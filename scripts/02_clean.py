"""
Stage 2: Clean extracted page text.

Input:  data/raw/page_XXXXX.txt
Output: data/clean/page_XXXXX.txt

Cleaning steps:
- Fix typographic ligatures (ﬁ, ﬂ, ﬀ, ﬃ, ﬄ)
- Join hyphenated line breaks (nega-\ntive -> negative)
- Strip standalone page numbers
- Strip running headers (lines that repeat across many pages)
- Normalize quotes, dashes, and whitespace
"""

import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
CLEAN_DIR = ROOT / "data" / "clean"
CLEAN_DIR.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------
# Ligature and punctuation normalization
# ----------------------------------------------------------------
CHAR_MAP = {
    "\ufb01": "fi",   # ﬁ
    "\ufb02": "fl",   # ﬂ
    "\ufb00": "ff",   # ﬀ
    "\ufb03": "ffi",  # ﬃ
    "\ufb04": "ffl",  # ﬄ
    "\ufb05": "ft",   # ﬅ
    "\ufb06": "st",   # ﬆ
    "\u2018": "'",    # ‘
    "\u2019": "'",    # ’
    "\u201c": '"',    # “
    "\u201d": '"',    # ”
    "\u2013": "-",    # –
    "\u2014": "--",   # —
    "\u2026": "...",  # …
    "\u00a0": " ",    # non-breaking space
    "\u2022": "*",    # bullet
}


def normalize_chars(text: str) -> str:
    for k, v in CHAR_MAP.items():
        text = text.replace(k, v)
    return text


# ----------------------------------------------------------------
# Running header / footer detection
# ----------------------------------------------------------------
def detect_running_lines(raw_files, sample_limit=400, min_count=8):
    """
    Scan the first N pages (spread out) and count how often each
    short line appears. Lines appearing frequently are running
    headers/footers -> remove.
    """
    counter = Counter()
    step = max(1, len(raw_files) // sample_limit)

    for i in range(0, len(raw_files), step):
        try:
            text = raw_files[i].read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for line in text.splitlines():
            s = line.strip()
            # Only short lines can be headers/footers
            if 3 <= len(s) <= 60 and not s.isdigit():
                counter[s] += 1

    # Threshold: appears in at least min_count pages
    running = {s for s, c in counter.items() if c >= min_count}
    return running


# ----------------------------------------------------------------
# Line-level filtering
# ----------------------------------------------------------------
PAGE_NUM_RE = re.compile(r"^\s*\d{1,4}\s*$")
CHAP_NUM_RE = re.compile(r"^\s*[A-Z]?\d{1,3}(\.\d+)?\s+[A-Z].*$")


def clean_page(text: str, running: set) -> str:
    text = normalize_chars(text)

    # Join hyphenated line breaks: "nega-\ntive" -> "negative"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    out_lines = []
    for line in text.splitlines():
        s = line.rstrip()
        stripped = s.strip()

        # Skip blank lines here (we re-add proper spacing later)
        if not stripped:
            out_lines.append("")
            continue

        # Skip standalone page numbers
        if PAGE_NUM_RE.match(stripped):
            continue

        # Skip running headers/footers
        if stripped in running:
            continue

        out_lines.append(s)

    text = "\n".join(out_lines)

    # Collapse 3+ blank lines to at most 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Collapse multiple spaces within a line
    text = re.sub(r" {2,}", " ", text)

    return text.strip()


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main():
    raw_files = sorted(RAW_DIR.glob("page_*.txt"))
    if not raw_files:
        sys.exit("No raw pages found. Run 01_extract.py first.")

    print(f"📖 Found {len(raw_files)} raw pages")

    print("🔍 Detecting running headers/footers (sampling)...")
    running = detect_running_lines(raw_files)
    print(f"   → {len(running)} repeating lines flagged for removal")
    if running:
        # Show a small sample
        for s in list(running)[:5]:
            print(f"     · {s[:60]}")
        if len(running) > 5:
            print(f"     ... and {len(running) - 5} more")

    print("🧹 Cleaning pages...")
    done = 0
    for f in raw_files:
        out = CLEAN_DIR / f.name
        if out.exists():
            continue
        try:
            raw = f.read_text(encoding="utf-8", errors="ignore")
            cleaned = clean_page(raw, running)
            out.write_text(cleaned, encoding="utf-8")
            done += 1
            if done % 200 == 0:
                print(f"   · {done}/{len(raw_files)}")
        except Exception as e:
            print(f"   ⚠️  {f.name}: {e}", file=sys.stderr)

    print(f"✅ Cleaned {done} pages → {CLEAN_DIR}")


if __name__ == "__main__":
    main()
