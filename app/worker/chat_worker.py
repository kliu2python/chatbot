"""
Worker module for processing chat requests from the queue.
"""
import os
import logging
from typing import Dict, Any, List
from pathlib import Path
import chromadb
from sentence_transformers import CrossEncoder, SentenceTransformer
from langchain_community.tools import DuckDuckGoSearchResults
from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional
import uuid

# Import shared resources and functions from the common core
from app.common.core import (
    embed, build_prompt, call_llm, assign_citations,
    chroma_retrieve_node, rerank_node, web_search_node, combine_contexts_node,
    build_retrieval_graph, RetrievalState
)

# Configuration
DB_DIR = os.getenv("DB_DIR", "./chroma_db")
COLLECTION = os.getenv("COLLECTION", "faq")
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
RERANK_MODEL = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-12-v2")
TOP_K_DEFAULT = int(os.getenv("TOP_K", "5"))
ENABLE_WEB_SEARCH = os.getenv("ENABLE_WEB_SEARCH", "true").lower() == "true"
WEB_SEARCH_K = int(os.getenv("WEB_SEARCH_K", "3"))

# Redis configuration
REDIS_HOST = os.getenv("REDIS_HOST", "10.160.13.16")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# Initialize shared resources
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
except Exception as exc:
    logging.warning("Unable to initialize DuckDuckGo search tool: %s", exc)
    duckduckgo_tool = None

# Build retrieval graph
retrieval_graph = build_retrieval_graph()


def process_chat_request(task_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a chat request from the queue.

    Args:
        task_data: Dictionary containing task information

    Returns:
        Dictionary with the chat response
    """
    try:
        question = task_data.get("question", "").strip()
        session_id = task_data.get("session_id", str(uuid.uuid4()))
        top_k = task_data.get("top_k", TOP_K_DEFAULT)
        use_web_search = task_data.get("use_web_search", ENABLE_WEB_SEARCH)

        if not question:
            return {
                "question": question,
                "answer": "",
                "sources": [],
                "citations": [],
                "note": "",
                "session_id": session_id,
                "history": [],
            }

        # Execute retrieval graph
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
                "Heads-up: I don't have a language model connected right now, so I'm "
                "sharing the most relevant passages I could find. If you set OPENAI_API_KEY "
                "(and optionally OPENAI_BASE_URL, OPENAI_MODEL), I can draft full "
                "responses for you."
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

        return response_payload

    except Exception as e:
        logging.error("Error processing chat request: %s", str(e))
        return {
            "error": str(e),
            "task_id": task_data.get("task_id"),
        }


if __name__ == "__main__":
    # This can be used to run the worker directly if needed
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.info("Chat worker initialized and ready to process requests")