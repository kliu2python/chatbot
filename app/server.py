import os
import uuid
from pathlib import Path
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import chromadb
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

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
    except Exception as e:
        openai_client = None
        USE_LLM = False

DB_DIR = os.getenv("DB_DIR", "./chroma_db")
COLLECTION = os.getenv("COLLECTION", "faq")
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
TOP_K_DEFAULT = int(os.getenv("TOP_K", "5"))

# Init
client = chromadb.PersistentClient(path=DB_DIR)
collection = client.get_or_create_collection(name=COLLECTION,
                                             metadata={"hnsw:space": "cosine"})
embedder = SentenceTransformer(EMBED_MODEL)

app = FastAPI(title="Chroma FAQ Chatbot", version="1.0.0")

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Chat UI not found")
    return FileResponse(index_path)


class AskBody(BaseModel):
    question: str
    top_k: int | None = None
    session_id: str | None = None


def embed(texts: List[str]) -> List[List[float]]:
    return embedder.encode(texts, show_progress_bar=False,
                           normalize_embeddings=True).tolist()


def build_prompt(question: str, contexts: List[Dict[str, Any]]) -> str:
    numbered = []
    for i, c in enumerate(contexts, 1):
        src = c["metadata"].get("source", "unknown")
        snippet = c["document"].strip().replace("\n", " ")
        if len(snippet) > 500:
            snippet = snippet[:500] + " ..."
        numbered.append(f"[{i}] Source: {src}\n{snippet}")
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
    except Exception as e:
        return f""  # fall back to retrieval-only


@app.get("/health")
def health():
    return {"status": "ok", "db_dir": DB_DIR, "collection": COLLECTION}


session_history: Dict[str, List[Dict[str, Any]]] = {}


@app.post("/ask")
def ask(body: AskBody):
    question = body.question.strip()
    top_k = body.top_k or TOP_K_DEFAULT
    session_id = body.session_id or str(uuid.uuid4())

    history = session_history.setdefault(session_id, [])

    if not question:
        return {
            "question": question,
            "answer": "",
            "sources": [],
            "note": "",
            "session_id": session_id,
            "history": history,
        }

    q_emb = embed([question])[0]

    res = collection.query(
        query_embeddings=[q_emb],
        n_results=top_k,
        include=["documents", "metadatas", "distances", "embeddings"],
    )

    # Normalize result structure for downstream usage
    results = []
    for doc, meta, dist in zip(res.get("documents", [[]])[0],
                               res.get("metadatas", [[]])[0],
                               res.get("distances", [[]])[0]):
        results.append({"document": doc, "metadata": meta, "distance": dist})

    # Build prompt and call LLM if available
    answer = ""
    if results:
        prompt = build_prompt(question, results)
        print(f"ask llm with question {prompt}")
        answer = call_llm(prompt)

    # If no LLM, return retrieved chunks with a helpful note
    if not answer:
        note = ("LLM not configured; returning retrieved passages only. Set "
                "OPENAI_API_KEY (and optionally OPENAI_BASE_URL, OPENAI_MODEL)")
    else:
        note = ""

    # Build simple source list
    sources = []
    for i, r in enumerate(results, 1):
        sources.append({
            "id": i,
            "source": r["metadata"].get("source"),
            "chunk": r["metadata"].get("chunk"),
            "distance": r["distance"],
            "preview": (r["document"][:240] + "...") if len(r["document"]) > 240 else r["document"]
        })

    history_entry = {
        "question": question,
        "answer": answer,
        "note": note,
        "sources": sources,
    }
    history.append(history_entry)

    return {
        "question": question,
        "answer": answer,
        "sources": sources,
        "note": note,
        "session_id": session_id,
        "history": history,
    }
