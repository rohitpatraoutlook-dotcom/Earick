#!/usr/bin/env python3
"""
Earick CLI — the single entry point for the whole project.

Usage:
    python earick.py add <pdf_path> "<Title>" "<Author>" [--serve]
    python earick.py serve
    python earick.py list
    python earick.py remove <book_id>
    python earick.py rebuild
"""
import argparse
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from earick import Library


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def slugify(text: str) -> str:
    """Turn a title into a filesystem-safe book_id."""
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:40] or "book"


def unique_book_id(lib: Library, base: str) -> str:
    """If base exists, append _2, _3, ..."""
    if base not in lib.books:
        return base
    i = 2
    while f"{base}_{i}" in lib.books:
        i += 1
    return f"{base}_{i}"


def check_pdf(path: Path) -> None:
    if not path.exists():
        sys.exit(f"❌ PDF not found: {path}")
    if path.suffix.lower() != ".pdf":
        sys.exit(f"❌ Not a PDF: {path}")
    if path.stat().st_size < 10_000:
        sys.exit(f"❌ File too small to be a book: {path.stat().st_size} bytes")


def print_banner(text: str) -> None:
    print()
    print("─" * 60)
    print(f"  {text}")
    print("─" * 60)


# ------------------------------------------------------------------
# Commands
# ------------------------------------------------------------------
def cmd_add(args) -> None:
    lib = Library(ROOT)

    pdf_src = Path(args.pdf).expanduser().resolve()
    check_pdf(pdf_src)

    title = args.title.strip()
    author = args.author.strip()

    # Derive a book_id
    if args.id:
        book_id = args.id.strip()
    else:
        book_id = unique_book_id(lib, slugify(title))

    print_banner(f"Adding book: {title}")
    print(f"  book_id  : {book_id}")
    print(f"  author   : {author}")
    print(f"  pdf      : {pdf_src}")
    print(f"  size     : {pdf_src.stat().st_size / 1024 / 1024:.1f} MB")

    # Register (copies PDF into data/books/<id>/source.pdf)
    meta = {
        "book_id": book_id,
        "title": title,
        "author": author,
        "edition": args.edition or "",
        "year": args.year or 0,
        "level": args.level or "undergrad",
        "subjects": args.subjects.split(",") if args.subjects else [],
    }
    book = lib.add_book(book_id, meta, pdf_src=pdf_src)
    print(f"  ✓ registered + copied to {book.pdf_path}")

    # Ingest (resumable — skips stages whose output exists)
    print_banner("Running pipeline")
    t0 = time.time()
    result = book.ingest(progress=lambda stage: print(f"  → {stage}"))
    elapsed = time.time() - t0

    print(f"  ✓ status   : {result['status']}")
    print(f"  ✓ pages    : {result.get('pages_extracted', 0)}")
    print(f"  ✓ chunks   : {book.chunk_count()}")
    print(f"  ✓ took     : {elapsed/60:.1f} min")

    # Rebuild the merged index across all books
    print_banner("Rebuilding merged index")
    t0 = time.time()
    n_chunks = lib.rebuild_merged_chunks()
    print(f"  ✓ merged   : {n_chunks} chunks from {len(lib.books)} books")
    stats = lib.rebuild_index()
    print(f"  ✓ indexed  : N={stats['N']}  vocab={stats['vocab']}  "
          f"size={stats['bytes']/1024/1024:.1f} MB  ({time.time()-t0:.1f}s)")

    print_banner("Done ✅")
    print(f"  Library now has {len(lib.books)} books.")

    if args.serve:
        cmd_serve(args)


def cmd_serve(args) -> None:
    print_banner("Starting Earick server")
    # Import here so `add` without --serve doesn't need Flask if user only adds
    from app import app
    app.run(host="0.0.0.0", port=5000, debug=False)


def cmd_list(args) -> None:
    lib = Library(ROOT)
    if not lib.books:
        print("📚 No books registered yet.")
        print("   Add one: python earick.py add <pdf> \"Title\" \"Author\"")
        return
    print(f"📚 {len(lib.books)} books:\n")
    for bid, b in lib.books.items():
        status = "✓ ready" if b.is_ready() else "✗ not ingested"
        print(f"  {bid:25s} {status:14s} {b.chunk_count():5d} chunks")
        print(f"    {b.meta.get('title','')} — {b.meta.get('author','')}")


def cmd_remove(args) -> None:
    lib = Library(ROOT)
    bid = args.book_id
    if bid not in lib.books:
        sys.exit(f"❌ Unknown book_id: {bid}")
    lib.remove_book(bid, delete_files=True)
    print(f"✓ Removed {bid}")
    print_banner("Rebuilding merged index")
    lib.rebuild_merged_chunks()
    stats = lib.rebuild_index()
    print(f"✓ Rebuilt: N={stats['N']}  vocab={stats['vocab']}")


def cmd_rebuild(args) -> None:
    lib = Library(ROOT)
    print_banner("Rebuilding merged index")
    n = lib.rebuild_merged_chunks()
    print(f"  ✓ merged: {n} chunks")
    stats = lib.rebuild_index()
    print(f"  ✓ index : N={stats['N']}  vocab={stats['vocab']}  "
          f"{stats['bytes']/1024/1024:.1f} MB")


# ------------------------------------------------------------------
# Argument parsing
# ------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        prog="earick",
        description="Earick — multi-book physics RAG assistant",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # add
    a = sub.add_parser("add", help="Add a PDF book and rebuild the index")
    a.add_argument("pdf", help="Path to the PDF (outside the project is fine)")
    a.add_argument("title", help="Book title")
    a.add_argument("author", help="Book author(s)")
    a.add_argument("--id", help="Custom book_id (default: slug of title)")
    a.add_argument("--edition", default="", help="Edition (e.g. '13th')")
    a.add_argument("--year", type=int, default=0, help="Year")
    a.add_argument("--level", default="undergrad",
                   choices=["intro", "undergrad", "grad"])
    a.add_argument("--subjects", default="",
                   help="Comma-separated subjects (e.g. 'quantum,relativity')")
    a.add_argument("--serve", action="store_true",
                   help="Start the server after ingest")
    a.set_defaults(func=cmd_add)

    # serve
    s = sub.add_parser("serve", help="Start the chatbot server")
    s.set_defaults(func=cmd_serve)

    # list
    l = sub.add_parser("list", help="List all registered books")
    l.set_defaults(func=cmd_list)

    # remove
    r = sub.add_parser("remove", help="Remove a book and rebuild index")
    r.add_argument("book_id")
    r.set_defaults(func=cmd_remove)

    # rebuild
    rb = sub.add_parser("rebuild", help="Rebuild the merged index")
    rb.set_defaults(func=cmd_rebuild)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
