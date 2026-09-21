"""
One-time migration: add book_id + new ID format to Young & Freedman chunks.
Safe: writes to a temp file, then atomically renames.
"""
import json
from pathlib import Path

CHUNKS = Path("data/books/young_freedman/chunks/chunks.jsonl")
BOOK_ID = "young_freedman"

if not CHUNKS.exists():
    raise SystemExit(f"Missing: {CHUNKS}")

lines = CHUNKS.read_text(encoding="utf-8").splitlines()
print(f"Reading {len(lines)} chunks...")

out_lines = []
changed = 0
for i, line in enumerate(lines):
    if not line.strip():
        continue
    rec = json.loads(line)

    # Normalize the ID to the new format
    old_id = rec.get("id", f"chunk_{i:06d}")
    if not old_id.startswith(f"{BOOK_ID}:"):
        new_id = f"{BOOK_ID}:{old_id}"
    else:
        new_id = old_id

    # Add book_id if missing
    if rec.get("book_id") != BOOK_ID:
        rec["book_id"] = BOOK_ID
        changed += 1

    rec["id"] = new_id
    out_lines.append(json.dumps(rec, ensure_ascii=False))

# Write atomically
tmp = CHUNKS.with_suffix(".jsonl.tmp")
tmp.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
tmp.rename(CHUNKS)

print(f"✅ Updated {changed} chunks with book_id")
print(f"   File size: {CHUNKS.stat().st_size / 1024 / 1024:.1f} MB")
print(f"   Sample first record:")
first = json.loads(CHUNKS.read_text(encoding="utf-8").splitlines()[0])
print(f"     id      = {first['id']}")
print(f"     book_id = {first['book_id']}")
print(f"     pages   = {first['page_start']}-{first['page_end']}")
