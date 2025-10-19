import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

import chromadb
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_community.tools import DuckDuckGoSearchResults
from langgraph.graph import END, StateGraph
from pydantic import BaseModel
from sentence_transformers import CrossEncoder, SentenceTransformer

try:  # Optional dependency for file watching
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # pragma: no cover - fallback when watchdog missing
    FileSystemEventHandler = None  # type: ignore
    Observer = None  # type: ignore

if FileSystemEventHandler is None:  # pragma: no cover - fallback type
    class _BaseHandler:  # type: ignore
        pass


else:  # pragma: no cover - simple alias
    _BaseHandler = FileSystemEventHandler  # type: ignore

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.server")

# Optional LLM (OpenAI-compatible)
USE_LLM = bool(os.getenv("OPENAI_API_KEY"))
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

if USE_LLM:
    try:
        from openai import OpenAI

        openai_client = OpenAI(
            base_url=OPENAI_BASE_URL, api_key=os.getenv("OPENAI_API_KEY")
        )
    except Exception as exc:  # pragma: no cover - network/runtime failures
        logger.warning("Failed to initialize OpenAI client: %s", exc)
        openai_client = None
        USE_LLM = False
else:
    openai_client = None

DB_DIR = os.getenv("DB_DIR", "./chroma_db")
COLLECTION = os.getenv("COLLECTION", "faq")
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
RERANK_MODEL = os.getenv(
    "RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-12-v2"
)
TOP_K_DEFAULT = int(os.getenv("TOP_K", "5"))
ENABLE_WEB_SEARCH = os.getenv("ENABLE_WEB_SEARCH", "true").lower() == "true"
WEB_SEARCH_K = int(os.getenv("WEB_SEARCH_K", "3"))
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
WATCH_DOCS = os.getenv("WATCH_DOCS", "true").lower() == "true"
REINGEST_DEBOUNCE = float(os.getenv("REINGEST_DEBOUNCE", "3.0"))

# Init shared resources
client = chromadb.PersistentClient(path=DB_DIR)
collection = client.get_or_create_collection(
    name=COLLECTION, metadata={"hnsw:space": "cosine"}
)
embedder = SentenceTransformer(EMBED_MODEL)
reranker = CrossEncoder(RERANK_MODEL)

try:
    duckduckgo_tool: Optional[DuckDuckGoSearchResults] = DuckDuckGoSearchResults(
        max_results=WEB_SEARCH_K
    )
except Exception as exc:  # pragma: no cover - optional dependency failure
    logger.warning("Unable to initialize DuckDuckGo search tool: %s", exc)
    duckduckgo_tool = None

app = FastAPI(title="Chroma FAQ Chatbot", version="1.1.0")

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class AskBody(BaseModel):
    question: str
    top_k: int | None = None
    session_id: str | None = None
    use_web_search: bool | None = None


class RetrievalState(TypedDict, total=False):
    question: str
    top_k: int
    use_web_search: bool
    retriever_results: List[Dict[str, Any]]
    reranked_results: List[Dict[str, Any]]
    web_results: List[Dict[str, Any]]
    combined_contexts: List[Dict[str, Any]]


def embed(texts: List[str]) -> List[List[float]]:
    return embedder.encode(
        texts, show_progress_bar=False, normalize_embeddings=True
    ).tolist()


def build_prompt(question: str, contexts: List[Dict[str, Any]]) -> str:
    numbered: List[str] = []
    for ctx in contexts:
        metadata = ctx.get("metadata", {}) or {}
        label = ctx.get("citation_label", "")
        title = (
            metadata.get("title")
            or metadata.get("filename")
            or metadata.get("source")
            or "Source"
        )
        section = metadata.get("section_label")
        url = metadata.get("url")
        descriptor_parts = [title]
        if section:
            descriptor_parts.append(section)
        if url and url not in descriptor_parts:
            descriptor_parts.append(url)
        descriptor = " – ".join([part for part in descriptor_parts if part])

        snippet = (ctx.get("document") or "").strip().replace("\n", " ")
        if len(snippet) > 500:
            snippet = snippet[:500] + " ..."
        numbered.append(f"{label} {descriptor}\n{snippet}")
    context_block = "\n\n".join(numbered)

    prompt = f"""You are Fortinet's FortiIdentity Cloud virtual support engineer.
Your audience is a network or IT administrator who manages multi-factor authentication,
directory integrations, and user lifecycle tasks for their company.

Using only the numbered CONTEXT provided, craft a professional, technically precise response.
If the necessary information is absent, state that additional FortiIdentity Cloud guidance is required.

USER QUESTION:
{question}

CONTEXT (numbered passages):
{context_block}

Response expectations:
- Provide structured guidance (bullets or short steps) tailored to FortiIdentity Cloud administrators.
- Highlight configuration prerequisites, menu paths, or feature names exactly as they appear in the context.
- Cite supporting passages using [n] references that match the numbered CONTEXT.
- Maintain a confident, service-oriented tone, and never invent details that are not in the context.

Deliver the final answer with citations.
"""
    return prompt


def call_llm(prompt: str) -> str:
    if not USE_LLM or openai_client is None:
        return ""
    try:
        resp = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:  # pragma: no cover - network/runtime failures
        logger.warning("LLM call failed: %s", exc)
        return ""


@app.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Chat UI not found")
    return FileResponse(index_path)


@app.get("/health")
def health():
    return {"status": "ok", "db_dir": DB_DIR, "collection": COLLECTION}


session_history: Dict[str, List[Dict[str, Any]]] = {}


def chroma_retrieve_node(state: RetrievalState) -> RetrievalState:
    question = state.get("question", "").strip()
    if not question:
        return {"retriever_results": []}

    top_k = state.get("top_k") or TOP_K_DEFAULT
    candidate_k = max(20, top_k)
    q_emb = embed([question])[0]
    res = collection.query(
        query_embeddings=[q_emb],
        n_results=candidate_k,
        include=["documents", "metadatas", "distances"],
    )

    results: List[Dict[str, Any]] = []
    documents = res.get("documents", [[]])[0] if res else []
    metadatas = res.get("metadatas", [[]])[0] if res else []
    distances = res.get("distances", [[]])[0] if res else []
    for doc, meta, dist in zip(documents, metadatas, distances):
        metadata = meta or {}
        metadata.setdefault("source_type", "document")
        results.append(
            {
                "document": doc,
                "metadata": metadata,
                "distance": dist,
            }
        )
    return {"retriever_results": results}


def rerank_node(state: RetrievalState) -> RetrievalState:
    results = state.get("retriever_results") or []
    question = state.get("question", "")
    if not results or not question:
        return {"reranked_results": []}

    pairs = [(question, r.get("document", "")) for r in results]
    try:
        scores = reranker.predict(pairs)
    except Exception as exc:  # pragma: no cover - model inference failure
        logger.warning("Reranker failed: %s", exc)
        scores = [0.0 for _ in pairs]

    for r, score in zip(results, scores):
        r["score"] = float(score)

    reranked = sorted(results, key=lambda item: item.get("score", 0.0), reverse=True)
    top_k = state.get("top_k") or TOP_K_DEFAULT
    return {"reranked_results": reranked[:top_k]}


def normalize_search_results(raw_results: Any) -> List[Dict[str, Any]]:
    if raw_results is None:
        return []
    if isinstance(raw_results, str):
        try:
            parsed = json.loads(raw_results)
        except json.JSONDecodeError:
            return [
                {
                    "title": "Web Search Result",
                    "snippet": raw_results,
                    "url": None,
                }
            ]
        else:
            raw_results = parsed

    if isinstance(raw_results, dict):
        raw_results = raw_results.get("results") or raw_results.get("data") or []

    normalized: List[Dict[str, Any]] = []
    for item in raw_results:
        if isinstance(item, str):
            normalized.append({"title": "Result", "snippet": item, "url": None})
            continue
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "title": item.get("title") or item.get("name") or "Result",
                "snippet": item.get("snippet")
                or item.get("body")
                or item.get("description")
                or "",
                "url": item.get("link")
                or item.get("href")
                or item.get("url")
                or item.get("source"),
            }
        )
    return normalized[:WEB_SEARCH_K]


def web_search_node(state: RetrievalState) -> RetrievalState:
    should_search = state.get("use_web_search")
    if should_search is None:
        should_search = ENABLE_WEB_SEARCH

    if not should_search or duckduckgo_tool is None:
        return {"web_results": []}

    question = state.get("question", "").strip()
    if not question:
        return {"web_results": []}

    try:
        raw_results = duckduckgo_tool.invoke(question)
    except Exception as exc:  # pragma: no cover - network/runtime failures
        logger.warning("Web search failed: %s", exc)
        return {"web_results": []}

    normalized = normalize_search_results(raw_results)
    for item in normalized:
        item.setdefault("source_type", "web")
    return {"web_results": normalized}


def combine_contexts_node(state: RetrievalState) -> RetrievalState:
    contexts: List[Dict[str, Any]] = []
    for res in state.get("reranked_results") or []:
        contexts.append(
            {
                "document": res.get("document", ""),
                "metadata": res.get("metadata", {}) or {},
                "distance": res.get("distance"),
                "score": res.get("score"),
            }
        )

    for result in state.get("web_results") or []:
        snippet = result.get("snippet") or ""
        if not snippet:
            continue
        metadata = {
            "source": result.get("url") or "web-search",
            "url": result.get("url"),
            "title": result.get("title") or result.get("url") or "Web Result",
            "section_label": result.get("snippet"),
            "source_type": "web",
        }
        contexts.append(
            {
                "document": snippet,
                "metadata": metadata,
                "score": result.get("score"),
            }
        )
    return {"combined_contexts": contexts}


def build_retrieval_graph() -> Any:
    graph = StateGraph(RetrievalState)
    graph.add_node("retrieve_chroma", chroma_retrieve_node)
    graph.add_node("rerank", rerank_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("combine", combine_contexts_node)

    graph.set_entry_point("retrieve_chroma")
    graph.add_edge("retrieve_chroma", "rerank")
    graph.add_edge("rerank", "web_search")
    graph.add_edge("web_search", "combine")
    graph.add_edge("combine", END)
    return graph.compile()


retrieval_graph = build_retrieval_graph()


def assign_citations(
    contexts: List[Dict[str, Any]]
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    prepared: List[Dict[str, Any]] = []
    citations: List[Dict[str, Any]] = []
    for idx, ctx in enumerate(contexts, 1):
        metadata = ctx.get("metadata", {}) or {}
        snippet = (ctx.get("document") or "").strip()
        one_line_snippet = " ".join(snippet.split())
        preview = (
            one_line_snippet[:240] + "..."
            if len(one_line_snippet) > 240
            else one_line_snippet
        )
        title = (
            metadata.get("title")
            or metadata.get("filename")
            or metadata.get("source")
            or "Source"
        )
        section = metadata.get("section_label")
        url = metadata.get("url") or metadata.get("source")
        citation = {
            "id": idx,
            "label": f"[{idx}]",
            "title": title,
            "url": url,
            "section": section,
            "source_type": metadata.get("source_type", "document"),
            "preview": preview,
        }
        prepared.append({**ctx, "citation_label": citation["label"], "citation_index": idx})
        citations.append(citation)
    return prepared, citations


# -------- Document watch / auto re-ingest --------
observer: Optional[Observer] = None
_reingest_timer: Optional[threading.Timer] = None
_reingest_lock = threading.Lock()


def _perform_reingest():
    global collection
    try:
        from app import ingest as ingest_module

        docs = list(ingest_module.iter_docs(DATA_DIR))
        ingest_module.upsert_chunks(
            client,
            COLLECTION,
            docs,
            model_name=EMBED_MODEL,
            reset=True,
        )
        # Refresh collection reference after reset
        collection = client.get_or_create_collection(
            name=COLLECTION, metadata={"hnsw:space": "cosine"}
        )
        logger.info("Re-ingested %s document chunks", len(docs))
    except Exception as exc:  # pragma: no cover - runtime failures
        logger.exception("Document re-ingest failed: %s", exc)
    finally:
        with _reingest_lock:
            global _reingest_timer
            _reingest_timer = None


def _schedule_reingest():
    global _reingest_timer
    if not DATA_DIR.exists():
        return
    with _reingest_lock:
        if _reingest_timer is not None:
            _reingest_timer.cancel()
        _reingest_timer = threading.Timer(REINGEST_DEBOUNCE, _perform_reingest)
        _reingest_timer.daemon = True
        _reingest_timer.start()


class DocumentChangeHandler(_BaseHandler):  # type: ignore[misc]
    def on_any_event(self, event):  # pragma: no cover - IO heavy
        if getattr(event, "is_directory", False):
            return
        _schedule_reingest()


def start_document_watcher():
    global observer
    if not WATCH_DOCS:
        return
    if Observer is None:
        logger.warning("watchdog package not available; document watch disabled.")
        return
    if observer is not None:
        return
    if not DATA_DIR.exists():
        logger.info("Data directory %s does not exist; skipping watch.", DATA_DIR)
        return

    handler = DocumentChangeHandler()
    observer = Observer()
    observer.schedule(handler, str(DATA_DIR), recursive=True)
    observer.start()
    logger.info("Watching %s for document changes", DATA_DIR)


def stop_document_watcher():
    global observer, _reingest_timer
    if observer is not None:
        observer.stop()
        observer.join(timeout=5)
        observer = None
    with _reingest_lock:
        if _reingest_timer is not None:
            _reingest_timer.cancel()
            _reingest_timer = None


@app.on_event("startup")
async def _on_startup():  # pragma: no cover - FastAPI lifecycle
    start_document_watcher()


@app.on_event("shutdown")
async def _on_shutdown():  # pragma: no cover - FastAPI lifecycle
    stop_document_watcher()


@app.post("/ask")
def ask(body: AskBody):
    question = body.question.strip()
    top_k = body.top_k or TOP_K_DEFAULT
    session_id = body.session_id or str(uuid.uuid4())
    use_web_search = body.use_web_search if body.use_web_search is not None else ENABLE_WEB_SEARCH

    history = session_history.setdefault(session_id, [])

    if not question:
        empty_response = {
            "question": question,
            "answer": "",
            "sources": [],
            "citations": [],
            "note": "",
            "session_id": session_id,
            "history": history,
        }
        return empty_response

    retrieval_state = retrieval_graph.invoke(
        {"question": question, "top_k": top_k, "use_web_search": use_web_search}
    )
    contexts = retrieval_state.get("combined_contexts") or []
    prepared_contexts, citations = assign_citations(contexts)

    answer = ""
    if prepared_contexts:
        prompt = build_prompt(question, prepared_contexts)
        answer = call_llm(prompt)

    if not answer:
        note = (
            "LLM not configured; returning retrieved passages only. Set OPENAI_API_KEY "
            "(and optionally OPENAI_BASE_URL, OPENAI_MODEL)"
        )
    else:
        note = ""

    response_payload = {
        "question": question,
        "answer": answer,
        "sources": citations,
        "citations": citations,
        "note": note,
        "session_id": session_id,
    }

    history_entry = {
        "question": question,
        "answer": answer,
        "note": note,
        "citations": citations,
        "sources": citations,
    }
    history.append(history_entry)
    response_payload["history"] = history

    # Attach retrieved previews when no LLM answer is available
    if not answer and prepared_contexts:
        response_payload["retrieved_contexts"] = prepared_contexts

    return response_payload
