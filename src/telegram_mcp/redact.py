import re

# Best-effort: catches well-known secret shapes, not every secret.
PATTERNS = {
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "telegram bot token": r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b",
    "aws access key": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "github token": r"\bgh[pousr]_[A-Za-z0-9]{30,}\b",
    "api key (sk-)": r"\bsk-[A-Za-z0-9_-]{20,}\b",
    "slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b",
    "google api key": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "jwt": r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
    "password/secret assignment": (
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b\s*[=:]\s*"
        r"['\"]?(?=[^\s'\"]*[\d_/+=!@#$%^&*-])[^\s'\"]{8,}"
    ),
}
_COMPILED = {k: re.compile(v) for k, v in PATTERNS.items()}


def find(text: str, literals: tuple[str, ...] = ()) -> list[str]:
    kinds = [k for k, rx in _COMPILED.items() if rx.search(text)]
    if any(lit and lit in text for lit in literals):
        kinds.append("this server's own bot token")
    return kinds


def redact(text: str, literals: tuple[str, ...] = ()) -> str:
    for lit in literals:
        if lit:
            text = text.replace(lit, "[REDACTED]")
    for kind, rx in _COMPILED.items():
        text = rx.sub(f"[REDACTED: {kind}]", text)
    return text
