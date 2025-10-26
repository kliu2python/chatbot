# Docker Setup for Chatbot

This setup includes all the necessary components to run the chatbot backend with Docker.

## Services

1. **chatbot-backend** - The main FastAPI server that serves the `/ask` endpoint and static files
2. **ingest** - A one-time service that processes documents and creates embeddings

## Quick Start

1. Build and start the services:
```bash
docker-compose up --build
```

2. Access the chatbot at http://localhost:8080

## Configuration

The docker-compose.yml file exposes the following configuration through environment variables:

- `DB_DIR` - Directory for Chroma database persistence
- `COLLECTION` - Name of the Chroma collection
- `EMBED_MODEL` - Sentence transformer model for embeddings
- `RERANK_MODEL` - Cross-encoder model for reranking
- `TOP_K` - Number of results to return
- `ENABLE_WEB_SEARCH` - Enable/disable web search
- `WEB_SEARCH_K` - Number of web search results
- `DATA_DIR` - Directory containing source documents
- `WATCH_DOCS` - Enable/disable document watching
- `REINGEST_DEBOUNCE` - Delay before reingesting changed documents

## Volumes

Two volumes are mounted:
- `./data` - Contains source documents for the chatbot
- `./chroma_db` - Persists Chroma database between container restarts

## Usage

To rebuild the embeddings when documents change:
```bash
docker-compose up ingest
```

To start only the backend service:
```bash
docker-compose up chatbot-backend
```

The backend service will automatically restart when code changes are detected due to the `--reload` flag.