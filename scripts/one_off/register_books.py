import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earick import Library

ROOT = Path(__file__).resolve().parent.parent
lib = Library(ROOT)

lib.add_book("young_freedman", {
    "book_id": "young_freedman",
    "title": "University Physics with Modern Physics",
    "author": "Young & Freedman",
    "edition": "13th",
    "year": 2011,
    "level": "intro",
    "subjects": ["mechanics", "thermodynamics", "electromagnetism",
                 "waves", "optics", "relativity", "quantum", "nuclear"],
})

lib.add_book("hobson_gr", {
    "book_id": "hobson_gr",
    "title": "General Relativity: An Introduction for Physicists",
    "author": "Hobson, Efstathiou & Lasenby",
    "edition": "1st",
    "year": 2006,
    "level": "undergrad",
    "subjects": ["relativity", "gravity", "cosmology", "differential geometry"],
})

print("✅ Registered:", list(lib.books.keys()))
print()
print(lib.catalog_path.read_text())
