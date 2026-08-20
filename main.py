import time
from typing import Any
from fastapi.middleware.cors import CORSMiddleware

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent import run_compliance_agent
from tools import get_compliance_overview


app = FastAPI(
    title="Obliq-io Compliance Agent API",
    version="1.0.0",
    description="Backend prototype for autonomous compliance checks.",
)
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
