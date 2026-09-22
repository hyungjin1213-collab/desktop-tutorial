from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
WEB_DIR = BASE_DIR / "web"

OPENALEX_BASE_URL = "https://api.openalex.org"
OPENALEX_EMAIL = os.getenv("OPENALEX_EMAIL", "")
REQUEST_TIMEOUT = 30

KOREA_COUNTRY_CODE = "KR"
MIN_SHARED_PAPERS = int(os.getenv("MIN_SHARED_PAPERS", "2"))
MAX_REVIEW_CANDIDATES = int(os.getenv("MAX_REVIEW_CANDIDATES", "300"))
