# Team Noir

AI-powered SupportOps copilot for digital finance platforms developed for the SUST CSE Carnival 2026 Codex Community Hackathon.

## Overview

Team Noir analyzes customer complaints together with recent transaction history to identify the relevant transaction, determine whether the available evidence supports the customer's claim, classify the issue, route it to the appropriate department, and generate a safe, structured response for support agents.

The service is designed as an internal support copilot rather than an autonomous decision maker. It follows fintech safety practices by avoiding requests for sensitive credentials, preventing unauthorized refund promises, and escalating ambiguous or high-risk cases for human review.

## Features

- Evidence-based complaint investigation
- Transaction matching and verification
- Automatic case classification
- Department routing
- Severity assessment
- Safe customer reply generation
- Human review detection
- Prompt injection resistance
- FastAPI REST API
- Docker-ready deployment

## Architecture

```text
Client
   │
   ▼
FastAPI API
   │
   ▼
Request Validation
   │
   ▼
Transaction Analysis
   │
   ▼
LLM Reasoning
   │
   ▼
Safety Layer
   │
   ▼
Structured JSON Response
```

## Tech Stack

| Component | Technology |
|----------|------------|
| Backend | FastAPI |
| Language | Python |
| Validation | Pydantic |
| AI | Google Gemini 1.5 Flash |
| Environment | python-dotenv |
| Deployment | Docker |

## API

### Health Check

```http
GET /health
```

Response

```json
{
  "status": "ok"
}
```

### Analyze Ticket

```http
POST /analyze-ticket
```

The endpoint accepts a customer complaint and recent transaction history and returns a structured JSON response containing:

- Relevant transaction
- Evidence verdict
- Case type
- Severity
- Department
- Agent summary
- Recommended next action
- Customer reply
- Human review flag
- Confidence score
- Reason codes

## Installation

Clone the repository.

```bash
git clone https://github.com/Avirup-Dutta/Team-Noir.git
cd Team-Noir
```

Install dependencies.

```bash
pip install -r requirements.txt
```

Create a `.env` file.

```env
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemini-1.5-flash
```

Start the server.

```bash
uvicorn main:app --reload
```

API documentation is available at:

```text
http://localhost:8000/docs
```

## Docker

Build the image.

```bash
docker build -t team-noir .
```

Run the container.

```bash
docker run -p 8000:8000 \
-e GEMINI_API_KEY=YOUR_API_KEY \
team-noir
```

## Safety

The application includes multiple safeguards to satisfy the competition requirements and common fintech support practices.

- Never requests PINs, OTPs, passwords, or full card numbers.
- Never promises refunds, reversals, or account recovery without authorization.
- Ignores prompt injection attempts embedded in customer complaints.
- Directs customers only to official support channels.
- Sanitizes generated responses before returning them to the client.

## Models

| Model | Purpose |
|------|---------|
| Gemini 1.5 Flash | Complaint understanding, reasoning, classification, routing, and response generation |

## Performance

The service combines deterministic transaction analysis with LLM reasoning to improve consistency while keeping response times low. It is designed for lightweight deployment and supports Docker-based execution.

## Limitations

- Requires a valid Gemini API key.
- Depends on external LLM availability.
- Intended as a hackathon prototype rather than a production-ready system.

## Future Work

- Improved multilingual support
- Retrieval-augmented generation (RAG)
- Historical ticket search
- Fraud analytics
- Feedback-driven model improvement

## Team

Developed by **Team Noir** for the **SUST CSE Carnival 2026 Codex Community Hackathon**.

## License

This project is provided for educational and demonstration purposes.
