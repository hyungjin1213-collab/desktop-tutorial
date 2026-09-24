from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
WEB_DIR = BASE_DIR / "web"

OPENALEX_BASE_URL = "https://api.openalex.org"
OPENALEX_EMAIL = os.getenv("OPENALEX_EMAIL", "")
OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY", "").strip()
REQUEST_TIMEOUT = 30

KOREA_COUNTRY_CODE = "KR"
MIN_SHARED_PAPERS = int(os.getenv("MIN_SHARED_PAPERS", "2"))
MAX_AUTHORS_PER_WORK = int(os.getenv("MAX_AUTHORS_PER_WORK", "100"))
MAX_REVIEW_CANDIDATES = int(os.getenv("MAX_REVIEW_CANDIDATES", "300"))

WEB_VERIFY_LIMIT = int(os.getenv("WEB_VERIFY_LIMIT", "20"))
AUTO_YES_CONFIDENCE = float(os.getenv("AUTO_YES_CONFIDENCE", "0.90"))
AUTO_NO_CONFIDENCE = float(os.getenv("AUTO_NO_CONFIDENCE", "0.92"))
