import argparse
import hashlib
import os
import re
import time
from itertools import chain
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Tuple

import chromadb
from sentence_transformers import SentenceTransformer
from bs4 import BeautifulSoup, NavigableString, Tag
import httpx
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


def fetch_html(url: str, timeout: float = 30.0) -> str:
    """Fetch HTML content from a URL with sensible defaults."""
    with httpx.Client(follow_redirects=True, timeout=timeout, verify=False) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


HEADING_LEVELS = {f"h{i}": i for i in range(1, 7)}


def _collect_answer_text(question_tag: Tag) -> str:
    """Collect text that belongs to a question heading until the next heading."""
    parts: List[str] = []
    for sibling in question_tag.next_siblings:
        if isinstance(sibling, Tag):
            level = HEADING_LEVELS.get(sibling.name.lower())
            if level and level <= HEADING_LEVELS.get(question_tag.name.lower(), 7):
                break
            text = sibling.get_text("\n", strip=True)
            if text:
                parts.append(text)
        elif isinstance(sibling, NavigableString):
            text = str(sibling).strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts).strip()


def iter_fortinet_faq(url: str) -> Iterator[Tuple[str, Dict]]:
    """Yield chunks derived from the Fortinet FAQ page."""
    try:
        html = fetch_html(url)
    except Exception as exc:  # pragma: no cover - network may fail in some environments
        print(f"Failed to fetch Fortinet FAQ page ({url}): {exc}")
        return

    soup = BeautifulSoup(html, "html.parser")
    headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
    last_modified = time.time()
    for heading in headings:
        question = heading.get_text(strip=True)
        if not question or not question.endswith("?"):
            continue

        answer = _collect_answer_text(heading)
        if not answer:
            continue

        anchor = heading.get("id")
        source_url = f"{url}#{anchor}" if anchor else url
        full_text = f"{question}\n\n{answer}"
        chunks = chunk_text(full_text)
        total_chunks = len(chunks)
        for idx, chunk in enumerate(chunks):
            section_label = question
            if total_chunks > 1:
                section_label = f"{question} (Part {idx + 1} of {total_chunks})"
            meta = {
                "source": source_url,
                "chunk": idx,
                "total_chunks": total_chunks,
                "filename": "fortinet_faqs",
                "last_modified": last_modified,
                "section_label": section_label,
                "url": source_url,
                "title": "FortiIdentity Cloud FAQs",
                "question": question,
                "source_type": "fortinet_faq",
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
    if reset:
        try:
            client.delete_collection(name=collection_name)
        except Exception:
            pass
    collection = client.get_or_create_collection(name=collection_name, metadata={"hnsw:space": "cosine"})
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
    parser.add_argument(
        "--fortinet_faq_url",
        type=str,
        default="https://docs.fortinet.com/document/fortiidentity-cloud/latest/admin-guide/766608/faqs",
        help="Fetch and embed Fortinet FAQs from the given URL.",
    )
    parser.add_argument(
        "--skip_fortinet_faq",
        action="store_true",
        help="Skip fetching the Fortinet FAQ page during ingestion.",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Warning: Data directory not found: {data_dir}")

    client = chromadb.PersistentClient(path=args.db_dir)
    doc_iters: List[Iterable[Tuple[str, Dict]]] = []
    if data_dir.exists():
        doc_iters.append(iter_docs(data_dir))
    if not args.skip_fortinet_faq and args.fortinet_faq_url:
        doc_iters.append(iter_fortinet_faq(args.fortinet_faq_url))

    if not doc_iters:
        raise SystemExit("No documents available for ingestion.")

    docs = chain.from_iterable(doc_iters)

    upsert_chunks(client, args.collection, docs, model_name=args.model, reset=args.reset)
    print(f"Ingest complete. DB path: {args.db_dir}, collection: {args.collection}")


if __name__ == "__main__":
    main()
