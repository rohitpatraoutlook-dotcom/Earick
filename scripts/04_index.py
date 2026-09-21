"""
Stage 4: Build a TF-IDF index from chunks.jsonl.

Input:  data/chunks/chunks.jsonl
Output: data/chunks/index.json

index.json format:
    {
      "N": <number of chunks>,
      "idf": {"token": idf_value, ...},
      "docs": [
        {"id": "chunk_000000", "tf": {"token": count, ...}, "len": <word_count>},
        ...
      ]
    }

Only tokens appearing in >=2 documents are kept, to shrink the index.
Stopwords are removed.
"""

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CHUNKS = ROOT / "data" / "chunks" / "chunks.jsonl"
INDEX = ROOT / "data" / "chunks" / "index.json"


STOPWORDS = set("""
a an and or but if then of in on at to for with by from as is are was were
be been being this that these those it its into over under such than so
not no nor can could may might will would shall should do does did have has
had there their they them he she we you your our i me my mine us
also each other any all more most some few both many much very only just
about above after again against before below between during through under
while same own further once here there when where why how what which who
both each few more most other some such no nor only own same so than too
""".split())


TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]{1,}")


def tokenize(text: str) -> list:
    """Lowercase, extract word tokens (length >= 2, may contain hyphens)."""
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


def main():
    if not CHUNKS.exists():
        sys.exit(f"Missing {CHUNKS}. Run 03_chunk.py first.")

    print(f"📖 Reading chunks from {CHUNKS}")

    docs = []           # list of (id, Counter, total_words)
    df_counter = Counter()   # document frequency per token

    with CHUNKS.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            tokens = tokenize(rec["text"])
            tf = Counter(tokens)
            docs.append({
                "id": rec["id"],
                "tf": tf,
                "len": len(tokens),
            })
            for token in tf:
                df_counter[token] += 1

    N = len(docs)
    print(f"   → {N} chunks, {len(df_counter)} unique tokens")

    # Compute IDF: log((N + 1) / (df + 1)) + 1
    idf = {
        token: math.log((N + 1) / (df + 1)) + 1.0
        for token, df in df_counter.items()
        if df >= 2   # keep only tokens appearing in >=2 chunks
    }
    print(f"   → {len(idf)} tokens kept (df >= 2)")

    # Compact doc representation: only keep tokens that survived
    compact_docs = []
    for d in docs:
        kept = {t: c for t, c in d["tf"].items() if t in idf}
        if kept:
            compact_docs.append({
                "id": d["id"],
                "len": d["len"],
                "tf": kept,
            })

    out = {
        "N": N,
        "idf": {k: round(v, 5) for k, v in idf.items()},
        "docs": compact_docs,
    }

    INDEX.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))

    size_mb = INDEX.stat().st_size / 1024 / 1024
    print(f"✅ Wrote index → {INDEX}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
