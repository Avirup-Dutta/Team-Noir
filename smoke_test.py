"""Throwaway smoke test — delete after verifying."""
import os
os.environ.setdefault("GEMINI_API_KEY", "x")

import asyncio
import json

from models import TicketRequest, TransactionHistoryEntry
from llm import analyze_ticket


req = TicketRequest(
    ticket_id="TKT-001",
    complaint="I sent 5000 taka to wrong number 01719876543 around 2pm",
    transaction_history=[
        TransactionHistoryEntry(
            transaction_id="TXN-9101",
            timestamp="2026-04-14T14:08:22Z",
            type="transfer",
            amount=5000,
            counterparty="+8801719876543",
            status="completed",
        )
    ],
)


async def main():
    r = await analyze_ticket(req)
    print(json.dumps(r.model_dump(), indent=2))


asyncio.run(main())