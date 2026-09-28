"""Download the tokenizer data needed by the offline Windows build."""

from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "assets" / "tiktoken_cache"
CACHE.mkdir(parents=True, exist_ok=True)
os.environ["TIKTOKEN_CACHE_DIR"] = str(CACHE)

import tiktoken


tiktoken.get_encoding("cl100k_base")
print(f"Prepared tiktoken cache in {CACHE}")
