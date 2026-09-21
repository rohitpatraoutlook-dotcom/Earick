"""
Stage 3: Chunk cleaned pages into retrievable units.

Input:  data/clean/page_XXXXX.txt
Output: data/chunks/chunks.jsonl

Each chunk:
    {
      "id": "chunk_000001",
      "text": "...",
      "page_start": 40,
      "page_end": 40,
      "chapter": "Chapter 1 — Units, Physical Quantities, and Vectors",
      "keywords": ["vector", "component", "angle"],
      "word_count": 342
    }
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CLEAN_DIR = ROOT / "data" / "clean"
CHUNK_DIR = ROOT / "data" / "chunks"
CHUNK_DIR.mkdir(parents=True, exist_ok=True)
OUT = CHUNK_DIR / "chunks.jsonl"


# Chunking parameters
TARGET_WORDS = 350
MAX_WORDS = 500
OVERLAP_WORDS = 60
MIN_CHUNK_WORDS = 60


# Chapter detection — matches lines like "1.8 Components of Vectors" or "CHAPTER 1"
CHAPTER_LINE_RE = re.compile(r"^\s*(\d{1,2}\.\d{1,2}\s+[A-Z][A-Za-z ,\-]{3,80})$")
CHAPTER_BIG_RE = re.compile(r"^\s*CHAPTER\s+(\d{1,2})\s*$", re.IGNORECASE)


STOPWORDS = set("""
a an and or but if then of in on at to for with by from as is are was were
be been being this that these those it its into over under such than so
not no nor can could may might will would shall should do does did have has
had there their they them he she we you your our i me my mine us
also each other any all more most some few both many much very only just
""".split())


def extract_keywords(text: str, top: int = 10) -> list:
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", text.lower())
    words = [w for w in words if w not in STOPWORDS]
    return [w for w, _ in Counter(words).most_common(top)]


def split_paragraphs(text: str) -> list:
    """Split on one-or-more blank lines, return non-empty paragraph strings."""
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def chunk_page(text: str, target: int = TARGET_WORDS, hard_max: int = MAX_WORDS):
    """Yield chunk strings from a single page's text."""
    paragraphs = split_paragraphs(text)
    buf = []
    words = 0
    for p in paragraphs:
        pw = len(p.split())
        if words + pw > hard_max and buf:
            yield " ".join(buf).strip()
            # overlap: keep last N words of previous chunk
            tail = " ".join(buf).split()[-OVERLAP_WORDS:]
            buf = [" ".join(tail)] if tail else []
            words = len(tail)
        buf.append(p)
        words += pw
        if words >= target:
            yield " ".join(buf).strip()
            tail = " ".join(buf).split()[-OVERLAP_WORDS:]
            buf = [" ".join(tail)] if tail else []
            words = len(tail)
    if buf:
        joined = " ".join(buf).strip()
        if len(joined.split()) >= MIN_CHUNK_WORDS:
            yield joined


def main():
    clean_files = sorted(CLEAN_DIR.glob("page_*.txt"))
    if not clean_files:
        sys.exit("No cleaned pages found. Run 02_clean.py first.")

    print(f"📖 Found {len(clean_files)} cleaned pages")

    # Best-effort chapter tracking
    current_chapter = "Front Matter"

    idx = 0
    with OUT.open("w", encoding="utf-8") as fout:
        for f in clean_files:
            try:
                page_num = int(f.stem.split("_")[1])
            except (IndexError, ValueError):
                continue

            text = f.read_text(encoding="utf-8", errors="ignore")
            if not text.strip():
                continue

            # Look for a chapter marker in the first 5 lines
            for line in text.splitlines()[:5]:
                s = line.strip()
                m = CHAPTER_LINE_RE.match(s)
                if m:
                    current_chapter = m.group(1)
                    break
                m2 = CHAPTER_BIG_RE.match(s)
                if m2:
                    current_chapter = f"Chapter {m2.group(1)}"
                    break

            for chunk_text in chunk_page(text):
                wc = len(chunk_text.split())
                if wc < MIN_CHUNK_WORDS:
                    continue

                rec = {
                    "id": f"chunk_{idx:06d}",
                    "text": chunk_text,
                    "page_start": page_num,
                    "page_end": page_num,
                    "chapter": current_chapter,
                    "keywords": extract_keywords(chunk_text),
                    "word_count": wc,
                }
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                idx += 1
                if idx % 500 == 0:
                    print(f"   · {idx} chunks (page {page_num})")

    print(f"✅ Wrote {idx} chunks → {OUT}")
    print(f"   File size: {OUT.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
