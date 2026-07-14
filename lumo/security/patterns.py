import re

# Separator tolerant of punctuation/underscores an attacker can splice between
# keywords (commas, hyphens, newlines, ...) in addition to plain whitespace.
_SEP = r"[\W_]+"
_SEP0 = r"[\W_]*"

PATTERNS = (
    (
        "OVERRIDE_PHRASE",
        re.compile(
            rf"(ignore|disregard|forget){_SEP}(all{_SEP})?(previous|prior|above|earlier)"
            rf"{_SEP}(instructions|rules|prompts|policies)",
            re.IGNORECASE,
        ),
    ),
    (
        "SYSTEM_OVERRIDE",
        re.compile(
            rf"new{_SEP}(system{_SEP})?(instructions|policy){_SEP0}:"
            rf"|you{_SEP}are{_SEP}now{_SEP}"
            rf"|system{_SEP}prompt",
            re.IGNORECASE,
        ),
    ),
    (
        "ROLE_TAG",
        re.compile(
            rf"</?{_SEP0}(system|assistant|tool){_SEP0}>"
            r"|\[/?(SYSTEM|INST)\]"
            r"|<\|im_(start|end)\|>",
            re.IGNORECASE,
        ),
    ),
    (
        "ADDRESS_CHANGE",
        re.compile(
            rf"(payment|bank|wallet|beneficiary){_SEP}(address|account|details){_SEP}"
            rf"(has{_SEP}|have{_SEP})?(been{_SEP})?(changed|updated)"
            rf"|send{_SEP}(the{_SEP})?(payment|funds|money){_SEP}to{_SEP}(this{_SEP}|the{_SEP})?new{_SEP}address"
            rf"|do{_SEP}not{_SEP}(use|pay){_SEP}the{_SEP}(usual|registered|old|previous)",
            re.IGNORECASE,
        ),
    ),
)

ZERO_WIDTH = (
    "\u200b\u200c\u200d\u200e\u200f"
    "\u2060\u2061\u2062\u2063\u2064"
    "\ufeff\u00ad"
)

STELLAR_ADDRESS = re.compile(r"G[A-Z2-7]{55}", re.IGNORECASE)
