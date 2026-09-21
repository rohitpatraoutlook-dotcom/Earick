"""
Earick multi-book library.

Two classes:
    Book     - one physics book: PDF -> chunks
    Library  - all books + merged index + diverse retrieval
"""

import json
import math
import re
import shutil
from collections import Counter
from pathlib import Path

import fitz  # PyMuPDF


# ============================================================
# Chunking constants
# ============================================================
TARGET_WORDS = 350
MAX_WORDS = 500
OVERLAP_WORDS = 60
MIN_CHUNK_WORDS = 60
MIN_DF = 2   # minimum doc frequency to keep a token in the index


# ============================================================
# Text cleaning
# ============================================================
CHAR_MAP = {
    "\ufb01": "fi", "\ufb02": "fl", "\ufb00": "ff",
    "\ufb03": "ffi", "\ufb04": "ffl", "\ufb05": "ft", "\ufb06": "st",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "--", "\u2026": "...",
    "\u00a0": " ", "\u2022": "*",
}

PAGE_NUM_RE = re.compile(r"^\s*\d{1,4}\s*$")


def normalize_chars(text):
    for k, v in CHAR_MAP.items():
        text = text.replace(k, v)
    return text


def detect_running_lines(pdf_path, sample=30):
    """Sample pages, find short lines that repeat -> running headers/footers."""
    counter = Counter()
    doc = fitz.open(pdf_path)
    total = doc.page_count
    step = max(1, total // sample)
    for i in range(0, total, step):
        text = doc[i].get_text("text")
        for line in text.splitlines():
            s = line.strip()
            if 3 <= len(s) <= 60 and not s.isdigit():
                counter[s] += 1
    doc.close()
    return {s for s, c in counter.items() if c >= max(3, sample // 4)}


# ============================================================
# Chapter detection
# ============================================================
CHAPTER_LINE_RE = re.compile(r"^\s*(\d{1,2}\.\d{1,2}\s+[A-Z][A-Za-z ,\-]{3,80})$")
CHAPTER_BIG_RE = re.compile(r"^\s*CHAPTER\s+(\d{1,2})\s*$", re.IGNORECASE)


# ============================================================
# Book
# ============================================================
class Book:
    """One physics book: PDF -> cleaned pages -> chunks.jsonl"""

    def __init__(self, book_id, root, meta=None):
        self.book_id = book_id
        self.root = Path(root)
        self.dir = self.root / "data" / "books" / book_id
        self.meta = meta or {}
        self._running_lines = None

    # ---- paths ----
    @property
    def pdf_path(self):     return self.dir / "source.pdf"
    @property
    def raw_dir(self):      return self.dir / "raw"
    @property
    def clean_dir(self):    return self.dir / "clean"
    @property
    def chunks_path(self):  return self.dir / "chunks" / "chunks.jsonl"

    # ---- status ----
    def is_ready(self):
        return self.chunks_path.exists() and self.chunks_path.stat().st_size > 0

    def chunk_count(self):
        if not self.is_ready():
            return 0
        with self.chunks_path.open() as f:
            return sum(1 for line in f if line.strip())

    # ---- stage 1: extract ----
    def extract(self, force=False):
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        if force:
            for f in self.raw_dir.glob("page_*.txt"):
                f.unlink()

        doc = fitz.open(self.pdf_path)
        total = doc.page_count
        done = 0
        for i in range(total):
            out = self.raw_dir / f"page_{i:05d}.txt"
            if out.exists() and out.stat().st_size > 0:
                continue
            try:
                text = doc[i].get_text("text")
            except Exception:
                text = ""
            out.write_text(text, encoding="utf-8")
            done += 1
        doc.close()
        return done

    # ---- stage 2: clean ----
    def _get_running_lines(self):
        if self._running_lines is None:
            self._running_lines = detect_running_lines(self.pdf_path)
        return self._running_lines

    def clean(self, force=False):
        self.clean_dir.mkdir(parents=True, exist_ok=True)
        if force:
            for f in self.clean_dir.glob("page_*.txt"):
                f.unlink()

        running = self._get_running_lines()
        done = 0
        for raw_file in sorted(self.raw_dir.glob("page_*.txt")):
            out = self.clean_dir / raw_file.name
            if out.exists() and out.stat().st_size > 0:
                continue
            raw = raw_file.read_text(encoding="utf-8", errors="ignore")
            cleaned = self._clean_page(raw, running)
            out.write_text(cleaned, encoding="utf-8")
            done += 1
        return done

    @staticmethod
    def _clean_page(text, running):
        text = normalize_chars(text)
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # join hyphenation
        lines = []
        for line in text.splitlines():
            s = line.strip()
            if not s:
                lines.append("")
                continue
            if PAGE_NUM_RE.match(s):
                continue
            if s in running:
                continue
            lines.append(line.rstrip())
        text = "\n".join(lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        return text.strip()

    # ---- stage 3: chunk ----
    def chunk(self, force=False):
        self.chunks_path.parent.mkdir(parents=True, exist_ok=True)
        if force and self.chunks_path.exists():
            self.chunks_path.unlink()

        clean_files = sorted(self.clean_dir.glob("page_*.txt"))
        current_chapter = "Front Matter"
        idx = 0

        with self.chunks_path.open("w", encoding="utf-8") as fout:
            for f in clean_files:
                try:
                    page_num = int(f.stem.split("_")[1])
                except (IndexError, ValueError):
                    continue
                text = f.read_text(encoding="utf-8", errors="ignore")
                if not text.strip():
                    continue

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

                for chunk_text in self._chunk_page(text):
                    wc = len(chunk_text.split())
                    if wc < MIN_CHUNK_WORDS:
                        continue
                    rec = {
                        "id": f"{self.book_id}:chunk_{idx:06d}",
                        "book_id": self.book_id,
                        "text": chunk_text,
                        "page_start": page_num,
                        "page_end": page_num,
                        "chapter": current_chapter,
                        "keywords": self._keywords(chunk_text),
                        "word_count": wc,
                    }
                    fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    idx += 1
        return idx

    @staticmethod
    def _chunk_page(text):
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        buf, words = [], 0
        for p in paragraphs:
            pw = len(p.split())
            if words + pw > MAX_WORDS and buf:
                yield " ".join(buf).strip()
                tail = " ".join(buf).split()[-OVERLAP_WORDS:]
                buf = [" ".join(tail)] if tail else []
                words = len(tail)
            buf.append(p)
            words += pw
            if words >= TARGET_WORDS:
                yield " ".join(buf).strip()
                tail = " ".join(buf).split()[-OVERLAP_WORDS:]
                buf = [" ".join(tail)] if tail else []
                words = len(tail)
        if buf:
            joined = " ".join(buf).strip()
            if len(joined.split()) >= MIN_CHUNK_WORDS:
                yield joined

    @staticmethod
    def _keywords(text, top=10):
        STOP = set("""a an and or but if then of in on at to for with by from as is
        are was were be been being this that these those it its into over under such
        than so not no nor can could may might will would shall should do does did
        have has had there their they them he she we you your our i me my mine us
        also each other any all more most some few both many much very only just""".split())
        words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", text.lower())
        words = [w for w in words if w not in STOP]
        return [w for w, _ in Counter(words).most_common(top)]

    # ---- orchestrator ----
    def ingest(self, force=False, progress=None):
        if self.is_ready() and not force:
            return {"status": "skipped", "chunks": self.chunk_count()}

        if progress: progress("extract")
        n_extract = self.extract(force=force)

        if progress: progress("clean")
        n_clean = self.clean(force=force)

        if progress: progress("chunk")
        n_chunks = self.chunk(force=force)

        return {
            "status": "completed",
            "pages_extracted": n_extract,
            "pages_cleaned": n_clean,
            "chunks": n_chunks,
        }


# ============================================================
# Library
# ============================================================
class Library:
    """All books + merged chunks + TF-IDF index + diverse retrieval."""

    def __init__(self, root):
        self.root = Path(root)
        self.books_dir = self.root / "data" / "books"
        self.index_dir = self.root / "data" / "index"
        self.catalog_path = self.root / "data" / "books.json"

        self.books = {}          # book_id -> Book
        self.chunks = {}         # chunk_id -> dict
        self.idf = {}            # token -> float
        self.docs = []           # [{id, len, tf, book_id}]
        self._loaded = False

        self.index_dir.mkdir(parents=True, exist_ok=True)
        self._load_catalog()

    # ---- catalog ----
    def _load_catalog(self):
        if self.catalog_path.exists():
            data = json.loads(self.catalog_path.read_text())
            for book_id, meta in data.items():
                self.books[book_id] = Book(book_id, self.root, meta)

    def _save_catalog(self):
        data = {bid: b.meta for bid, b in self.books.items()}
        self.catalog_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    # ---- book management ----
    def add_book(self, book_id, meta, pdf_src=None):
        book = Book(book_id, self.root, meta)
        book.dir.mkdir(parents=True, exist_ok=True)

        if pdf_src is not None:
            src = Path(pdf_src)
            if not src.exists():
                raise FileNotFoundError(f"PDF not found: {src}")
            if not book.pdf_path.exists() or src.stat().st_mtime > book.pdf_path.stat().st_mtime:
                shutil.copy2(src, book.pdf_path)

        self.books[book_id] = book
        self._save_catalog()
        return book

    def remove_book(self, book_id, delete_files=False):
        if book_id not in self.books:
            return False
        book = self.books.pop(book_id)
        if delete_files and book.dir.exists():
            shutil.rmtree(book.dir)
        self._save_catalog()
        return True

    # ---- merged chunks ----
    def rebuild_merged_chunks(self):
        out = self.index_dir / "chunks_all.jsonl"
        tmp = out.with_suffix(".jsonl.tmp")
        total = 0
        with tmp.open("w", encoding="utf-8") as fout:
            for book in self.books.values():
                if not book.is_ready():
                    continue
                with book.chunks_path.open(encoding="utf-8") as fin:
                    for line in fin:
                        if line.strip():
                            fout.write(line)
                            total += 1
        tmp.rename(out)  # atomic
        return total

    # ---- index ----
    def rebuild_index(self, min_df=MIN_DF):
        chunks_file = self.index_dir / "chunks_all.jsonl"
        if not chunks_file.exists():
            raise FileNotFoundError("Run rebuild_merged_chunks() first")

        TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]{1,}")
        STOP = set("""a an and or but if then of in on at to for with by from as is
        are was were be been being this that these those it its into over under such
        than so not no nor can could may might will would shall should do does did
        have has had there their they them he she we you your our i me my mine us""".split())

        docs = []
        df = Counter()
        with chunks_file.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                toks = [t for t in TOKEN_RE.findall(rec["text"].lower()) if t not in STOP]
                tf = Counter(toks)
                docs.append({"id": rec["id"], "len": len(toks), "tf": dict(tf),
                             "book_id": rec["book_id"]})
                for t in tf:
                    df[t] += 1

        N = len(docs)
        idf = {t: round(math.log((N + 1) / (c + 1)) + 1.0, 5)
               for t, c in df.items() if c >= min_df}

        for d in docs:
            d["tf"] = {t: c for t, c in d["tf"].items() if t in idf}

        index_data = {"N": N, "idf": idf, "docs": docs}
        out = self.index_dir / "index_all.json"
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(index_data, ensure_ascii=False, separators=(",", ":")))
        tmp.rename(out)

        return {"N": N, "vocab": len(idf), "bytes": out.stat().st_size}

    # ---- loading (for app.py) ----
    def load_index(self):
        chunks_file = self.index_dir / "chunks_all.jsonl"
        index_file = self.index_dir / "index_all.json"

        self.chunks = {}
        with chunks_file.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    self.chunks[rec["id"]] = rec

        data = json.loads(index_file.read_text(encoding="utf-8"))
        self.idf = data["idf"]
        self.docs = data["docs"]
        self._loaded = True
        return len(self.chunks), len(self.idf)

    # ---- retrieval (diversity-aware) ----
    def search(self, query_tokens, top_k=6, book_ids=None, max_per_book=3,
               ensure_min_books=2, max_per_chapter=2):
        """
        Retrieval with diversity constraints.

        - top_k:            number of chunks to return
        - book_ids:         optional list of book_ids to restrict to
        - max_per_book:     at most this many chunks from any one book
        - ensure_min_books: try to include chunks from at least this many books
        - max_per_chapter:  at most this many chunks from any one chapter/topic
        """
        if not self._loaded:
            raise RuntimeError("call load_index() first")

        qset = set(query_tokens)

        # 1. Score every doc
        scored = []
        for d in self.docs:
            if book_ids and d.get("book_id") not in book_ids:
                continue
            tf = d["tf"]
            s = 0.0
            matched = 0
            for t in qset:
                c = tf.get(t, 0)
                if c:
                    s += (1.0 + math.log(c)) * self.idf.get(t, 1.0)
                    matched += 1
            if matched:
                s *= (1.0 + 0.1 * matched)
                scored.append((s, d["id"], d.get("book_id", "")))

        scored.sort(reverse=True)

        # 2. Greedy pick with diversity constraints
        results = []
        book_counts = Counter()
        chapter_counts = Counter()

        for s, cid, book_id in scored:
            if len(results) >= top_k:
                break
            if book_counts[book_id] >= max_per_book:
                continue

            rec = self.chunks.get(cid)
            if not rec:
                continue
            chapter_key = rec.get("chapter") or f"p{rec.get('page_start',0)//10*10}"
            if chapter_counts[chapter_key] >= max_per_chapter:
                continue

            results.append((s, cid))
            book_counts[book_id] += 1
            chapter_counts[chapter_key] += 1

        # 3. Backfill if we didn't hit ensure_min_books
        if ensure_min_books > 1:
            present_books = {self.chunks[c]["book_id"] for _, c in results}
            if len(present_books) < ensure_min_books:
                for s, cid, book_id in scored:
                    if len(results) >= top_k:
                        break
                    if any(r[1] == cid for r in results):
                        continue
                    if book_counts[book_id] >= max_per_book:
                        continue
                    results.append((s, cid))
                    book_counts[book_id] += 1

        return results

    # ---- stats ----
    def stats(self):
        return {
            "books": len(self.books),
            "ready_books": sum(1 for b in self.books.values() if b.is_ready()),
            "total_chunks": sum(b.chunk_count() for b in self.books.values()),
        }
