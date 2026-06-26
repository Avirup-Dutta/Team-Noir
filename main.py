"""
main.py
-------
FastAPI application exposing:
  GET  /              → API info
  GET  /health        → {"status": "ok"}
  POST /analyze-ticket → TicketResponse JSON
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

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
        "health": "/health",
    }


# ── Health check ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Main endpoint ──────────────────────────────────────────────────────────────

@app.post("/analyze-ticket", response_model=TicketResponse)
async def analyze_ticket_endpoint(ticket: TicketRequest):
    """
    Accept a ticket JSON body, analyze it, return structured response.
    """

    # Semantic validation
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

    try:
        response: TicketResponse = await analyze_ticket(ticket)
        return response

    except RuntimeError:
        return JSONResponse(
            status_code=500,
            content={"error": "Analysis failed. Please try again."},
        )

    except Exception:
        return JSONResponse(
            status_code=500,
            content={"error": "An internal error occurred."},
        )


# ── Global exception handler ───────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": "An unexpected error occurred."},
    )