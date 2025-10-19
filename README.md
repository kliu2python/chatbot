# Chroma FAQ Chatbot (RAG) – Minimal Starter

This is a **tiny, production-friendly starter** for building an FAQ chatbot using:
- **Chroma** as a local vector database (persistent on disk)
- **Sentence-Transformers** for local embeddings (no external API required)
- **FastAPI** for a simple `/ask` endpoint
- Optional **OpenAI-compatible** LLM (works with OpenAI or a LiteLLM proxy via `OPENAI_BASE_URL`)
- **Cross-encoder reranking** (`cross-encoder/ms-marco-MiniLM-L-12-v2` by default) for high-quality context ordering
- **LangGraph + LangChain** orchestration that blends Chroma retrieval with optional DuckDuckGo web search results
- **Structured citations** that surface titles, sections, and URLs directly in the chat widget
- **Automatic document watches** (via `watchdog`) to reingest updated content without restarting the API

## Quickstart

```bash
# 1) Create venv + install deps
python -m venv .venv && source .venv/bin/activate  # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt

# 2) Put your docs into ./data (pdf, txt, md, html supported in this demo)
#    A sample doc already exists.

# 3) Build the vector DB (pass --reset to rebuild from scratch)
python -m app.ingest --data_dir ./data --db_dir ./chroma_db --collection faq --reset

# 4) Run the API
# Optional env (works with OpenAI or LiteLLM):
#   export OPENAI_API_KEY=sk-...
#   export OPENAI_BASE_URL=https://your-litellm-or-openai-compatible-endpoint/v1/
#   export OPENAI_MODEL=gpt-4o-mini
uvicorn app.server:app --host 0.0.0.0 --port 8000

# 5) Ask questions
curl -s http://localhost:8000/ask -X POST -H "Content-Type: application/json" -d '{"question": "What is this project?"}' | jq
```

If you don't set an LLM key, the server will return **retrieved passages** only so you can still test retrieval. Citations remain available for each chunk/web result even in retrieval-only mode.

## Docker usage

You can build and run the chatbot entirely from a container. The included `Dockerfile` and `docker-compose.yml` assume that your documentation lives in `./data` on the host and persists the vector store in a named volume so it survives restarts.

```bash
# Build the image
docker compose build

# (Optional) Ingest docs into the Chroma DB
docker compose run --rm \
  chatbot \
  python -m app.ingest --data_dir /data/docs --db_dir /data/chroma_db --collection faq --reset

# Start the API
docker compose up

# Query it
curl -s http://localhost:8000/ask -X POST -H "Content-Type: application/json" -d '{"question": "What is this project?"}' | jq
```

Environment variables such as `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, or `ENABLE_WEB_SEARCH` can be added to the `docker-compose.yml` file (under `environment:`) or passed via `docker compose run ... -e VAR=value` when ingesting. To rebuild embeddings after changing documentation, rerun the ingestion command above.

## Embedding the FortiIdentity Cloud support widget elsewhere

Once the FastAPI server is reachable from your FortiIdentity Cloud frontend, you can drop the floating chat experience into any page with a single script tag. The embed script injects the widget markup, loads the widget stylesheet, and wires the `/ask` endpoint with per-session history.

```html
<script
  src="https://YOUR_CHATBOT_HOST/static/embed.js"
  data-base-url="https://YOUR_CHATBOT_HOST"
  data-with-credentials="false"
  defer
></script>
```

**Options**

- `data-base-url` (recommended): explicitly points the widget to the FastAPI host that serves `/ask` and the static assets. If the script is loaded from the same origin as your API, you can omit it.
- `data-with-credentials="true"`: include cookies when calling `/ask` if your deployment relies on browser-based auth. Defaults to `false`.
- `data-session-key`: override the localStorage key used for chat sessions when embedding the widget on multiple sites.

The script waits for `DOMContentLoaded`, injects the floating launcher button, and reuses the existing FortiIdentity styling without altering the host page layout.

## Tuning knobs
- **Chunk size / overlap** in `app/ingest.py` (`CHUNK_CHARS`, `CHUNK_OVERLAP`)
- **Top-K** results in `/ask` body (`top_k`, default 5) – reranking automatically evaluates the top 20 candidates
- **Cross-encoder model** via `RERANK_MODEL`
- **Web search fan-out** with `ENABLE_WEB_SEARCH=true`/`false` and `WEB_SEARCH_K`
- **Automatic watches** toggle with `WATCH_DOCS=true`/`false` and debounce via `REINGEST_DEBOUNCE`
- **Metadata** you store with each chunk (`source`, `title`, `url`, etc.)

## Folder layout
```
chroma_faq_bot/
  app/
    ingest.py     # Build & update the Chroma collection from docs
    server.py     # FastAPI app exposing /ask
  data/
    sample_faq.md # Example content
  requirements.txt
  README.md
```

Enjoy!
