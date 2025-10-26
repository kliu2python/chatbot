"""Offline learning agent pipeline for transforming support emails into knowledge cards.

This module implements the "Learning Agent" described in the product specification.
It reads historical support emails, extracts Q/A pairs with metadata, clusters near
duplicates, generates structured knowledge cards, and stores the results in both a
semantic vector store and a structured JSON/YAML catalog.

The pipeline is orchestrated with LangChain Runnable components so additional steps
can be added easily in the future (quality gates, manual approvals, etc.).
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import chromadb
import numpy as np
import yaml
from email import policy
from email.parser import BytesParser
from langchain_core.runnables import RunnableLambda
from sentence_transformers import SentenceTransformer

logger = logging.getLogger("app.learning_agent")


# ------------------------- Data structures -------------------------


@dataclass
class EmailRecord:
    """Raw email artifact used as input to the learning pipeline."""

    id: str
    subject: str
    body: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QAItem:
    """Question/Answer pair extracted from a single email."""

    question: str
    answer: str
    metadata: Dict[str, Any]
    source_email_id: str


@dataclass
class ClusteredTopic:
    """Normalized topic that merges similar Q/A examples."""

    representative: QAItem
    members: List[QAItem]
    embeddings: np.ndarray


# ------------------------- Utility functions -------------------------


EMAIL_SIGNATURE_RE = re.compile(r"\n--+\s*$", re.MULTILINE)
EMAIL_QUOTE_RE = re.compile(r"(?m)^>+.*$")
ORIGINAL_MESSAGE_RE = re.compile(r"(?is)--+\s*original message\s*--+.*$")


def load_email_dataset(path: Path) -> List[EmailRecord]:
    """Load email threads from JSON/JSONL files or raw .eml/.txt directories."""

    if not path.exists():
        raise FileNotFoundError(f"Email dataset not found: {path}")

    if path.is_dir():
        records: List[EmailRecord] = []
        for file_path in sorted(p for p in path.rglob("*") if p.is_file()):
            records.extend(_load_email_file(file_path))
        return records

    return _load_email_file(path)


def _load_email_file(path: Path) -> List[EmailRecord]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        records: List[EmailRecord] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                records.append(_payload_to_email(payload))
        return records

    if suffix == ".json":
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            payload = payload.get("emails") or payload.get("data") or []
        if not isinstance(payload, Sequence):
            raise ValueError("Email dataset must be a list or JSONL lines")
        return [_payload_to_email(item) for item in payload]

    if suffix == ".eml":
        record = _parse_email_file(path)
        return [record] if record else []

    if suffix in {".txt", ".md"}:
        body = path.read_text(encoding="utf-8")
        record = EmailRecord(
            id=str(uuid.uuid4()),
            subject=path.stem,
            body=body,
            metadata={"sourcePath": str(path)},
        )
        return [record]

    logger.debug("Skipping unsupported file type: %s", path)
    return []


def _parse_email_file(path: Path) -> Optional[EmailRecord]:
    """Parse a raw RFC822 email file into an EmailRecord."""

    with path.open("rb") as handle:
        message = BytesParser(policy=policy.default).parse(handle)

    subject = message.get("subject", "(no subject)")
    plain_parts: List[str] = []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain":
            try:
                plain_parts.append(part.get_content())
            except LookupError:
                plain_parts.append(part.get_payload(decode=True).decode("utf-8", "replace"))
        elif content_type == "text/html" and not plain_parts:
            try:
                plain_parts.append(part.get_content())
            except LookupError:
                plain_parts.append(part.get_payload(decode=True).decode("utf-8", "replace"))

    body = "\n".join(plain_parts).strip()
    metadata = {
        "from": message.get("from"),
        "to": message.get("to"),
        "date": message.get("date"),
        "sourcePath": str(path),
    }

    return EmailRecord(
        id=str(message.get("message-id") or uuid.uuid4()),
        subject=str(subject),
        body=body,
        metadata={k: v for k, v in metadata.items() if v},
    )


def _payload_to_email(payload: Dict[str, Any]) -> EmailRecord:
    identifier = str(payload.get("id") or payload.get("messageId") or uuid.uuid4())
    subject = str(payload.get("subject") or "(no subject)")
    body = str(payload.get("body") or payload.get("content") or "")
    metadata = {
        k: v
        for k, v in payload.items()
        if k not in {"id", "messageId", "subject", "body", "content"}
    }
    return EmailRecord(id=identifier, subject=subject, body=body, metadata=metadata)


def clean_email_body(body: str) -> str:
    """Strip signatures, quoted history, and collapse whitespace."""

    if not body:
        return ""
    cleaned = EMAIL_QUOTE_RE.sub("", body)
    cleaned = ORIGINAL_MESSAGE_RE.split(cleaned)[0]
    cleaned = EMAIL_SIGNATURE_RE.split(cleaned)[0]
    cleaned_lines = [line.rstrip() for line in cleaned.splitlines() if line.strip()]
    return "\n".join(cleaned_lines).strip()


def split_question_answer(subject: str, body: str) -> Tuple[str, str]:
    """Heuristic extraction of question and answer segments."""

    question_candidates: List[str] = []
    answer_lines: List[str] = []
    seen_answer = False
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not seen_answer and stripped.endswith("?"):
            question_candidates.append(stripped)
            continue
        seen_answer = True
        answer_lines.append(stripped)

    question = " ".join(question_candidates).strip()
    if not question:
        question = subject.strip()
    answer = "\n".join(answer_lines).strip()
    return question, answer


def infer_metadata(subject: str, body: str, base_metadata: Dict[str, Any]) -> Dict[str, Any]:
    metadata = dict(base_metadata)
    text = f"{subject}\n{body}".lower()

    version_match = re.search(r"v(?:ersion)?\s*(\d+(?:\.\d+)+)", text)
    if version_match:
        metadata.setdefault("productVersion", version_match.group(1))

    env_match = re.search(r"(cloud|on[- ]prem|self[- ]hosted)", text)
    if env_match:
        metadata.setdefault("environment", env_match.group(1))

    metadata.setdefault("issueType", "support_email")
    metadata.setdefault("language", "en")
    metadata.setdefault("confidence", 0.6 if body else 0.2)
    return metadata


def extract_qa_items(emails: Iterable[EmailRecord]) -> List[QAItem]:
    """Extract question/answer pairs with metadata from raw emails."""

    qa_items: List[QAItem] = []
    for email in emails:
        cleaned = clean_email_body(email.body)
        question, answer = split_question_answer(email.subject, cleaned)
        if not question or not answer:
            continue
        metadata = infer_metadata(email.subject, cleaned, email.metadata)
        qa_items.append(
            QAItem(
                question=question,
                answer=answer,
                metadata=metadata,
                source_email_id=email.id,
            )
        )
    return qa_items


def cluster_items(
    qa_items: List[QAItem],
    embedder: SentenceTransformer,
    similarity_threshold: float = 0.85,
) -> List[ClusteredTopic]:
    """Group semantically similar Q/A pairs using cosine similarity."""

    if not qa_items:
        return []

    questions = [item.question for item in qa_items]
    embeddings = embedder.encode(
        questions, show_progress_bar=False, normalize_embeddings=True
    )
    matrix = np.array(embeddings)

    used = np.zeros(len(qa_items), dtype=bool)
    clusters: List[ClusteredTopic] = []
    for idx, item in enumerate(qa_items):
        if used[idx]:
            continue
        used[idx] = True
        member_indices = [idx]
        for other_idx in range(idx + 1, len(qa_items)):
            if used[other_idx]:
                continue
            similarity = float(matrix[idx].dot(matrix[other_idx]))
            if similarity >= similarity_threshold:
                used[other_idx] = True
                member_indices.append(other_idx)
        members = [qa_items[i] for i in member_indices]
        cluster_embeddings = matrix[member_indices]
        clusters.append(
            ClusteredTopic(
                representative=item, members=members, embeddings=cluster_embeddings
            )
        )
    return clusters


def _summarize_answer(answer: str) -> str:
    paragraphs = [para.strip() for para in answer.split("\n\n") if para.strip()]
    if not paragraphs:
        return answer[:280]
    summary = paragraphs[0]
    if len(summary) > 320:
        summary = summary[:320] + "..."
    return summary


def _to_steps(answer: str) -> List[str]:
    lines = [line.strip() for line in answer.splitlines() if line.strip()]
    steps: List[str] = []
    for line in lines:
        if len(line) > 0:
            steps.append(line)
    return steps[:12]


def build_knowledge_cards(clusters: List[ClusteredTopic]) -> List[Dict[str, Any]]:
    cards: List[Dict[str, Any]] = []
    for cluster in clusters:
        metadata = cluster.representative.metadata
        canonical_question = cluster.representative.question
        short_answer = _summarize_answer(cluster.representative.answer)
        step_by_step = _to_steps(cluster.representative.answer)
        links: List[str] = []
        constraints: List[str] = []
        caveats: List[str] = []

        for item in cluster.members:
            source = item.metadata.get("source") or item.metadata.get("url")
            if source and source not in links:
                links.append(str(source))
            constraint = item.metadata.get("constraints")
            if isinstance(constraint, str) and constraint not in constraints:
                constraints.append(constraint)
            caveat = item.metadata.get("caveats")
            if isinstance(caveat, str) and caveat not in caveats:
                caveats.append(caveat)

        card_id = str(uuid.uuid4())
        average_confidence = float(
            np.mean([item.metadata.get("confidence", 0.6) for item in cluster.members])
        )

        card = {
            "id": card_id,
            "canonicalQuestion": canonical_question,
            "shortAnswer": short_answer,
            "stepByStep": step_by_step,
            "links": links,
            "constraints": constraints,
            "caveats": caveats,
            "metrics": {
                "occurrenceCount": len(cluster.members),
                "averageConfidence": round(average_confidence, 3),
            },
            "sourceEmails": [item.source_email_id for item in cluster.members],
            "metadata": metadata,
        }

        cards.append(card)
    return cards


def save_cards(cards: List[Dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_dir = output_dir / "json"
    yaml_dir = output_dir / "yaml"
    json_dir.mkdir(exist_ok=True)
    yaml_dir.mkdir(exist_ok=True)

    index_data = {"cards": []}
    for card in cards:
        index_data["cards"].append(
            {
                "id": card["id"],
                "canonicalQuestion": card["canonicalQuestion"],
                "metrics": card["metrics"],
            }
        )
        with (json_dir / f"{card['id']}.json").open("w", encoding="utf-8") as handle:
            json.dump(card, handle, ensure_ascii=False, indent=2)
        with (yaml_dir / f"{card['id']}.yaml").open("w", encoding="utf-8") as handle:
            yaml.safe_dump(card, handle, sort_keys=False, allow_unicode=True)

    with (output_dir / "index.json").open("w", encoding="utf-8") as handle:
        json.dump(index_data, handle, ensure_ascii=False, indent=2)


def export_review_queue(cards: List[Dict[str, Any]], review_dir: Path) -> None:
    """Produce CSV and JSONL review queues for human approval."""

    review_dir.mkdir(parents=True, exist_ok=True)
    csv_path = review_dir / "review_queue.csv"
    jsonl_path = review_dir / "review_queue.jsonl"

    fieldnames = [
        "card_id",
        "canonical_question",
        "short_answer",
        "average_confidence",
        "source_emails",
        "status",
        "rating",
        "notes",
    ]

    with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for card in cards:
            writer.writerow(
                {
                    "card_id": card["id"],
                    "canonical_question": card["canonicalQuestion"],
                    "short_answer": card["shortAnswer"],
                    "average_confidence": card["metrics"]["averageConfidence"],
                    "source_emails": ";".join(card["sourceEmails"]),
                    "status": "pending",
                    "rating": "",
                    "notes": "",
                }
            )

    with jsonl_path.open("w", encoding="utf-8") as jsonl_file:
        for card in cards:
            payload = {
                "cardId": card["id"],
                "canonicalQuestion": card["canonicalQuestion"],
                "shortAnswer": card["shortAnswer"],
                "metrics": card["metrics"],
                "sourceEmails": card["sourceEmails"],
                "metadata": card.get("metadata", {}),
                "status": "pending",
                "rating": None,
                "notes": None,
            }
            jsonl_file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def persist_cards_to_vector_store(
    cards: List[Dict[str, Any]],
    db_dir: Path,
    collection_name: str,
    embedder: SentenceTransformer,
) -> None:
    if not cards:
        logger.info("No cards to persist to Chroma")
        return

    client = chromadb.PersistentClient(path=str(db_dir))
    collection = client.get_or_create_collection(
        name=collection_name, metadata={"hnsw:space": "cosine"}
    )

    documents = [
        f"Question: {card['canonicalQuestion']}\nAnswer: {card['shortAnswer']}"
        for card in cards
    ]
    metadatas = [
        {
            "card_id": card["id"],
            "source_type": "knowledge_card",
            "canonicalQuestion": card["canonicalQuestion"],
            "metrics": card["metrics"],
        }
        for card in cards
    ]
    ids = [card["id"] for card in cards]
    embeddings = embedder.encode(
        documents, show_progress_bar=False, normalize_embeddings=True
    ).tolist()
    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )


# ------------------------- LangChain pipeline -------------------------


def build_learning_pipeline(
    embedder: SentenceTransformer, similarity_threshold: float
):
    """Create a LangChain Runnable pipeline for the learning flow."""

    extract_node = RunnableLambda(lambda emails: extract_qa_items(emails))
    cluster_node = RunnableLambda(
        lambda qa_items: cluster_items(
            qa_items, embedder=embedder, similarity_threshold=similarity_threshold
        )
    )
    card_node = RunnableLambda(lambda clusters: build_knowledge_cards(clusters))
    return extract_node | cluster_node | card_node


# ------------------------- CLI entry point -------------------------


def run_learning_agent(args: argparse.Namespace) -> List[Dict[str, Any]]:
    logging.basicConfig(level=logging.INFO)
    dataset_path = Path(args.input)
    output_dir = Path(args.output)
    db_dir = Path(args.db_dir)
    embed_model = args.embed_model
    threshold = args.similarity_threshold

    logger.info("Loading email dataset from %s", dataset_path)
    emails = load_email_dataset(dataset_path)
    if not emails:
        logger.warning("No email records found in %s", dataset_path)
        return []

    logger.info("Initializing embedding model: %s", embed_model)
    embedder = SentenceTransformer(embed_model)

    pipeline = build_learning_pipeline(embedder, threshold)
    logger.info("Running learning pipeline on %d emails", len(emails))
    cards = pipeline.invoke(emails)

    logger.info("Generated %d knowledge cards", len(cards))
    save_cards(cards, output_dir)
    persist_cards_to_vector_store(cards, db_dir, args.collection, embedder)
    if args.review_out:
        review_dir = Path(args.review_out)
        export_review_queue(cards, review_dir)
        logger.info("Exported review queue to %s", review_dir)
    return cards


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Learn knowledge cards from historical support emails."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to a JSON/JSONL file or directory with historical email threads.",
    )
    parser.add_argument(
        "--output",
        default="./knowledge_cards",
        help="Directory where knowledge cards will be written.",
    )
    parser.add_argument(
        "--db-dir",
        default=os.getenv("DB_DIR", "./chroma_db"),
        help="Chroma persistence directory for the knowledge base.",
    )
    parser.add_argument(
        "--collection",
        default=os.getenv("COLLECTION", "faq"),
        help="Chroma collection that stores knowledge cards.",
    )
    parser.add_argument(
        "--embed-model",
        default=os.getenv(
            "EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        ),
        help="SentenceTransformer model to use for embeddings.",
    )
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.85,
        help="Cosine similarity threshold for clustering duplicate questions.",
    )
    parser.add_argument(
        "--review-out",
        help=(
            "Optional directory where a human review queue (CSV and JSONL) will be written."
        ),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    run_learning_agent(args)


if __name__ == "__main__":
    main()
