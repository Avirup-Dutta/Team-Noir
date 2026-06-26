"""
safety.py
---------
Post-processing safety layer that runs after the LLM generates a response.

Automatically checks and sanitizes customer_reply and recommended_next_action
to prevent safety rule violations that cost -10 to -15 points each.
"""

import re
from typing import Tuple


# ── Forbidden patterns ─────────────────────────────────────────────────────────

# Rule 1: Never ask for PIN, OTP, password, full card number (-15 pts)
CREDENTIAL_REQUEST_PATTERNS = [
    r"\bshare\s+your\s+(pin|otp|password|card\s+number)\b",
    r"\bprovide\s+your\s+(pin|otp|password)\b",
    r"\benter\s+your\s+(pin|otp|password)\b",
    r"\bsend\s+your\s+(pin|otp|password)\b",
    r"\bverif\w+\s+(with|using|your)\s+(pin|otp|password)\b",
    r"\bwhat\s+is\s+your\s+(pin|otp|password)\b",
    r"\bconfirm\s+your\s+(pin|otp|password)\b",
    r"\byour\s+(pin|otp|password)\s+(for|to|so)\b",
    r"\bneed\s+your\s+(pin|otp|password)\b",
]

# Rule 2: Never confirm refund/reversal/unblock without authority (-10 pts)
UNAUTHORIZED_CONFIRMATION_PATTERNS = [
    r"\bwe\s+will\s+refund\b",
    r"\byou\s+will\s+receive\s+a\s+refund\b",
    r"\brefund\s+has\s+been\s+(approved|confirmed|processed|initiated)\b",
    r"\bwe\s+will\s+(reverse|return)\s+(the\s+)?amount\b",
    r"\byour\s+account\s+will\s+be\s+unblocked\b",
    r"\bwe\s+will\s+recover\s+your\s+(money|funds|amount)\b",
    r"\bwe\s+guarantee\s+(a\s+)?refund\b",
    r"\bwe\s+will\s+credit\s+your\s+account\b",
    r"\bwe\s+will\s+send\s+the\s+money\s+back\b",
    r"\bwe\s+are\s+processing\s+your\s+refund\b",
]

# Rule 3: Never send to suspicious third party (-10 pts)
THIRD_PARTY_PATTERNS = [
    r"\bcontact\s+(?!bkash|our\s+official|our\s+support|our\s+team|us\b)",
    r"\bcall\s+this\s+number\b",
    r"\bvisit\s+(?!our\b)",
    r"\bwhatsapp\b",
    r"\btelegram\b",
]

# Safe replacement text for each violation type
CREDENTIAL_SAFE_REPLACEMENT = (
    "Please do not share your PIN, OTP, or password with anyone, "
    "including our agents. We will never ask for this information."
)

REFUND_SAFE_LANGUAGE = (
    "If your case is eligible, any applicable amount will be "
    "returned through official bKash channels after investigation."
)


def _check_credentials(text: str) -> Tuple[bool, str]:
    """
    Returns (violation_found, cleaned_text).
    Splits into sentences, drops any sentence matching a credential-request
    pattern, and rejoins with a safe replacement appended.
    """
    if not text:
        return False, text

    # Split on sentence-ending punctuation while keeping the delimiters.
    parts = re.split(r"([.!?]+)", text)
    # Re-attach delimiters to their preceding sentence.
    sentences = []
    for i in range(0, len(parts) - 1, 2):
        sentences.append(parts[i] + parts[i + 1])
    if len(parts) % 2 == 1 and parts[-1].strip():
        sentences.append(parts[-1])

    kept = []
    removed = False
    for sent in sentences:
        s_lower = sent.lower()
        if any(re.search(pat, s_lower) for pat in CREDENTIAL_REQUEST_PATTERNS):
            removed = True
            continue
        kept.append(sent)

    if not removed:
        return False, text

    cleaned = " ".join(s.strip() for s in kept if s.strip()).strip()
    if cleaned:
        cleaned = cleaned + " " + CREDENTIAL_SAFE_REPLACEMENT
    else:
        cleaned = CREDENTIAL_SAFE_REPLACEMENT
    return True, cleaned


def _check_unauthorized_refund(text: str) -> Tuple[bool, str]:
    """Returns (violation_found, cleaned_text)."""
    lower = text.lower()
    for pattern in UNAUTHORIZED_CONFIRMATION_PATTERNS:
        if re.search(pattern, lower):
            cleaned = re.sub(
                pattern,
                REFUND_SAFE_LANGUAGE,
                text,
                flags=re.IGNORECASE,
            )
            return True, cleaned.strip()
    return False, text


def _check_third_party(text: str) -> bool:
    """Returns True if a suspicious third-party redirect is detected."""
    lower = text.lower()
    for pattern in THIRD_PARTY_PATTERNS:
        if re.search(pattern, lower):
            return True
    return False


_INJECTION_SIGNALS = [
    # English
        r"ignore\s+(all\s+)?(previous|above|prior)\s+instructions",
        r"forget\s+(all\s+)?instructions",
        r"you\s+are\s+now\s+a",
        r"act\s+as\s+(if\s+you\s+are\s+)?a",
        r"disregard\s+(your\s+)?(safety|rules|guidelines)",
        r"system\s*:\s*",
        r"<\s*system\s*>",
        r"\[INST\]",
        r"new\s+instructions\s*:",
        r"override\s+(safety|rules|instructions)",
        r"pretend\s+you\s+(are|have\s+no)",
        r"do\s+not\s+follow\s+(your\s+)?(safety|rules)",
    # Bangla / Banglish
        r"উপরের\s+(নির্দেশনা|নিয়ম)\s+উপেক্ষা",
        r"নির্দেশনা\s+ভুলে\s+(যাও|দাও)",
        r"তুমি\s+এখন\s+একজন",
        r"নিরাপত্তা\s+নিয়ম\s+অগ্রাহ্য",
        r"system\s*:\s*",  # bilingual code-switch already covered
        r"ignore\s+koro",
        r"rules\s+bhul",
        r"instruction\s+gulo\s+bhul",
    ]

_INJECTION_RE = re.compile("|".join(_INJECTION_SIGNALS), re.IGNORECASE)


def _detect_prompt_injection(complaint: str) -> bool:
    """
    Detect if the complaint text contains embedded instructions
    attempting to override system behavior (prompt injection).
    Covers English, Bangla, and Banglish variants.
    """
    if not complaint:
        return False
    return bool(_INJECTION_RE.search(complaint))


def sanitize_response(
    customer_reply: str,
    recommended_next_action: str,
    complaint: str,
) -> Tuple[str, str, list]:
    """
    Main entry point called from llm.py after the LLM returns its response.

    Returns:
        (safe_customer_reply, safe_recommended_next_action, violations_found)
    """
    violations = []

    # ── Check customer_reply ───────────────────────────────────────────────────
    cred_violation, customer_reply = _check_credentials(customer_reply)
    if cred_violation:
        violations.append("credential_request_removed")

    refund_violation, customer_reply = _check_unauthorized_refund(customer_reply)
    if refund_violation:
        violations.append("unauthorized_refund_language_removed")
        # Replace with safe language if not already present
        if "official" not in customer_reply.lower():
            customer_reply += (
                " " + REFUND_SAFE_LANGUAGE
            )

    if _check_third_party(customer_reply):
        violations.append("third_party_redirect_detected")
        # Append safe channel reminder
        customer_reply += (
            " For any assistance, please use only official bKash support channels: "
            "16247 or the bKash app."
        )

    # ── Check recommended_next_action ─────────────────────────────────────────
    refund_violation_action, recommended_next_action = _check_unauthorized_refund(
        recommended_next_action
    )
    if refund_violation_action:
        violations.append("unauthorized_refund_in_action_removed")

    # ── Prompt injection in complaint ──────────────────────────────────────────
    if _detect_prompt_injection(complaint):
        violations.append("prompt_injection_detected")

    return customer_reply, recommended_next_action, violations
