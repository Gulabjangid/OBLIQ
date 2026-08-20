from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


DATA_PATH = Path(__file__).resolve().parent / "data.json"
_DB_CACHE: Database | None = None


class DocumentStatus(str, Enum):
    uploaded = "uploaded"
    missing = "missing"
    pending = "pending"


class ReminderReason(str, Enum):
    missing_documents = "missing_documents"
    upcoming_deadlines = "upcoming_deadlines"
    both = "both"


class ClientRecord(BaseModel):
    id: str
    name: str
    email: str
    required_documents: list[str] = Field(default_factory=list)


class DocumentRecord(BaseModel):
    client_id: str
    doc_name: str
    status: DocumentStatus


class DeadlineRecord(BaseModel):
    client_id: str
    event: str
    date: date


class Database(BaseModel):
    clients: list[ClientRecord]
    documents: list[DocumentRecord]
    deadlines: list[DeadlineRecord]


class ClientInput(BaseModel):
    client_id: str = Field(min_length=1)


class UpcomingDeadlineInput(BaseModel):
    client_id: str = Field(min_length=1)
    within_days: int = Field(default=30, ge=1, le=365)


class ReminderInput(BaseModel):
    client_id: str = Field(min_length=1)
    reason: ReminderReason
    missing_documents: list[str] = Field(default_factory=list)
    upcoming_deadlines: list[dict[str, Any]] = Field(default_factory=list)


TOOL_ARG_MODELS = {
    "get_missing_docs": ClientInput,
    "get_upcoming_deadlines": UpcomingDeadlineInput,
    "trigger_reminder": ReminderInput,
}


def _read_data_sync() -> Database:
    with DATA_PATH.open("r", encoding="utf-8") as file:
        raw = json.load(file)
    return Database.model_validate(raw)


async def load_data(force_reload: bool = False) -> Database:
    global _DB_CACHE
    if _DB_CACHE is None or force_reload:
        _DB_CACHE = await asyncio.to_thread(_read_data_sync)
    return _DB_CACHE


def _get_client_or_raise(db: Database, client_id: str) -> ClientRecord:
    for client in db.clients:
        if client.id == client_id:
            return client
    raise KeyError(f"Client {client_id} not found")


async def get_missing_docs(client_id: str) -> dict[str, Any]:
    db = await load_data()
    client = _get_client_or_raise(db, client_id)

    client_docs = [doc for doc in db.documents if doc.client_id == client_id]

    uploaded_docs = {
        doc.doc_name for doc in client_docs if doc.status == DocumentStatus.uploaded
    }
    explicit_missing_docs = {
        doc.doc_name for doc in client_docs if doc.status == DocumentStatus.missing
    }

    required_docs = set(client.required_documents)
    inferred_missing_docs = required_docs - uploaded_docs

    missing_docs = sorted(explicit_missing_docs | inferred_missing_docs)

    return {
        "client_id": client_id,
        "missing_documents": missing_docs,
        "missing_count": len(missing_docs),
        "is_compliant_on_documents": len(missing_docs) == 0,
    }


async def get_upcoming_deadlines(client_id: str, within_days: int = 30) -> dict[str, Any]:
    db = await load_data()
    _get_client_or_raise(db, client_id)

    today = date.today()
    upcoming: list[dict[str, Any]] = []
    overdue: list[dict[str, Any]] = []

    for deadline in db.deadlines:
        if deadline.client_id != client_id:
            continue

        days_remaining = (deadline.date - today).days
        payload = {
            "event": deadline.event,
            "date": deadline.date.isoformat(),
            "days_remaining": days_remaining,
        }

        if days_remaining < 0:
            overdue.append(payload)
        elif days_remaining <= within_days:
            upcoming.append(payload)

    upcoming.sort(key=lambda item: item["date"])
    overdue.sort(key=lambda item: item["date"])

    return {
        "client_id": client_id,
        "window_days": within_days,
        "upcoming_deadlines": upcoming,
        "overdue_deadlines": overdue,
        "upcoming_count": len(upcoming),
        "overdue_count": len(overdue),
    }


async def get_compliance_overview(within_days: int = 30) -> list[dict[str, Any]]:
    db = await load_data()
    overview: list[dict[str, Any]] = []

    for client in db.clients:
        missing = await get_missing_docs(client.id)
        deadlines = await get_upcoming_deadlines(client.id, within_days)
        if missing["missing_documents"] or deadlines["upcoming_deadlines"] or deadlines["overdue_deadlines"]:
            overview.append(
                {
                    "client_id": client.id,
                    "client_name": client.name,
                    "email": client.email,
                    "missing_documents": missing["missing_documents"],
                    "upcoming_deadlines": deadlines["upcoming_deadlines"],
                    "overdue_deadlines": deadlines["overdue_deadlines"],
                }
            )

    return overview


async def trigger_reminder(
    client_id: str,
    reason: ReminderReason,
    missing_documents: list[str] | None = None,
    upcoming_deadlines: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    db = await load_data()
    client = _get_client_or_raise(db, client_id)

    missing_documents = missing_documents or []
    upcoming_deadlines = upcoming_deadlines or []

    summary_parts: list[str] = []
    if missing_documents:
        summary_parts.append(f"Missing docs: {', '.join(missing_documents)}")
    if upcoming_deadlines:
        event_list = [f"{item['event']} ({item['date']})" for item in upcoming_deadlines]
        summary_parts.append(f"Upcoming deadlines: {', '.join(event_list)}")

    summary = " | ".join(summary_parts) if summary_parts else "No action required"

    reminder = {
        "client_id": client_id,
        "client_name": client.name,
        "recipient_email": client.email,
        "reason": reason.value,
        "message": (
            f"Dear {client.name}, please review your compliance status. {summary}."
        ),
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "status": "logged",
    }

    # Prototype behavior: the reminder is returned as a log payload and not persisted.
    return reminder


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_missing_docs",
            "description": "Return missing compliance documents for a given client.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_id": {
                        "type": "string",
                        "description": "The unique client ID to inspect.",
                    }
                },
                "required": ["client_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_upcoming_deadlines",
            "description": "Return upcoming and overdue deadlines for a client.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_id": {
                        "type": "string",
                        "description": "The unique client ID to inspect.",
                    },
                    "within_days": {
                        "type": "integer",
                        "description": "Days ahead to treat as upcoming.",
                        "minimum": 1,
                        "maximum": 365,
                        "default": 30,
                    },
                },
                "required": ["client_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_reminder",
            "description": "Draft and log a reminder to the client based on findings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_id": {
                        "type": "string",
                        "description": "The unique client ID to notify.",
                    },
                    "reason": {
                        "type": "string",
                        "enum": [
                            ReminderReason.missing_documents.value,
                            ReminderReason.upcoming_deadlines.value,
                            ReminderReason.both.value,
                        ],
                    },
                    "missing_documents": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                    },
                    "upcoming_deadlines": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "event": {"type": "string"},
                                "date": {"type": "string"},
                                "days_remaining": {"type": "integer"},
                            },
                            "required": ["event", "date", "days_remaining"],
                            "additionalProperties": False,
                        },
                        "default": [],
                    },
                },
                "required": ["client_id", "reason"],
                "additionalProperties": False,
            },
        },
    },
]


TOOL_REGISTRY = {
    "get_missing_docs": get_missing_docs,
    "get_upcoming_deadlines": get_upcoming_deadlines,
    "trigger_reminder": trigger_reminder,
}
