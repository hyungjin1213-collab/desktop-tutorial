from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from config import DATA_DIR, OUTPUT_DIR

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
FACULTY_AGENT_MODEL = os.getenv("FACULTY_AGENT_MODEL", "gpt-5.6-luna").strip()
FACULTY_AGENT_SOURCE_LIMIT = int(os.getenv("FACULTY_AGENT_SOURCE_LIMIT", "2"))
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
REQUEST_TIMEOUT_SECONDS = 120

COLUMNS = [
    "source_id", "name", "title", "university", "department", "email",
    "profile_url", "source_page", "research_field", "evidence",
    "agent_confidence",
]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str).fillna("")


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _source_key(row: pd.Series | dict) -> str:
    return str(row.get("source_id", "")).strip()


def _extract_output_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    chunks: list[str] = []
    for item in data.get("output", []) or []:
        for part in item.get("content", []) or []:
            if part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    return "\n".join(chunks).strip()


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "source_page": {"type": "string"},
            "faculty": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "title": {"type": "string"},
                        "email": {"type": "string"},
                        "profile_url": {"type": "string"},
                        "research_field": {"type": "string"},
                        "evidence": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    },
                    "required": [
                        "name", "title", "email", "profile_url",
                        "research_field", "evidence", "confidence",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["source_page", "faculty"],
        "additionalProperties": False,
    }


def _agent_request(source: pd.Series) -> dict[str, Any]:
    university = _clean(source.get("university", ""))
    department = _clean(source.get("department", ""))
    hint_url = _clean(source.get("faculty_url", ""))

    prompt = f"""
Find the CURRENT faculty/PI roster for the following Korean university unit.

University: {university}
Department or school: {department}
Official faculty-page hint: {hint_url or "(none)"}

Use web search and inspect official university/department pages. Prefer the supplied
official page when valid, but search for a better official faculty directory if needed.

Goal: extract ONLY actual current faculty/PIs. Do not include navigation text, majors,
departments, introductions, students, postdocs, staff, emeritus, adjunct, visiting,
honorary, or administrative-only entries unless they are also clearly current faculty.

For each person:
- name: actual person's name
- title: professor / associate professor / assistant professor or Korean equivalent
- email: official email if shown, otherwise empty string
- profile_url: official personal/faculty profile if available, otherwise the official roster page
- research_field: short field if directly stated, otherwise empty string
- evidence: a very short phrase describing the official-page evidence
- confidence: high only when the official page clearly identifies the person as current faculty

Do not guess names from menus or headings. If uncertain, omit the person.
Return the complete roster visible from authoritative official sources, not a sample.
""".strip()

    payload = {
        "model": FACULTY_AGENT_MODEL,
        "input": prompt,
        "tools": [{"type": "web_search"}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "faculty_roster",
                "schema": _schema(),
                "strict": True,
            }
        },
    }

    r = requests.post(
        OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    data = r.json()
    raw = _extract_output_text(data)
    if not raw:
        raise RuntimeError("OpenAI response contained no output text")
    return json.loads(raw)


def collect_faculty_with_agent() -> pd.DataFrame:
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is missing. Add it in GitHub repository Settings > "
            "Secrets and variables > Actions > New repository secret."
        )

    sources = _read_csv(DATA_DIR / "faculty_sources.csv")
    out_path = OUTPUT_DIR / "faculty_directory_agent.csv"
    error_path = OUTPUT_DIR / "faculty_agent_errors.csv"
    existing = _read_csv(out_path)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if sources.empty:
        empty = pd.DataFrame(columns=COLUMNS)
        empty.to_csv(out_path, index=False, encoding="utf-8-sig")
        return empty

    enabled = sources[
        sources.get("enabled", "yes").astype(str).str.casefold().isin({"yes", "true", "1"})
    ].copy()

    done_sources = set(existing.get("source_id", [])) if not existing.empty else set()
    pending = enabled[~enabled["source_id"].isin(done_sources)].head(FACULTY_AGENT_SOURCE_LIMIT)

    print(
        f"Faculty agent: {len(done_sources)} sources done / {len(enabled)} enabled; "
        f"processing {len(pending)} now",
        flush=True,
    )

    if pending.empty:
        return existing if not existing.empty else pd.DataFrame(columns=COLUMNS)

    all_new: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    for i, (_, src) in enumerate(pending.iterrows(), start=1):
        source_id = _source_key(src)
        university = _clean(src.get("university", ""))
        department = _clean(src.get("department", ""))
        print(f"[{i}/{len(pending)}] agent search: {source_id} | {university} | {department}", flush=True)

        try:
            result = _agent_request(src)
            source_page = _clean(result.get("source_page", "")) or _clean(src.get("faculty_url", ""))
            people = result.get("faculty", []) or []

            valid_count = 0
            for person in people:
                name = _clean(person.get("name", ""))
                title = _clean(person.get("title", ""))
                confidence = _clean(person.get("confidence", "low")).casefold()
                if not name or not title:
                    continue
                if confidence == "low":
                    continue

                all_new.append({
                    "source_id": source_id,
                    "name": name,
                    "title": title,
                    "university": university,
                    "department": department,
                    "email": _clean(person.get("email", "")),
                    "profile_url": _clean(person.get("profile_url", "")) or source_page,
                    "source_page": source_page,
                    "research_field": _clean(person.get("research_field", "")),
                    "evidence": _clean(person.get("evidence", "")),
                    "agent_confidence": confidence,
                })
                valid_count += 1

            print(f"  -> accepted {valid_count} faculty", flush=True)

            # Save after every source, so a later failure never loses prior work.
            batch = pd.DataFrame(all_new, columns=COLUMNS)
            merged = pd.concat([existing, batch], ignore_index=True) if not existing.empty else batch
            if not merged.empty:
                merged = merged.drop_duplicates(
                    subset=["source_id", "name", "university", "department"],
                    keep="last",
                )
            merged.to_csv(out_path, index=False, encoding="utf-8-sig")

        except Exception as exc:
            errors.append({
                "source_id": source_id,
                "university": university,
                "department": department,
                "error": f"{type(exc).__name__}: {exc}",
            })
            print(f"  -> ERROR: {type(exc).__name__}: {exc}", flush=True)

    current_errors = _read_csv(error_path)
    new_errors = pd.DataFrame(
        errors,
        columns=["source_id", "university", "department", "error"],
    )
    merged_errors = (
        pd.concat([current_errors, new_errors], ignore_index=True)
        if not current_errors.empty else new_errors
    )
    if not merged_errors.empty:
        merged_errors = merged_errors.drop_duplicates(subset=["source_id"], keep="last")
    merged_errors.to_csv(error_path, index=False, encoding="utf-8-sig")

    final = _read_csv(out_path)
    print(f"Faculty agent saved {len(final)} total people", flush=True)
    return final


if __name__ == "__main__":
    df = collect_faculty_with_agent()
    print(f"Faculty agent rows: {len(df)}")
