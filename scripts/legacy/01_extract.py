"""
Stage 1: Extract text from book.pdf, one file per page.

Output: data/raw/page_00000.txt, page_00001.txt, ...
Resumable: skips pages already extracted.

Usage:
    python scripts/01_extract.py
    python scripts/01_extract.py --start 100 --end 200   # optional range
"""

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("PyMuPDF not found. Install with: pkg install python-pymupdf")


ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / "data" / "book.pdf"
RAW_DIR = ROOT / "data" / "raw"
PROGRESS_FILE = ROOT / "data" / "progress.json"

RAW_DIR.mkdir(parents=True, exist_ok=True)


def load_progress():
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text())
        except Exception:
            pass
    return {"pages_done": [], "last_page": -1}


def save_progress(progress):
    PROGRESS_FILE.write_text(json.dumps(progress))


def extract_page(doc, page_index):
    """Extract text from a single page, best-effort."""
    try:
        page = doc[page_index]
        # "text" mode preserves reading order, best for prose books
        return page.get_text("text")
    except Exception as e:
        print(f"  ⚠️  page {page_index}: {e}", file=sys.stderr)
        return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0, help="first page index")
    parser.add_argument("--end", type=int, default=None, help="last page index (exclusive)")
    args = parser.parse_args()

    if not PDF_PATH.exists():
        sys.exit(f"Missing PDF: {PDF_PATH}")

    doc = fitz.open(PDF_PATH)
    total = doc.page_count
    start = args.start
    end = args.end if args.end is not None else total

    print(f"📖 {PDF_PATH.name}  ·  {total} pages")
    print(f"📂 Output: {RAW_DIR}")
    print(f"🎯 Range:  {start} → {end - 1}")
    print("-" * 60)

    progress = load_progress()
    done_count = 0
    skipped = 0
    t0 = time.time()

    for i in range(start, end):
        out_file = RAW_DIR / f"page_{i:05d}.txt"
        if out_file.exists() and out_file.stat().st_size > 0:
            skipped += 1
            continue

        text = extract_page(doc, i)
        out_file.write_text(text, encoding="utf-8")
        done_count += 1

        # progress every 50 pages
        if done_count % 50 == 0:
            elapsed = time.time() - t0
            rate = done_count / elapsed if elapsed else 0
            remaining = end - i - 1
            eta_sec = remaining / rate if rate else 0
            print(f"  ✓ {i:5d}/{end}  ({rate:.1f} pg/s, ETA {eta_sec/60:.1f} min)")

        if done_count % 200 == 0:
            progress["last_page"] = i
            save_progress(progress)

    progress["last_page"] = end - 1
    save_progress(progress)
    doc.close()

    elapsed = time.time() - t0
    print("-" * 60)
    print(f"✅ Done: {done_count} extracted, {skipped} skipped (already existed)")
    print(f"⏱️  Took {elapsed/60:.1f} min")


if __name__ == "__main__":
    main()
