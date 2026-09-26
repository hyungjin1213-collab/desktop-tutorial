"""Research keywords and techniques per professor.

Sources, from the works already fetched for the collaboration graph:
- MeSH descriptors (assigned by PubMed indexers; most precise for bio/med),
  with major topics counting more;
- OpenAlex keywords (scored per paper).

Weighting: the professor's role on the paper (last > first > middle author),
recency (halves every 6 years) and, across professors, TF-IDF so that a
term shared by everyone (Signal Transduction) ranks below one that sets a
lab apart (CAR-T). Demographic / study-design MeSH "check tags" are dropped.

Techniques come from data/technique_terms.csv: many spellings of one method
(FACS, flow cytometry, Flow Cytometry) count toward one canonical technique
(유세포분석), so the map can filter on it. Every other term is a topic keyword.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROLE_WEIGHT = {"last": 1.0, "first": 0.8, "middle": 0.25}
MAJOR_MESH_BONUS = 1.5
HALF_LIFE_YEARS = 6.0
TOP_KEYWORDS = 12
TOP_TECHNIQUES = 8
# A technique must show up in at least this many of the professor's papers:
# one co-authored paper that used organoids does not make an organoid lab.
MIN_TECHNIQUE_WORKS = 2

# MeSH check tags and study-design terms: true for most papers, say nothing about a lab.
GENERIC_TERMS = {t.casefold() for t in [
    "Humans", "Animals", "Mice", "Rats", "Male", "Female", "Adult", "Middle Aged", "Aged",
    "Aged, 80 and over", "Young Adult", "Adolescent", "Child", "Child, Preschool", "Infant",
    "Infant, Newborn", "Pregnancy", "Republic of Korea", "Korea", "Retrospective Studies",
    "Prospective Studies", "Cohort Studies", "Cross-Sectional Studies", "Case-Control Studies",
    "Follow-Up Studies", "Treatment Outcome", "Risk Factors", "Time Factors", "Incidence",
    "Prevalence", "Prognosis", "Surveys and Questionnaires", "Reproducibility of Results",
    "Sensitivity and Specificity", "Logistic Models", "Multivariate Analysis", "Odds Ratio",
    "Kaplan-Meier Estimate", "Survival Rate", "ROC Curve", "Cells, Cultured", "Cell Line",
    "Cell Line, Tumor", "In Vitro Techniques", "Mice, Inbred C57BL", "Mice, Inbred BALB C",
    "Rats, Sprague-Dawley", "Mice, Nude", "Disease Models, Animal", "Dose-Response Relationship, Drug",
    "Models, Biological", "Medicine", "Biology", "Chemistry",
    "Internal medicine", "Computer science", "Materials science", "Pathology",
]}

DEFAULT_TECHNIQUES_FILE = Path(__file__).resolve().parents[1] / "data" / "technique_terms.csv"


def load_techniques(path: Path = DEFAULT_TECHNIQUES_FILE) -> list[tuple[str, str, re.Pattern]]:
    """[(Korean label, English label, compiled pattern)] from data/technique_terms.csv.

    Many spellings map to one technique (FACS, flow cytometry -> 유세포분석),
    so techniques can be counted and filtered on.
    """
    if not path.exists():
        return []
    df = pd.read_csv(path, dtype=str).fillna("")
    return [(r["technique"], r["label_en"], re.compile(r["pattern"], re.I)) for _, r in df.iterrows() if r["pattern"]]


class KeywordCollector:
    """Research-topic keywords and techniques, kept apart.

    A term matching the technique dictionary counts toward that technique
    (canonical label); every other term is a research-topic keyword.
    """

    def __init__(self, now_year: int, techniques_file: Path = DEFAULT_TECHNIQUES_FILE):
        self.now = now_year
        self.techniques = load_techniques(techniques_file)
        self.label_en = {ko: en for ko, en, _ in self.techniques}
        self.topics: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.methods: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.method_works: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.display: dict[str, str] = {}
        self._technique_cache: dict[str, str] = {}

    def technique_of(self, term: str) -> str:
        key = term.casefold()
        if key not in self._technique_cache:
            self._technique_cache[key] = next((ko for ko, _, pat in self.techniques if pat.search(term)), "")
        return self._technique_cache[key]

    def _add(self, professor_id: str, name: str, weight: float, seen: set[str]) -> None:
        key = name.casefold()
        if not name or key in GENERIC_TERMS or key in seen:
            return
        seen.add(key)
        technique = self.technique_of(name)
        if technique:
            # Several spellings in one paper (Flow Cytometry + FACS) count once.
            if "\0" + technique in seen:
                return
            seen.add("\0" + technique)
            self.methods[professor_id][technique] += weight
            self.method_works[professor_id][technique] += 1
        else:
            self.display.setdefault(key, name)
            self.topics[professor_id][key] += weight

    def add_work(self, professor_id: str, position: str, work: dict) -> None:
        role = ROLE_WEIGHT.get(position, ROLE_WEIGHT["middle"])
        year = int(work.get("publication_year") or 0)
        age = max(self.now - year, 0) if year else 2 * HALF_LIFE_YEARS
        base = role * 0.5 ** (age / HALF_LIFE_YEARS)
        seen: set[str] = set()
        for mesh in work.get("mesh") or []:
            name = str(mesh.get("descriptor_name", "")).strip()
            self._add(professor_id, name, base * (MAJOR_MESH_BONUS if mesh.get("is_major_topic") else 1.0), seen)
        for kw in work.get("keywords") or []:
            name = str(kw.get("display_name", "")).strip()
            self._add(professor_id, name, base * float(kw.get("score") or 0.5), seen)

    @staticmethod
    def _tfidf(weights: dict[str, dict[str, float]]) -> dict[str, list[tuple[str, float]]]:
        n = max(len(weights), 1)
        df: dict[str, int] = defaultdict(int)
        for terms in weights.values():
            for key in terms:
                df[key] += 1
        return {
            pid: sorted(((k, w * math.log(1 + n / df[k])) for k, w in terms.items()), key=lambda kv: -kv[1])
            for pid, terms in weights.items()
        }

    def top_terms(self) -> dict[str, dict[str, list[tuple[str, float]]]]:
        """{professor_id: {"keywords": [(term, score)], "techniques": [(label, score)]}}."""
        frequent = {
            pid: {t: w for t, w in terms.items() if self.method_works[pid][t] >= MIN_TECHNIQUE_WORKS}
            for pid, terms in self.methods.items()
        }
        topics, methods = self._tfidf(self.topics), self._tfidf({p: t for p, t in frequent.items() if t})
        out = {}
        for pid in set(topics) | set(methods):
            out[pid] = {
                "keywords": [(self.display[k], round(v, 3)) for k, v in topics.get(pid, [])[:TOP_KEYWORDS]],
                "techniques": [(k, round(v, 3)) for k, v in methods.get(pid, [])[:TOP_TECHNIQUES]],
            }
        return out

    def to_frame(self) -> pd.DataFrame:
        rows = []
        for pid, groups in self.top_terms().items():
            for kind, items in groups.items():
                for rank, (term, score) in enumerate(items, start=1):
                    rows.append({"professor_id": pid, "kind": kind[:-1], "rank": rank, "term": term,
                                 "term_en": self.label_en.get(term, "") if kind == "techniques" else term,
                                 "score": score})
        return pd.DataFrame(rows, columns=["professor_id", "kind", "rank", "term", "term_en", "score"])
