import re

PATTERNS = (
    (
        "OVERRIDE_PHRASE",
        re.compile(
            r"(ignore|disregard|forget)\s+(all\s+)?(previous|prior|above|earlier)"
            r"\s+(instructions|rules|prompts|policies)",
            re.IGNORECASE,
        ),
    ),
    (
        "SYSTEM_OVERRIDE",
        re.compile(
            r"new\s+(system\s+)?(instructions|policy)\s*:"
            r"|you\s+are\s+now\s"
            r"|system\s+prompt",
            re.IGNORECASE,
        ),
    ),
    (
        "ROLE_TAG",
        re.compile(
            r"</?\s*(system|assistant|tool)\s*>"
            r"|\[/?(SYSTEM|INST)\]"
            r"|<\|im_(start|end)\|>",
            re.IGNORECASE,
        ),
    ),
    (
        "ADDRESS_CHANGE",
        re.compile(
            r"(payment|bank|wallet|beneficiary)\s+(address|account|details)\s+"
            r"(has\s+|have\s+)?(been\s+)?(changed|updated)"
            r"|send\s+(the\s+)?(payment|funds|money)\s+to\s+(this\s+|the\s+)?new\s+address"
            r"|do\s+not\s+(use|pay)\s+the\s+(usual|registered|old|previous)",
            re.IGNORECASE,
        ),
    ),
)

ZERO_WIDTH = (
    "\u200b\u200c\u200d\u200e\u200f"
    "\u2060\u2061\u2062\u2063\u2064"
    "\ufeff\u00ad"
)

STELLAR_ADDRESS = re.compile(r"G[A-Z2-7]{55}")
