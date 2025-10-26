import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

import chromadb
from dotenv import load_dotenv
from enum import Enum
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator
from langchain_community.document_loaders import (
    PyPDFLoader, DirectoryLoader, TextLoader, BSHTMLLoader
)

# SSL support
import ssl

# Import task manager for queue handling
from app.common.task_manager import queue_chat_request, get_task_status, TaskStatus
from app.common.knowledge_base import (
    list_cards,
    get_card,
    add_review,
)

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.server")

DB_DIR = os.getenv("DB_DIR", "./chroma_db")
COLLECTION = os.getenv("COLLECTION", "faq")
TOP_K_DEFAULT = int(os.getenv("TOP_K", "5"))
ENABLE_WEB_SEARCH = os.getenv("ENABLE_WEB_SEARCH", "true").lower() == "true"

app = FastAPI(title="Chroma FAQ Chatbot", version="1.1.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

ADMIN_REVIEW_TOKEN = os.getenv("ADMIN_REVIEW_TOKEN", "").strip()


class KnowledgeCardModel(BaseModel):
    id: str
    canonicalQuestion: str | None = None
    shortAnswer: str | None = None
    stepByStep: list[str] | str | None = None
    links: list[str] | None = None
    constraints: list[str] | None = None
    caveats: list[str] | None = None
    metrics: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    status: str
    reviews: list[dict[str, Any]] | None = None

    class Config:
        arbitrary_types_allowed = True
        extra = "allow"


class ReviewDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"


class KnowledgeCardReview(BaseModel):
    reviewer: str
    rating: int
    decision: ReviewDecision
    notes: str | None = None

    @validator("reviewer")
    def validate_reviewer(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("Reviewer is required")
        return value

    @validator("rating")
    def validate_rating(cls, value: int) -> int:
        if not 1 <= value <= 5:
            raise ValueError("Rating must be between 1 and 5")
        return value


def require_admin(request: Request):
    if not ADMIN_REVIEW_TOKEN:
        return
    token = request.headers.get("X-Admin-Token") or request.query_params.get("admin_token")
    if token != ADMIN_REVIEW_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing admin token")


class AskBody(BaseModel):
    question: str
    top_k: int | None = None
    session_id: str | None = None
    use_web_search: bool | None = None


class TaskResponse(BaseModel):
    task_id: str
    status: str = "queued"


@app.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Chat UI not found")
    return FileResponse(index_path)


@app.get("/embed", include_in_schema=False)
def serve_embed() -> FileResponse:
    embed_path = STATIC_DIR / "embed.html"
    if not embed_path.exists():
        raise HTTPException(status_code=404, detail="Embed UI not found")
    return FileResponse(embed_path)


@app.get("/admin", include_in_schema=False)
def serve_admin_portal() -> FileResponse:
    review_path = STATIC_DIR / "review.html"
    if not review_path.exists():
        raise HTTPException(status_code=404, detail="Admin review UI not found")
    return FileResponse(review_path)


@app.get("/health")
def health():
    return {"status": "ok", "db_dir": DB_DIR, "collection": COLLECTION}


@app.get("/knowledge-cards", response_model=List[KnowledgeCardModel])
def fetch_knowledge_cards(
    status: Optional[str] = None,
    _: None = Depends(require_admin),
):
    cards = list_cards(status)
    return [KnowledgeCardModel(**card) for card in cards]


@app.get("/knowledge-cards/{card_id}", response_model=KnowledgeCardModel)
def fetch_knowledge_card(card_id: str, _: None = Depends(require_admin)):
    card = get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    return KnowledgeCardModel(**card)


@app.post("/knowledge-cards/{card_id}/review", response_model=KnowledgeCardModel)
def submit_knowledge_card_review(
    card_id: str,
    review: KnowledgeCardReview,
    _: None = Depends(require_admin),
):
    card = get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Knowledge card not found")

    review_payload = {
        "reviewer": review.reviewer,
        "rating": review.rating,
        "decision": review.decision.value,
        "notes": review.notes,
    }
    updated = add_review(card_id, review_payload, new_status=review.decision.value)
    if not updated:
        raise HTTPException(status_code=500, detail="Unable to update knowledge card")
    return KnowledgeCardModel(**updated)


# -------- Task Management Endpoints --------
@app.post("/ask", response_model=TaskResponse)
def queue_ask_request(body: AskBody):
    """
    Queue a chat request for asynchronous processing.

    Returns:
        TaskResponse: Contains the task ID for polling the result.
    """
    question = body.question.strip()
    top_k = body.top_k or TOP_K_DEFAULT
    session_id = body.session_id or str(uuid.uuid4())
    use_web_search = body.use_web_search if body.use_web_search is not None else ENABLE_WEB_SEARCH

    if not question:
        # For empty questions, we still queue a task to maintain consistency
        task_id = queue_chat_request("", session_id, top_k, use_web_search)
        return TaskResponse(task_id=task_id, status=TaskStatus.QUEUED)

    # Queue the chat request
    task_id = queue_chat_request(question, session_id, top_k, use_web_search)
    return TaskResponse(task_id=task_id, status=TaskStatus.QUEUED)


@app.get("/tasks/{task_id}")
def get_task_result(task_id: str):
    """
    Get the result of a queued task.

    Args:
        task_id: The task identifier

    Returns:
        The task result if completed, or status information if still processing.
    """
    task_status = get_task_status(task_id)

    if not task_status:
        raise HTTPException(status_code=404, detail="Task not found")

    return task_status


# -------- Document watch / auto re-ingest --------
# (Keeping the existing document watching functionality as it's not part of the request processing)
