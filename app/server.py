import os
from typing import List, Dict, Any

from fastapi import FastAPI
from fastapi import Query
from pydantic import BaseModel
import chromadb
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

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


class AskBody(BaseModel):
    question: str
    top_k: int | None = None


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

    prompt = f"""You are a helpful FAQ assistant.
     Answer the user's question **only** using the CONTEXT.
If the answer is not in the context, say you don't have enough information.

USER QUESTION:
{question}

CONTEXT (numbered passages):
{context_block}

Instructions:
- Be concise but complete.
- If you use facts from a passage, cite like [1], [2] etc.
- If multiple sources support the same point, cite both.
- If you cannot find the answer, say so.

Now draft the best possible answer with citations.
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


@app.post("/ask")
def ask(body: AskBody):
    question = body.question.strip()
    top_k = body.top_k or TOP_K_DEFAULT
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

    return {
        "question": question,
        "answer": answer,
        "sources": sources,
        "note": note,
    }
