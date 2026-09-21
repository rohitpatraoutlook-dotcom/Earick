"""
Earick two-line book ingestion.

Usage in a Python REPL or script:

    from earick_add import earick

    book = "/storage/downloads/some_physics_book.pdf"
    earick(book)

That's it. The function:
  - cleans the filename into a title
  - derives a safe book_id
  - infers author/level from common patterns (best-effort)
  - runs extract -> clean -> chunk
  - rebuilds the merged TF-IDF index

If you want to override the metadata:

    earick(book, title="Real Title", author="Real Author", level="grad")

Existing books are skipped automatically (idempotent).
"""

import re
import sys
import time
from pathlib import Path

# Make sure `earick` package is importable
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from earick import Library


# ------------------------------------------------------------------
# Metadata inference from filename
# ------------------------------------------------------------------
LEVEL_HINTS = [
    ("intro", ["intro", "introduction", "elementary", "basic", "fundamental"]),
    ("grad", ["graduate", "advanced", "quantum field", "string theory",
              "general relativity", "condensed matter"]),
    ("undergrad", ["quantum", "nuclear", "particle", "mechanics",
                   "electromagnetism", "thermodynamics", "statistical"]),
]

SUBJECT_HINTS = {
    "quantum": ["quantum", "qm", "wave mechanics"],
    "relativity": ["relativity", "gr", "general relativity", "special relativity"],
    "mechanics": ["mechanics", "classical mechanics", "newtonian"],
    "electromagnetism": ["electro", "em", "maxwell", "electricity", "magnetism"],
    "thermodynamics": ["thermo", "statistical mechanics", "entropy"],
    "nuclear": ["nuclear", "fission", "fusion", "radioactiv"],
    "particle": ["particle", "standard model", "quark", "higgs"],
    "condensed": ["condensed", "solid state", "superconduct"],
    "optics": ["optics", "photonic", "laser"],
    "string": ["string theory", "brane", "superstring"],
    "cosmology": ["cosmology", "universe", "big bang"],
    "mathematical": ["mathematical", "methods", "math"],
}


def clean_title(filename: str) -> str:
    """Turn a filename into a human-readable title."""
    name = Path(filename).stem
    # strip common junk
    name = re.sub(r"\[[^\]]*\]", " ", name)          # [Author Name]
    name = re.sub(r"\([^)]*\)", " ", name)            # (BookFi), (1), etc.
    name = re.sub(r"(?i)\b(bookfi|z-lib|libgen|pdf|ebook|book)\b", " ", name)
    name = re.sub(r"[_\-\.]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()

    # Title-case but keep small words lowercase
    small = {"a", "an", "the", "of", "in", "on", "at", "to", "for",
             "and", "or", "by", "with", "from"}
    words = name.split()
    out = []
    for i, w in enumerate(words):
        if i > 0 and w.lower() in small:
            out.append(w.lower())
        elif w.isupper() and len(w) > 1:
            out.append(w)          # keep acronyms
        else:
            out.append(w.capitalize())
    title = " ".join(out)
    return title or "Untitled Physics Book"


def slugify(text: str) -> str:
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:40] or "book"


def unique_book_id(lib: Library, base: str) -> str:
    if base not in lib.books:
        return base
    i = 2
    while f"{base}_{i}" in lib.books:
        i += 1
    return f"{base}_{i}"


def infer_author(filename: str) -> str:
    """Try to pull an author out of common filename patterns."""
    # [Author Name] ...
    m = re.search(r"\[([^\]]+)\]", filename)
    if m:
        return m.group(1).strip()
    # "by Author Name"
    m = re.search(r"(?i)\bby\s+([A-Z][A-Za-z\.\-]+(?:\s+[A-Z][A-Za-z\.\-]+){0,2})",
                  filename)
    if m:
        return m.group(1).strip()
    return "Unknown"


def infer_level(text: str) -> str:
    low = text.lower()
    for level, hints in LEVEL_HINTS:
        if any(h in low for h in hints):
            return level
    return "undergrad"


def infer_subjects(text: str) -> list:
    low = text.lower()
    out = []
    for subject, hints in SUBJECT_HINTS.items():
        if any(h in low for h in hints):
            out.append(subject)
    return out


# ------------------------------------------------------------------
# The one-line API
# ------------------------------------------------------------------
def earick(pdf_path, title=None, author=None, edition="",
           year=0, level=None, subjects=None, book_id=None,
           rebuild=True, verbose=True):
    """
    Add a book to the Earick library.

    Minimum usage:
        earick("/storage/downloads/some_book.pdf")

    Optional overrides:
        earick(pdf, title="Real Title", author="Real Author", level="grad")
    """
    pdf = Path(str(pdf_path)).expanduser()
    if not pdf.exists():
        raise FileNotFoundError(f"PDF not found: {pdf}")
    if pdf.suffix.lower() != ".pdf":
        raise ValueError(f"Not a PDF: {pdf}")
    if pdf.stat().st_size < 10_000:
        raise ValueError(f"File too small to be a book: {pdf.stat().st_size} bytes")

    # Infer metadata from filename if not supplied
    fname = pdf.name
    title = title or clean_title(fname)
    author = author or infer_author(fname)
    level = level or infer_level(title + " " + fname)
    subjects = subjects if subjects is not None else infer_subjects(title + " " + fname)

    lib = Library(ROOT)
    bid = book_id or unique_book_id(lib, slugify(title))

    if verbose:
        print()
        print("━" * 60)
        print(f"  Adding: {title}")
        print("━" * 60)
        print(f"  book_id  : {bid}")
        print(f"  author   : {author}")
        print(f"  level    : {level}")
        print(f"  subjects : {', '.join(subjects) if subjects else '(none)'}")
        print(f"  pdf      : {pdf}")
        print(f"  size     : {pdf.stat().st_size / 1024 / 1024:.1f} MB")

    # Skip if already ingested
    if bid in lib.books and lib.books[bid].is_ready():
        if verbose:
            print(f"  → already ingested ({lib.books[bid].chunk_count()} chunks) — skipping")
        return lib.books[bid]

    meta = {
        "book_id": bid,
        "title": title,
        "author": author,
        "edition": edition,
        "year": year,
        "level": level,
        "subjects": subjects,
    }

    book = lib.add_book(bid, meta, pdf_src=pdf)
    if verbose:
        print(f"  ✓ registered + copied")

    t0 = time.time()
    result = book.ingest(progress=(lambda s: print(f"     → {s}")) if verbose else None)
    elapsed = time.time() - t0

    if verbose:
        print(f"  ✓ pages   : {result.get('pages_extracted', 0)}")
        print(f"  ✓ chunks  : {book.chunk_count()}")
        print(f"  ✓ took    : {elapsed/60:.1f} min")

    if rebuild:
        if verbose:
            print()
            print("  Rebuilding merged index...")
        t0 = time.time()
        n = lib.rebuild_merged_chunks()
        stats = lib.rebuild_index()
        if verbose:
            print(f"  ✓ merged  : {n} chunks from {len(lib.books)} books")
            print(f"  ✓ indexed : N={stats['N']}  vocab={stats['vocab']}  "
                  f"size={stats['bytes']/1024/1024:.1f} MB  "
                  f"({time.time()-t0:.1f}s)")

    if verbose:
        print("━" * 60)
        print(f"  ✅ Library now has {len(lib.books)} books")
        print("━" * 60)
        print()

    return book


# ------------------------------------------------------------------
# CLI fallback: python earick_add.py <pdf>
# ------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python earick_add.py /path/to/book.pdf")
        sys.exit(1)
    earick(sys.argv[1])
