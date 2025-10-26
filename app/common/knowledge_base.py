"""Utility helpers for managing knowledge cards and their review state."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
KNOWLEDGE_CARDS_FILE = Path(
    os.getenv("KNOWLEDGE_CARDS_FILE", DATA_DIR / "knowledge_cards.json")
)

_DATA_LOCK = Lock()
_DEFAULT_STATUS = "pending"


def _ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not KNOWLEDGE_CARDS_FILE.exists():
        KNOWLEDGE_CARDS_FILE.write_text("[]", encoding="utf-8")


def _ensure_card_defaults(card: Dict[str, Any]) -> Dict[str, Any]:
    if "id" not in card or not str(card["id"]).strip():
        card["id"] = str(card.get("canonicalQuestion")) or str(card.get("source"))
        if not card["id"]:
            card["id"] = f"card-{hash(json.dumps(card, sort_keys=True)) & 0xFFFFFFFF:x}"
    card.setdefault("status", _DEFAULT_STATUS)
    card.setdefault("reviews", [])
    card.setdefault("created_at", datetime.utcnow().isoformat() + "Z")
    return card


def _load_cards_unlocked() -> List[Dict[str, Any]]:
    _ensure_storage()
    raw = KNOWLEDGE_CARDS_FILE.read_text(encoding="utf-8")
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        data = []
    cards: List[Dict[str, Any]] = []
    for card in data:
        if isinstance(card, dict):
            cards.append(_ensure_card_defaults(card))
    return cards


def _save_cards_unlocked(cards: List[Dict[str, Any]]) -> None:
    KNOWLEDGE_CARDS_FILE.write_text(
        json.dumps(cards, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def list_cards(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return knowledge cards, optionally filtered by status."""
    with _DATA_LOCK:
        cards = _load_cards_unlocked()
        if status:
            return [card for card in cards if card.get("status") == status]
        return cards


def get_card(card_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a knowledge card by its identifier."""
    with _DATA_LOCK:
        for card in _load_cards_unlocked():
            if str(card.get("id")) == str(card_id):
                return card
    return None


def replace_cards(cards: List[Dict[str, Any]]) -> None:
    """Persist a full list of cards (used for batch updates)."""
    with _DATA_LOCK:
        processed = [_ensure_card_defaults(dict(card)) for card in cards]
        _save_cards_unlocked(processed)


def upsert_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """Insert or update a single knowledge card."""
    with _DATA_LOCK:
        cards = _load_cards_unlocked()
        payload = _ensure_card_defaults(dict(card))
        replaced = False
        for idx, existing in enumerate(cards):
            if str(existing.get("id")) == str(payload.get("id")):
                cards[idx] = payload
                replaced = True
                break
        if not replaced:
            cards.append(payload)
        _save_cards_unlocked(cards)
        return payload


def add_review(
    card_id: str,
    review: Dict[str, Any],
    new_status: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Append a review to a card and optionally update its status."""
    with _DATA_LOCK:
        cards = _load_cards_unlocked()
        for idx, card in enumerate(cards):
            if str(card.get("id")) != str(card_id):
                continue
            entry = dict(review)
            entry.setdefault("reviewed_at", datetime.utcnow().isoformat() + "Z")
            card.setdefault("reviews", []).append(entry)
            if new_status:
                card["status"] = new_status
            card["last_reviewed_at"] = entry["reviewed_at"]
            cards[idx] = card
            _save_cards_unlocked(cards)
            return card
    return None


def update_status(card_id: str, status: str) -> Optional[Dict[str, Any]]:
    """Update the status of a knowledge card without recording a review."""
    with _DATA_LOCK:
        cards = _load_cards_unlocked()
        for idx, card in enumerate(cards):
            if str(card.get("id")) != str(card_id):
                continue
            card["status"] = status
            cards[idx] = card
            _save_cards_unlocked(cards)
            return card
    return None
