"""
Core shared functionality for both API and Worker services.
"""
import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict
from dotenv import load_dotenv

import chromadb
from sentence_transformers import CrossEncoder, SentenceTransformer
from langchain_community.tools import DuckDuckGoSearchResults
from langgraph.graph import StateGraph, END
from langchain_community.document_loaders import (
    PyPDFLoader, DirectoryLoader, TextLoader, BSHTMLLoader
)

# Load environment variables
load_dotenv()

# Configuration
DB_DIR = os.getenv("DB_DIR", "./chroma_db")
COLLECTION = os.getenv("COLLECTION", "faq")
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
RERANK_MODEL = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-12-v2")
TOP_K_DEFAULT = int(os.getenv("TOP_K", "5"))
ENABLE_WEB_SEARCH = os.getenv("ENABLE_WEB_SEARCH", "true").lower() == "true"
WEB_SEARCH_K = int(os.getenv("WEB_SEARCH_K", "3"))
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
WATCH_DOCS = os.getenv("WATCH_DOCS", "true").lower() == "true"
REINGEST_DEBOUNCE = float(os.getenv("REINGEST_DEBOUNCE", "3.0"))

# Optional LLM (OpenAI-compatible)
USE_LLM = bool(os.getenv("OPENAI_API_KEY"))
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

if USE_LLM:
    try:
        from openai import OpenAI
        from google import genai
        import httpx

        # Initialize OpenAI client with SSL verification disabled for testing
        # In production, you should properly configure SSL certificates
        openai_client = OpenAI(
            base_url=OPENAI_BASE_URL,
            api_key=os.getenv("OPENAI_API_KEY"),
            http_client=httpx.Client(verify=False)
        )
    except Exception as exc:  # pragma: no cover - network/runtime failures
        logging.warning("Failed to initialize OpenAI client: %s", exc)
        openai_client = None
        USE_LLM = False
else:
    openai_client = None

# Init shared resources
client = chromadb.PersistentClient(path=DB_DIR)
collection = client.get_or_create_collection(
    name=COLLECTION, metadata={"hnsw:space": "cosine"}
)
# Lazy-loaded global models. They are instantiated on first use so that
# startup/import of the worker does not immediately try to download large
# HuggingFace assets (which can exceed the RQ worker timeout in restricted
# environments).
embedder_lock = threading.Lock()
reranker_lock = threading.Lock()
embedder: Optional[SentenceTransformer] = None
reranker: Optional[CrossEncoder] = None


def get_embedder() -> Optional[SentenceTransformer]:
    global embedder
    if embedder is not None:
        return embedder
    with embedder_lock:
        if embedder is not None:
            return embedder
        try:
            embedder = SentenceTransformer(EMBED_MODEL)
        except Exception as exc:  # pragma: no cover - network/runtime failures
            logging.warning("Unable to load embed model '%s': %s", EMBED_MODEL, exc)
            embedder = None
        return embedder


def get_reranker() -> Optional[CrossEncoder]:
    global reranker
    if reranker is not None:
        return reranker
    with reranker_lock:
        if reranker is not None:
            return reranker
        try:
            reranker = CrossEncoder(RERANK_MODEL)
        except Exception as exc:  # pragma: no cover - network/runtime failures
            logging.warning("Unable to load rerank model '%s': %s", RERANK_MODEL, exc)
            reranker = None
        return reranker

try:
    duckduckgo_tool: Optional[DuckDuckGoSearchResults] = DuckDuckGoSearchResults(
        max_results=WEB_SEARCH_K
    )
except Exception as exc:  # pragma: no cover - optional dependency failure
    logging.warning("Unable to initialize DuckDuckGo search tool: %s", exc)
    duckduckgo_tool = None


class RetrievalState(TypedDict, total=False):
    question: str
    top_k: int
    use_web_search: bool
    retriever_results: List[Dict[str, Any]]
    reranked_results: List[Dict[str, Any]]
    web_results: List[Dict[str, Any]]
    combined_contexts: List[Dict[str, Any]]


def embed(texts: List[str]) -> List[List[float]]:
    model = get_embedder()
    if model is None:
        logging.warning("Embedding model unavailable; skipping embedding.")
        return []
    try:
        return model.encode(
            texts, show_progress_bar=False, normalize_embeddings=True
        ).tolist()
    except Exception as exc:  # pragma: no cover - model inference failure
        logging.warning("Embedding failed: %s", exc)
        return []


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

Response format requirements:
- Answer the question directly and concisely
- Structure your response using bullet points or numbered lists
- Limit your response to 3-5 key points maximum
- Focus only on the most essential information needed to address the question
- Highlight configuration prerequisites, menu paths, or feature names exactly as they appear in the context
- Cite supporting passages using [n] references that match the numbered CONTEXT
- Never invent details that are not in the context

Structure your response using numbered steps (1, 2, 3) or bullet points as appropriate:
1. Start with the direct answer to the question
2. Provide 2-4 key steps or points that directly address the question
3. Include any important prerequisites or warnings

Keep responses brief and actionable.
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
        logging.warning("LLM call failed: %s", exc)
        return ""


def chroma_retrieve_node(state: RetrievalState) -> RetrievalState:
    question = state.get("question", "").strip()
    if not question:
        return {"retriever_results": []}

    top_k = state.get("top_k") or TOP_K_DEFAULT
    candidate_k = max(20, top_k)
    embeddings = embed([question])
    if not embeddings:
        return {"retriever_results": []}

    q_emb = embeddings[0]
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
    model = get_reranker()
    if model is None:
        logging.warning("Reranker unavailable; returning retriever order.")
        top_k = state.get("top_k") or TOP_K_DEFAULT
        return {"reranked_results": results[:top_k]}

    try:
        scores = model.predict(pairs)
    except Exception as exc:  # pragma: no cover - model inference failure
        logging.warning("Reranker failed: %s", exc)
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
        logging.warning("Web search failed: %s", exc)
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