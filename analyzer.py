"""
analyzer.py
-----------
Pure-Python transaction matching and preliminary evidence analysis.

This runs BEFORE the LLM call. By resolving the relevant transaction
deterministically we anchor the two highest-value response fields
(relevant_transaction_id, evidence_verdict) without relying on the
LLM to read raw JSON correctly.
"""

from typing import Optional, List, Dict, Any
from models import TransactionHistoryEntry, TransactionStatus, TransactionType
import re


# ── Keyword banks ──────────────────────────────────────────────────────────────

WRONG_TRANSFER_KEYWORDS = [
    "wrong number", "wrong person", "wrong recipient", "sent to wrong",
    "wrong transfer", "mistake", "accidentally", "bul number", "ভুল নম্বর",
    "ভুল ট্রান্সফার", "wrong account"
]

PAYMENT_FAILED_KEYWORDS = [
    "failed", "not received", "deducted", "balance deducted", "not credited",
    "payment failed", "transaction failed", "কাটা গেছে", "পাওয়া যায়নি"
]

REFUND_KEYWORDS = [
    "refund", "return my money", "give back", "money back", "ফেরত",
    "রিফান্ড", "return", "reimburse"
]

DUPLICATE_KEYWORDS = [
    "twice", "double", "duplicate", "charged twice", "double charged",
    "paid twice", "two times", "দুইবার", "দুবার"
]

MERCHANT_KEYWORDS = [
    "merchant", "settlement", "shop", "store", "business", "payment received",
    "merchant portal", "seller"
]

AGENT_KEYWORDS = [
    "agent", "cash in", "cash-in", "deposit", "agent point", "ক্যাশ ইন",
    "এজেন্ট"
]

PHISHING_KEYWORDS = [
    "pin", "otp", "password", "someone called", "call received", "scam",
    "fraud", "suspicious", "asked for", "verify", "asked my", "পিন",
    "ওটিপি", "পাসওয়ার্ড", "ফোন করেছে"
]


def _contains_any(text: str, keywords: List[str]) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def _extract_amount_from_complaint(complaint: str) -> Optional[float]:
    """Pull the first numeric amount mentioned in the complaint."""
    # matches patterns like "5000 taka", "৳500", "500 BDT", "Tk 200"
    patterns = [
        r"(\d[\d,]*)\s*(?:taka|tk|bdt|৳|টাকা)",
        r"(?:taka|tk|bdt|৳|টাকা)\s*(\d[\d,]*)",
        r"(\d[\d,]{2,})",   # fallback: any number >= 100
    ]
    for pat in patterns:
        m = re.search(pat, complaint, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _extract_counterparty_from_complaint(complaint: str) -> Optional[str]:
    """Extract phone number mentioned in the complaint."""
    m = re.search(r"(\+?880\d{10}|01[3-9]\d{8})", complaint)
    return m.group(1) if m else None


def find_relevant_transaction(
    complaint: str,
    history: List[TransactionHistoryEntry],
) -> Optional[TransactionHistoryEntry]:
    """
    Match the complaint to the most likely transaction in the history.
    Strategy (in priority order):
      1. Exact phone number match in counterparty
      2. Amount match within a small tolerance
      3. Status-based match (e.g. failed transaction for a payment_failed complaint)
      4. Most recent transaction as last resort if history has exactly 1 entry
    Returns None if history is empty or no match found.
    """
    if not history:
        return None

    complaint_amount = _extract_amount_from_complaint(complaint)
    complaint_phone  = _extract_counterparty_from_complaint(complaint)

    scored: List[tuple[int, TransactionHistoryEntry]] = []

    for txn in history:
        score = 0

        # Phone number match (strong signal)
        if complaint_phone and complaint_phone in (txn.counterparty or ""):
            score += 40
        elif complaint_phone and txn.counterparty and (
            complaint_phone[-8:] in txn.counterparty
        ):
            score += 20

        # Amount match (strong signal)
        if complaint_amount is not None:
            if abs(txn.amount - complaint_amount) < 1:
                score += 35
            elif abs(txn.amount - complaint_amount) / max(complaint_amount, 1) < 0.1:
                score += 15

        # Status signals
        if _contains_any(complaint, PAYMENT_FAILED_KEYWORDS):
            if txn.status in (TransactionStatus.failed, TransactionStatus.pending):
                score += 20
        if _contains_any(complaint, REFUND_KEYWORDS):
            if txn.status == TransactionStatus.reversed:
                score += 15

        # Type signals
        if _contains_any(complaint, WRONG_TRANSFER_KEYWORDS + REFUND_KEYWORDS):
            if txn.type == TransactionType.transfer:
                score += 10
        if _contains_any(complaint, PAYMENT_FAILED_KEYWORDS):
            if txn.type == TransactionType.payment:
                score += 10
        if _contains_any(complaint, AGENT_KEYWORDS):
            if txn.type == TransactionType.cash_in:
                score += 15
        if _contains_any(complaint, MERCHANT_KEYWORDS):
            if txn.type == TransactionType.settlement:
                score += 15

        scored.append((score, txn))

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_txn = scored[0]

    # Only return a match if we have meaningful evidence
    # (score 0 with single entry → still return it as a weak match)
    if best_score > 0:
        return best_txn
    if len(history) == 1:
        return history[0]   # only one transaction, likely the subject
    return None


def compute_evidence_verdict(
    complaint: str,
    txn: Optional[TransactionHistoryEntry],
) -> str:
    """
    Preliminary evidence verdict based on the matched transaction.
    The LLM may refine this, but we provide a strong starting signal.

    consistent        → complaint story aligns with the transaction data
    inconsistent      → complaint contradicts what the data shows
    insufficient_data → no matching transaction or data is ambiguous
    """
    if txn is None:
        return "insufficient_data"

    # Phishing/social engineering: transaction data is irrelevant
    if _contains_any(complaint, PHISHING_KEYWORDS):
        return "consistent"   # the call/message happened; no TXN needed

    complaint_amount = _extract_amount_from_complaint(complaint)

    # Check for inconsistency signals
    if _contains_any(complaint, PAYMENT_FAILED_KEYWORDS):
        if txn.status == TransactionStatus.completed:
            # Customer says failed but transaction completed → inconsistent
            return "inconsistent"
        if txn.status in (TransactionStatus.failed, TransactionStatus.pending):
            return "consistent"

    if _contains_any(complaint, WRONG_TRANSFER_KEYWORDS):
        if txn.status == TransactionStatus.completed:
            return "consistent"   # money did go out, matches the complaint

    if _contains_any(complaint, REFUND_KEYWORDS):
        if txn.status == TransactionStatus.reversed:
            return "inconsistent"  # already reversed, refund may be invalid
        if txn.status == TransactionStatus.completed:
            return "consistent"

    if _contains_any(complaint, DUPLICATE_KEYWORDS):
        # Need to see duplicate transactions; with limited history it's often unclear
        return "insufficient_data"

    # Amount mismatch check
    if complaint_amount and abs(txn.amount - complaint_amount) > 1:
        return "insufficient_data"

    return "consistent"


def classify_complaint(complaint: str) -> str:
    """
    Heuristic case_type classification — passed to LLM as a hint.
    LLM can override if context warrants.
    """
    if _contains_any(complaint, PHISHING_KEYWORDS):
        return "phishing_or_social_engineering"
    if _contains_any(complaint, DUPLICATE_KEYWORDS):
        return "duplicate_payment"
    if _contains_any(complaint, AGENT_KEYWORDS):
        return "agent_cash_in_issue"
    if _contains_any(complaint, MERCHANT_KEYWORDS):
        return "merchant_settlement_delay"
    if _contains_any(complaint, WRONG_TRANSFER_KEYWORDS):
        return "wrong_transfer"
    if _contains_any(complaint, PAYMENT_FAILED_KEYWORDS):
        return "payment_failed"
    if _contains_any(complaint, REFUND_KEYWORDS):
        return "refund_request"
    return "other"


def build_analysis_context(
    complaint: str,
    history: List[TransactionHistoryEntry],
) -> Dict[str, Any]:
    """
    Top-level function called by llm.py.
    Returns a dict with all pre-computed signals ready to inject into the prompt.
    """
    relevant_txn = find_relevant_transaction(complaint, history)
    evidence     = compute_evidence_verdict(complaint, relevant_txn)
    hint_case    = classify_complaint(complaint)

    return {
        "relevant_transaction_id": relevant_txn.transaction_id if relevant_txn else None,
        "relevant_transaction":    relevant_txn,
        "evidence_verdict_hint":   evidence,
        "case_type_hint":          hint_case,
    }


# ── Rules-only fallback response ──────────────────────────────────────────────

_CASE_TO_DEPARTMENT = {
    "wrong_transfer":                 "dispute_resolution",
    "payment_failed":                 "payments_ops",
    "refund_request":                 "dispute_resolution",
    "duplicate_payment":              "payments_ops",
    "merchant_settlement_delay":      "merchant_operations",
    "agent_cash_in_issue":            "agent_operations",
    "phishing_or_social_engineering": "fraud_risk",
    "other":                          "customer_support",
}


def _pick_severity(case_type: str, amount: Optional[float]) -> str:
    if case_type == "phishing_or_social_engineering":
        return "critical"
    if case_type == "wrong_transfer":
        return "high"
    if case_type == "payment_failed":
        return "high"
    if amount is None:
        return "medium"
    if amount > 10000:
        return "critical"
    if amount > 2000:
        return "high"
    if amount >= 500:
        return "medium"
    return "low"


def _pick_department(case_type: str, evidence: str) -> str:
    base = _CASE_TO_DEPARTMENT.get(case_type, "customer_support")
    # Vague or insufficient data → customer_support regardless of case_type
    if evidence == "insufficient_data":
        return "customer_support"
    return base


def _needs_human_review(case_type: str, severity: str, evidence: str) -> bool:
    if case_type in ("wrong_transfer", "phishing_or_social_engineering", "refund_request"):
        return True
    if severity in ("high", "critical"):
        return True
    if evidence in ("inconsistent", "insufficient_data"):
        return True
    return False


def _build_safe_customer_reply(case_type: str, ticket_id: str) -> str:
    """Hand-crafted reply that always passes the safety regexes."""
    opener = (
        "Thank you for contacting bKash support. We have received your "
        f"concern under ticket {ticket_id} and our team will review it."
    )
    by_case = {
        "wrong_transfer": (
            "Please do not share your PIN, OTP, or password with anyone, "
            "including our agents. We will never ask for this information. "
            "If your case is eligible, any applicable amount will be returned "
            "through official bKash channels after investigation."
        ),
        "payment_failed": (
            "Please do not share your PIN, OTP, or password with anyone, "
            "including our agents. We will never ask for this information. "
            "For any assistance, please use only official bKash support channels: "
            "16247 or the bKash app."
        ),
        "refund_request": (
            "Please do not share your PIN, OTP, or password with anyone, "
            "including our agents. We will never ask for this information. "
            "If your case is eligible, any applicable amount will be returned "
            "through official bKash channels after investigation."
        ),
        "duplicate_payment": (
            "Please do not share your PIN, OTP, or password with anyone, "
            "including our agents. We will never ask for this information. "
            "For any assistance, please use only official bKash support channels: "
            "16247 or the bKash app."
        ),
        "merchant_settlement_delay": (
            "Please do not share your PIN, OTP, or password with anyone, "
            "including our agents. We will never ask for this information. "
            "For any assistance, please use only official bKash support channels: "
            "16247 or the bKash app."
        ),
        "agent_cash_in_issue": (
            "Please do not share your PIN, OTP, or password with anyone, "
            "including our agents. We will never ask for this information. "
            "For any assistance, please use only official bKash support channels: "
            "16247 or the bKash app."
        ),
        "phishing_or_social_engineering": (
            "Please do not share your PIN, OTP, or password with anyone, "
            "including our agents. We will never ask for this information. "
            "For any assistance, please use only official bKash support channels: "
            "16247 or the bKash app."
        ),
        "other": (
            "Please do not share your PIN, OTP, or password with anyone, "
            "including our agents. We will never ask for this information. "
            "For any assistance, please use only official bKash support channels: "
            "16247 or the bKash app."
        ),
    }
    return opener + " " + by_case.get(case_type, by_case["other"])


def _build_agent_summary(
    ticket_id: str, case_type: str, evidence: str,
    txn: Optional[TransactionHistoryEntry], amount: Optional[float],
) -> str:
    txn_part = (
        f" Relevant transaction: {txn.transaction_id} ({txn.type.value}, "
        f"{txn.amount} BDT, status={txn.status.value})."
        if txn is not None
        else " No matching transaction was found in the provided history."
    )
    amt_part = f" Amount mentioned: {amount} BDT." if amount is not None else ""
    return (
        f"Ticket {ticket_id} classified as {case_type} with evidence verdict "
        f"'{evidence}'." + amt_part + txn_part
    )


def _build_next_action(case_type: str) -> str:
    actions = {
        "wrong_transfer": (
            "Verify the recipient details with the customer and escalate to "
            "the dispute resolution team for possible reversal assessment."
        ),
        "payment_failed": (
            "Check transaction logs for the matching transaction, confirm "
            "deduction status, and route to payments operations."
        ),
        "refund_request": (
            "Review transaction history and eligibility, then escalate to "
            "the dispute resolution team for decision."
        ),
        "duplicate_payment": (
            "Identify duplicate transactions from history and forward to "
            "payments operations for reversal assessment."
        ),
        "merchant_settlement_delay": (
            "Verify merchant settlement status with the merchant operations team."
        ),
        "agent_cash_in_issue": (
            "Verify the cash-in transaction with the agent and route to "
            "agent operations for resolution."
        ),
        "phishing_or_social_engineering": (
            "Flag the case to fraud risk and advise the customer not to share "
            "credentials with anyone."
        ),
        "other": (
            "Review the complaint with customer support and request additional "
            "details if needed."
        ),
    }
    return actions.get(case_type, actions["other"])


def build_response_from_rules(
    ticket_id: str,
    complaint: str,
    history: List[TransactionHistoryEntry],
) -> Dict[str, Any]:
    """
    Deterministic, LLM-free TicketResponse payload. Used when Gemini is
    unavailable or returns unparseable output. Returns a dict that conforms
    to the TicketResponse schema (reason_codes and confidence included).
    """
    relevant_txn = find_relevant_transaction(complaint, history)
    evidence     = compute_evidence_verdict(complaint, relevant_txn)
    case_type    = classify_complaint(complaint)
    amount       = _extract_amount_from_complaint(complaint)

    severity = _pick_severity(case_type, amount)
    department = _pick_department(case_type, evidence)
    human_review = _needs_human_review(case_type, severity, evidence)

    reason_codes = []
    if case_type != "other":
        reason_codes.append(case_type)
    if relevant_txn is not None:
        reason_codes.append("transaction_match")
    if evidence != "consistent":
        reason_codes.append(f"evidence_{evidence}")

    return {
        "ticket_id":                ticket_id,
        "relevant_transaction_id":  relevant_txn.transaction_id if relevant_txn else None,
        "evidence_verdict":         evidence,
        "case_type":                case_type,
        "severity":                 severity,
        "department":               department,
        "agent_summary":            _build_agent_summary(
            ticket_id, case_type, evidence, relevant_txn, amount
        ),
        "recommended_next_action":  _build_next_action(case_type),
        "customer_reply":           _build_safe_customer_reply(case_type, ticket_id),
        "human_review_required":    human_review,
        "confidence":               0.6,
        "reason_codes":             reason_codes,
    }
