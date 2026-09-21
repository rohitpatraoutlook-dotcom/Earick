"""
Batch-add all pending physics books, then rebuild index once at the end.
Sequential processing to keep CPU/memory manageable.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earick import Library

ROOT = Path(__file__).resolve().parent.parent
DOWNLOAD = Path("/data/data/com.termux/files/home/storage/downloads")

BOOKS = [
    # (pdf filename, book_id, title, author, edition, year, level, subjects)
    ("intro_physics_1.pdf", "introductory_physics",
     "Introductory Physics", "Unknown", "", 0, "intro",
     "mechanics,waves,thermodynamics"),

    ("QuantumPhysics (1).pdf", "quantum_physics",
     "Quantum Physics", "Unknown", "", 0, "undergrad",
     "quantum,wave,mechanics"),

    ("CONDMAT (1).pdf", "condensed_matter",
     "Condensed Matter Physics", "Unknown", "", 0, "grad",
     "condensed matter,solid state"),

    ("[Pal Palash B] An Introductory Course of Particle Physics (1).pdf",
     "pal_particle_physics",
     "An Introductory Course of Particle Physics", "Palash B. Pal",
     "", 0, "undergrad", "particle,standard model"),

    ("irving_kaplan_nuclear_physics.pdf", "kaplan_nuclear",
     "Nuclear Physics", "Irving Kaplan", "2nd", 1963, "undergrad",
     "nuclear,radioactivity,fission"),

    ("phys3305-book (1).pdf", "phys3305",
     "PHYS3305 Course Book", "Unknown", "", 0, "undergrad",
     "physics"),
]


def main():
    lib = Library(ROOT)

    print("=" * 60)
    print(f"  Batch adding {len(BOOKS)} books")
    print(f"  Already in library: {list(lib.books.keys())}")
    print("=" * 60)
    print()

    for i, (filename, book_id, title, author, edition, year, level, subjects) in enumerate(BOOKS, 1):
        print()
        print("▓" * 60)
        print(f"  [{i}/{len(BOOKS)}] {title}")
        print(f"  book_id: {book_id}")
        print("▓" * 60)

        pdf_path = DOWNLOAD / filename
        if not pdf_path.exists():
            print(f"  ❌ PDF not found: {pdf_path}")
            print(f"  Skipping...")
            continue

        # Skip if already ingested
        if book_id in lib.books and lib.books[book_id].is_ready():
            print(f"  ⏭  Already ingested ({lib.books[book_id].chunk_count()} chunks) — skipping")
            continue

        # Register
        meta = {
            "book_id": book_id,
            "title": title,
            "author": author,
            "edition": edition,
            "year": year,
            "level": level,
            "subjects": subjects.split(",") if subjects else [],
        }

        try:
            book = lib.add_book(book_id, meta, pdf_src=pdf_path)
            print(f"  ✓ registered + copied ({pdf_path.stat().st_size/1024/1024:.1f} MB)")

            t0 = time.time()
            result = book.ingest(progress=lambda s: print(f"     → {s}"))
            elapsed = time.time() - t0

            print(f"  ✓ status   : {result['status']}")
            print(f"  ✓ pages    : {result.get('pages_extracted', 0)}")
            print(f"  ✓ chunks   : {book.chunk_count()}")
            print(f"  ✓ took     : {elapsed/60:.1f} min")

        except Exception as e:
            print(f"  ❌ Failed: {e}")
            import traceback
            traceback.print_exc()
            continue

    # Rebuild index ONCE at the end
    print()
    print("▓" * 60)
    print("  Rebuilding merged index (final step)")
    print("▓" * 60)

    t0 = time.time()
    n_chunks = lib.rebuild_merged_chunks()
    print(f"  ✓ merged chunks: {n_chunks}")

    stats = lib.rebuild_index()
    print(f"  ✓ indexed: N={stats['N']}  vocab={stats['vocab']}  "
          f"size={stats['bytes']/1024/1024:.1f} MB")
    print(f"  ✓ took: {(time.time()-t0)/60:.1f} min")

    print()
    print("=" * 60)
    print(f"  ✅ DONE — Library now has {len(lib.books)} books")
    print("=" * 60)
    for bid, b in lib.books.items():
        status = "✓" if b.is_ready() else "✗"
        print(f"  {status} {bid:24s} {b.chunk_count():5d} chunks  {b.meta.get('title','')}")


if __name__ == "__main__":
    main()
