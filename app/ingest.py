import argparse
import hashlib
import os
import re
from pathlib import Path
from typing import Iterable, List, Tuple, Dict

import chromadb
from sentence_transformers import SentenceTransformer
from bs4 import BeautifulSoup
from pypdf import PdfReader

# -------- Config --------
CHUNK_CHARS = 1000     # ~characters per chunk
CHUNK_OVERLAP = 150    # overlap between chunks


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def read_md_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def read_html_file(path: Path) -> str:
    html = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    # Keep visible text
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def read_pdf_file(path: Path) -> str:
    reader = PdfReader(str(path))
    texts = []
    for page in reader.pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            pass
    return "\n".join(texts).strip()


def chunk_text(text: str, chunk_size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> List[str]:
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = max(0, end - overlap)
    return chunks


def file_to_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in [".txt"]:
        return read_text_file(path)
    if ext in [".md", ".markdown"]:
        return read_md_file(path)
    if ext in [".html", ".htm"]:
        return read_html_file(path)
    if ext in [".pdf"]:
        return read_pdf_file(path)
    # Fallback: try utf-8 read
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def iter_docs(data_dir: Path) -> Iterable[Tuple[str, Dict]]:
    """Yield (text, metadata) for each chunk from all files under data_dir."""
    for path in sorted(data_dir.rglob("*")):
        if not path.is_file():
            continue
        text = file_to_text(path)
        if not text:
            continue
        chunks = chunk_text(text)
        last_modified = path.stat().st_mtime
        for i, chunk in enumerate(chunks):
            meta = {
                "source": str(path.resolve()),
                "chunk": i,
                "total_chunks": len(chunks),
                "filename": path.name,
                "last_modified": last_modified,
                "section_label": f"Section {i + 1} of {len(chunks)}",
                "url": str(path.resolve()),
            }
            yield chunk, meta


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def upsert_chunks(
    client: chromadb.ClientAPI,
    collection_name: str,
    docs: Iterable[Tuple[str, Dict]],
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    batch_size: int = 128,
    reset: bool = False,
):
    collection = client.get_or_create_collection(name=collection_name, metadata={"hnsw:space": "cosine"})
    if reset:
        collection.delete()
    embedder = SentenceTransformer(model_name)

    batch_texts, batch_metas, batch_ids = [], [], []

    def flush():
        nonlocal batch_texts, batch_metas, batch_ids
        if not batch_texts:
            return
        embeddings = embedder.encode(batch_texts, show_progress_bar=False, normalize_embeddings=True).tolist()
        collection.upsert(
            ids=batch_ids,
            embeddings=embeddings,
            documents=batch_texts,
            metadatas=batch_metas,
        )
        batch_texts, batch_metas, batch_ids = [], [], []

    for text, meta in docs:
        # Deterministic ID by source + chunk index ensures updates overwrite
        content_id = sha1(meta["source"] + "::" + str(meta["chunk"]))
        batch_texts.append(text)
        batch_metas.append(meta)
        batch_ids.append(content_id)
        if len(batch_texts) >= batch_size:
            flush()

    flush()
    return collection


def main():
    parser = argparse.ArgumentParser(description="Ingest docs into a Chroma collection.")
    parser.add_argument("--data_dir", type=str, default="./data", help="Directory containing your documents")
    parser.add_argument("--db_dir", type=str, default="./chroma_db", help="Directory for Chroma persistence")
    parser.add_argument("--collection", type=str, default="faq", help="Collection name")
    parser.add_argument("--model", type=str, default="sentence-transformers/all-MiniLM-L6-v2", help="Embedding model")
    parser.add_argument("--reset", action="store_true", help="Reset the collection before ingesting")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        raise SystemExit(f"Data directory not found: {data_dir}")

    client = chromadb.PersistentClient(path=args.db_dir)
    docs = iter_docs(data_dir)

    upsert_chunks(client, args.collection, docs, model_name=args.model, reset=args.reset)
    print(f"Ingest complete. DB path: {args.db_dir}, collection: {args.collection}")


if __name__ == "__main__":
    main()
