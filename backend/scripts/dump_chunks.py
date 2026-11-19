"""Export the crawled chunks (url, section, text) to JSONL so gold labels can be checked against real page text.
Usage: python scripts/dump_chunks.py > chunks.jsonl"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings  # noqa: E402

conn = sqlite3.connect(str(get_settings().sqlite_path))
for url, section, text in conn.execute("SELECT url, section_path, text FROM chunks ORDER BY url, rowid"):
    print(json.dumps({"url": url, "section": section, "text": text}, ensure_ascii=False))
