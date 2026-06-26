"""
main.py
-------
FastAPI application exposing:
  GET  /health         → {"status": "ok"}
  POST /analyze-ticket → TicketResponse JSON
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from models import TicketRequest, TicketResponse
from llm import analyze_ticket

app = FastAPI(
    title="QueueStorm Investigator",
    description="AI copilot for bKash support agents",
    version="1.0.0",
)


# ── Root endpoint ──────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "message": "QueueStorm Investigator API",
        "docs": "/docs",
        "health": "/health"
    }

# ── Health check ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Main endpoint ──────────────────────────────────────────────────────────────

@app.post("/analyze-ticket", response_model=TicketResponse)
async def analyze_ticket_endpoint(request: Request):
    """
    Accept a ticket JSON body, analyze it, return structured response.

    Error handling:
    - 400: malformed JSON or missing required fields
    - 422: semantically invalid input (empty complaint)
    - 500: internal error (never exposes secrets or stack traces)
    """

    # ── Parse raw body ─────────────────────────────────────────────────────────
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON body. Please send a valid JSON object."},
        )

    # ── Validate against schema ────────────────────────────────────────────────
    try:
        ticket = TicketRequest(**body)
    except ValidationError as e:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Request schema validation failed.",
                "details": e.errors(),
            },
        )

    # ── Semantic validation ────────────────────────────────────────────────────
    if not ticket.complaint or not ticket.complaint.strip():
        return JSONResponse(
            status_code=422,
            content={"error": "complaint field must not be empty."},
        )

    if not ticket.ticket_id or not ticket.ticket_id.strip():
        return JSONResponse(
            status_code=422,
            content={"error": "ticket_id field must not be empty."},
        )

    # ── Analyze ────────────────────────────────────────────────────────────────
    try:
        response: TicketResponse = await analyze_ticket(ticket)
        return response
    except RuntimeError as e:
        # Known errors from llm.py (API failure, parse failure)
        return JSONResponse(
            status_code=500,
            content={"error": "Analysis failed. Please try again."},
        )
    except Exception:
        # Unknown errors — log internally but never expose to client
        return JSONResponse(
            status_code=500,
            content={"error": "An internal error occurred."},
        )


# ── Global exception handler (safety net) ─────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all: ensures the service never exposes stack traces or secrets."""
    return JSONResponse(
        status_code=500,
        content={"error": "An unexpected error occurred."},
    )
