"""
Ingest a book by ID into the Earick library.

Usage:
    python scripts/ingest_book.py <book_id>

Example:
    python scripts/ingest_book.py hobson_gr
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earick import Library


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/ingest_book.py <book_id>")
        print()
        lib = Library(Path(__file__).resolve().parent.parent)
        print("Available books:")
        for bid, b in lib.books.items():
            status = "✓ ready" if b.is_ready() else "✗ not ingested"
            print(f"  {bid:20s} {status}")
        sys.exit(1)

    book_id = sys.argv[1]
    root = Path(__file__).resolve().parent.parent
    lib = Library(root)

    if book_id not in lib.books:
        sys.exit(f"Unknown book_id: {book_id}. Register it first.")

    book = lib.books[book_id]
    print(f"📖 {book.meta.get('title', book_id)}")
    print(f"   PDF: {book.pdf_path}")
    print()

    result = book.ingest(progress=lambda stage: print(f"   → {stage}"))
    print()
    print(f"   status: {result['status']}")
    print(f"   chunks: {book.chunk_count()}")


if __name__ == "__main__":
    main()
