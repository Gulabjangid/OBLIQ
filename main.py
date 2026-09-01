import time
from datetime import datetime, timezone
from typing import Any
from fastapi.middleware.cors import CORSMiddleware

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent import run_compliance_agent
from tools import get_compliance_overview, get_missing_docs, get_upcoming_deadlines, load_data, _get_client_or_raise, ReminderReason


app = FastAPI(
    title="Obliq-io Compliance Agent API",
    version="1.0.0",
    description="Backend prototype for autonomous compliance checks.",
)

# ---------------------------------------------------------------------------
# In-memory reminder log (prototype – not persisted across restarts)
# ---------------------------------------------------------------------------
REMINDER_LOG: list[dict[str, Any]] = []
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ComplianceCheckRequest(BaseModel):
    client_id: str = Field(min_length=1, examples=["101"])


class ComplianceCheckResponse(BaseModel):
    status: str
    took_ms: int
    data: dict[str, Any]


class ComplianceOverviewItem(BaseModel):
    client_id: str
    client_name: str
    email: str
    missing_documents: list[str]
    upcoming_deadlines: list[dict[str, Any]]
    overdue_deadlines: list[dict[str, Any]]


class SendReminderRequest(BaseModel):
    client_id: str = Field(min_length=1, examples=["101"])
    message: str = Field(default="", examples=["Please submit your pending documents."])


class ReminderRecord(BaseModel):
    id: int
    client_id: str
    client_name: str
    recipient_email: str
    reason: str
    message: str
    missing_documents: list[str]
    upcoming_deadlines: list[dict[str, Any]]
    overdue_deadlines: list[dict[str, Any]]
    sent_at: str
    status: str


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Hello from Obliq-io FastAPI backend."}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/compliance/check", response_model=ComplianceCheckResponse)
async def compliance_check(payload: ComplianceCheckRequest) -> ComplianceCheckResponse:
    started = time.perf_counter()

    try:
        result = await run_compliance_agent(payload.client_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Unexpected server error: {exc}") from exc

    duration_ms = int((time.perf_counter() - started) * 1000)

    return ComplianceCheckResponse(
        status="success",
        took_ms=duration_ms,
        data=result,
    )


@app.get("/api/v1/compliance/overview", response_model=list[ComplianceOverviewItem])
async def compliance_overview() -> list[ComplianceOverviewItem]:
    overview = await get_compliance_overview()
    return [ComplianceOverviewItem.model_validate(item) for item in overview]


@app.post("/api/v1/compliance/send-reminder", response_model=ReminderRecord)
async def send_reminder(payload: SendReminderRequest) -> ReminderRecord:
    """Mock send-reminder endpoint.

    Looks up the client, gathers their compliance gaps, composes a mock
    reminder email, and returns the logged reminder. Nothing is actually
    sent – this is a prototype that logs to an in-memory list.
    """
    db = await load_data()

    try:
        client = _get_client_or_raise(db, payload.client_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Gather compliance gaps for the reminder body
    missing_info = await get_missing_docs(payload.client_id)
    deadline_info = await get_upcoming_deadlines(payload.client_id)

    missing_docs: list[str] = missing_info["missing_documents"]
    upcoming: list[dict[str, Any]] = deadline_info["upcoming_deadlines"]
    overdue: list[dict[str, Any]] = deadline_info["overdue_deadlines"]

    # Determine reason
    has_docs_issue = len(missing_docs) > 0
    has_deadline_issue = len(upcoming) > 0 or len(overdue) > 0
    if has_docs_issue and has_deadline_issue:
        reason = ReminderReason.both.value
    elif has_docs_issue:
        reason = ReminderReason.missing_documents.value
    elif has_deadline_issue:
        reason = ReminderReason.upcoming_deadlines.value
    else:
        reason = "no_action_needed"

    # Build the message body
    body_parts: list[str] = []
    if payload.message:
        body_parts.append(payload.message)
    if missing_docs:
        body_parts.append(f"Missing documents: {', '.join(missing_docs)}.")
    if overdue:
        events = [f"{d['event']} (due {d['date']})" for d in overdue]
        body_parts.append(f"Overdue deadlines: {', '.join(events)}.")
    if upcoming:
        events = [f"{d['event']} (due {d['date']}, {d['days_remaining']}d left)" for d in upcoming]
        body_parts.append(f"Upcoming deadlines: {', '.join(events)}.")
    if not body_parts:
        body_parts.append("All compliance checks are clear. No action required.")

    full_message = f"Dear {client.name}, " + " ".join(body_parts)

    record = ReminderRecord(
        id=len(REMINDER_LOG) + 1,
        client_id=payload.client_id,
        client_name=client.name,
        recipient_email=client.email,
        reason=reason,
        message=full_message,
        missing_documents=missing_docs,
        upcoming_deadlines=upcoming,
        overdue_deadlines=overdue,
        sent_at=datetime.now(timezone.utc).isoformat(),
        status="sent_mock",
    )

    REMINDER_LOG.append(record.model_dump())
    return record


@app.get("/api/v1/compliance/reminder-history", response_model=list[ReminderRecord])
async def reminder_history() -> list[ReminderRecord]:
    """Return all mock reminders sent during this session."""
    return [ReminderRecord.model_validate(entry) for entry in REMINDER_LOG]

