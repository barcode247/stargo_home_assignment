"""AI-visibility snapshot (GEO / LLM-SEO) from answer-engine captures.

Per answer: is Stargo really mentioned (not a look-alike), is it cited from an owned
domain, which competitors appear, and what is wrong. Per prompt: a gap score.

Gap score (0-100), higher = bigger gap:

    100 x (priority / 3) x product_fit x absence x (0.5 + 0.5 x competitor_share)

- absence = (1 - coverage) / 1.5, where coverage is the mean answer value across engines:
  +0.5 for a correct mention, +0.5 for an owned citation, -0.25 for citing a look-alike
  domain, and -0.5 overall when the answer confuses Stargo with another company or makes
  a claim BC-5 rules out. Coverage runs from -0.5 to 1, so absence runs from 0 to 1.
- competitor_share = distinct known competitors named across engines / known competitors.
  Buyers see a shortlist without us.
- product_fit = 1 when the prompt maps to a BC-3 product (or BC-1 positioning), 0.5 when
  Stargo has no product for it: a gap we cannot honestly fill is a weaker gap.
- priority comes from the capture file (1-3).

Accuracy problems (look-alikes, wrong claims) are also listed separately as alerts,
because a wrong answer about the brand matters even on a low-priority prompt.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

BRAND_RE = re.compile(r"\bstar[- ]?go\b", re.IGNORECASE)

LOOKALIKE_CONTEXT = {
    "travel or holiday booking company": re.compile(
        r"holiday|travel|booking app|hotel|flight booking|refund", re.IGNORECASE),
}
WRONG_CLAIMS = {
    "describes Stargo as a carrier, forwarder or broker (BC-5)": re.compile(
        r"\b(ocean|sea|air)?\s*carrier\b|container shipping|shipping line|freight forwarder"
        r"|customs broker|moves? freight", re.IGNORECASE),
}

CLUSTER_PRODUCT = {
    "rate-quoting": "BC-3a",
    "competitive": "BC-3a",
    "document-extraction": "BC-3b",
    "air-cargo": "BC-3b",
    "invoice-audit": "BC-3c",
    "trade-finance": "BC-3d",
    "brand": "BC-1",
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnswerCheck(Strict):
    answer_id: str
    prompt_id: str
    engine: str
    mentioned: bool
    owned_citation: bool
    competitors: list[str]
    issues: list[str]
    value: float
    answer_text: str
    citations: list[str]


class PromptGap(Strict):
    rank: int
    prompt_id: str
    prompt: str
    cluster: str
    priority: int
    product: str | None
    engines_mentioning: list[str]
    engines_citing_owned: list[str]
    competitors: list[str]
    coverage: float
    absence: float
    competitor_share: float
    product_fit: float
    gap_score: float
    issues: list[str]


class VisibilitySnapshot(Strict):
    brand: str
    own_domains: list[str]
    known_competitors: list[str]
    answers: list[AnswerCheck]
    gaps: list[PromptGap]
    alerts: list[str]
    formula: str


def _host(url: str) -> str:
    host = (urlsplit(url if "://" in url else "//" + url).hostname or "").lower()
    return host.removeprefix("www.")


def is_owned(url: str, own_domains: list[str]) -> bool:
    host = _host(url)
    return any(host == d or host.endswith("." + d) for d in own_domains)


def _sentences_with_brand(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if BRAND_RE.search(s)]


def check_answer(answer: dict, own_domains: list[str], competitors: list[str]) -> AnswerCheck:
    text = answer["answer_text"]
    citations = answer.get("citations") or []
    issues: list[str] = []
    confused = False
    brand_sentences = _sentences_with_brand(text)
    for label, pattern in LOOKALIKE_CONTEXT.items():
        if any(pattern.search(s) for s in brand_sentences):
            issues.append(f"look-alike brand: answer describes a {label}")
            confused = True
    for label, pattern in WRONG_CLAIMS.items():
        if any(pattern.search(s) for s in brand_sentences):
            issues.append(f"wrong claim: {label}")
            confused = True

    mentioned = bool(brand_sentences) and not confused
    owned = any(is_owned(u, own_domains) for u in citations)
    lookalike_domains = sorted({_host(u) for u in citations
                                if "stargo" in _host(u) and not is_owned(u, own_domains)})
    for host in lookalike_domains:
        issues.append(f"cites look-alike domain {host}")

    named = [c for c in competitors if re.search(rf"\b{re.escape(c)}\b", text, re.IGNORECASE)]
    if confused:
        value = -0.5
    else:
        value = (0.5 if mentioned else 0.0) + (0.5 if owned and mentioned else 0.0)
        value -= 0.25 * bool(lookalike_domains)
    return AnswerCheck(answer_id=answer["answer_id"], prompt_id=answer["prompt_id"],
                       engine=answer["engine"], mentioned=mentioned,
                       owned_citation=owned and mentioned, competitors=named, issues=issues,
                       value=value, answer_text=text, citations=citations)


@dataclass
class _PromptAgg:
    prompt: str
    cluster: str
    priority: int
    checks: list[AnswerCheck]


def build_snapshot(data: dict) -> VisibilitySnapshot:
    meta = data["meta"]
    own = [d.lower() for d in meta["own_domains"]]
    competitors = meta["known_competitors"]
    checks = [check_answer(a, own, competitors) for a in data["answers"]]

    prompts: dict[str, _PromptAgg] = {}
    for answer, check in zip(data["answers"], checks, strict=True):
        agg = prompts.setdefault(answer["prompt_id"], _PromptAgg(
            answer["prompt"], answer["cluster"], int(answer["priority"]), []))
        agg.checks.append(check)

    gaps = []
    for prompt_id, agg in prompts.items():
        coverage = sum(c.value for c in agg.checks) / len(agg.checks)
        absence = (1 - coverage) / 1.5
        named = sorted({n for c in agg.checks for n in c.competitors})
        share = len(named) / len(competitors) if competitors else 0.0
        product = CLUSTER_PRODUCT.get(agg.cluster)
        fit = 1.0 if product else 0.5
        score = 100 * (agg.priority / 3) * fit * absence * (0.5 + 0.5 * share)
        gaps.append(PromptGap(
            rank=0, prompt_id=prompt_id, prompt=agg.prompt, cluster=agg.cluster,
            priority=agg.priority, product=product,
            engines_mentioning=[c.engine for c in agg.checks if c.mentioned],
            engines_citing_owned=[c.engine for c in agg.checks if c.owned_citation],
            competitors=named, coverage=round(coverage, 3), absence=round(absence, 3),
            competitor_share=round(share, 3), product_fit=fit, gap_score=round(score, 1),
            issues=[f"{c.engine}: {i}" for c in agg.checks for i in c.issues]))
    gaps.sort(key=lambda g: (-g.gap_score, -g.priority, g.prompt_id))
    ranked = [g.model_copy(update={"rank": i}) for i, g in enumerate(gaps, 1)]
    alerts = [f"{c.answer_id} ({c.engine}): {issue}" for c in checks for issue in c.issues]
    return VisibilitySnapshot(brand=meta.get("brand", "Stargo"), own_domains=own,
                              known_competitors=competitors, answers=checks, gaps=ranked,
                              alerts=alerts, formula=__doc__.split("Gap score", 1)[1].strip())


def load_snapshot(path: Path) -> VisibilitySnapshot:
    return build_snapshot(json.loads(path.read_text(encoding="utf-8")))
