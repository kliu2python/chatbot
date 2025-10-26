# Project FAQ

## What is this project?
This project is a minimal Retrieval-Augmented Generation (RAG) starter using Chroma as the vector database and FastAPI as the serving layer.

## How does retrieval work?
Your documents are chunked (with overlap), embedded locally with Sentence-Transformers, and stored in a persistent Chroma collection. At query time we embed the question, run a vector search, and feed the top chunks to an LLM to draft an answer.

## Where are embeddings stored?
Embeddings and metadata are persisted on disk via Chroma (see the `--db_dir` argument), so you can restart the server without reingesting.

## Can I use OpenAI or a LiteLLM proxy?
Yes. Set `OPENAI_API_KEY`, optionally `OPENAI_BASE_URL`, and `OPENAI_MODEL`. If unset, the API returns retrieved passages only so you can test retrieval without an LLM.
