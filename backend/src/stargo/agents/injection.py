"""Deterministic detection of messages that try to instruct the system.

This runs in code on every message, independent of any model, so an LLM that is
itself fooled cannot clear the flag. A hit sends the lead to `needs review`.
False positives are cheap (a human looks); false negatives are not, because
message text never feeds the rules anyway, only the extraction.
"""

import re

INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    name: re.compile(pattern, re.IGNORECASE)
    for name, pattern in {
        "override_instructions": (
            r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}"
            r"\b(previous|prior|above|all|earlier|system|your)\b[^.\n]{0,20}"
            r"\b(rules?|instructions?|prompts?|guidelines?)"
        ),
        "prompt_probe": r"system prompt|developer (message|prompt)|your (instructions|prompt)",
        "role_marker": (
            r"\b(system|developer|assistant)\s*(note|message|instruction)s?\b"
            r"|^\s*(system|assistant|developer)\s*:|<\s*/?\s*(system|instructions?)\s*>|\[/?INST\]"
        ),
        "addressed_to_ai": (
            r"\b(to|dear|hey)\s+(the\s+)?(ai|assistant|llm|model|chatbot|bot|agent)\b"
            r"|\bas an ai\b|\byou are now\b"
        ),
        "status_manipulation": (
            r"\b(mark|set|classify|label|flag|route|score|qualify)\b[^.\n]{0,30}"
            r"\b(lead|this|me|it|us)\b[^.\n]{0,30}"
            r"\b(qualified|ql|score|priority|ceo|owner|100|approved)\b"
        ),
        "foreign_override": r"התעלם|הוראות קודמות|ignoriere|negeer|ignorez|ignora las",
    }.items()
}


def detect_injection(*texts: str | None) -> list[str]:
    """Names of the patterns that matched, empty when the text looks clean."""
    joined = "\n".join(t for t in texts if t)
    return [name for name, pattern in INJECTION_PATTERNS.items() if pattern.search(joined)]
