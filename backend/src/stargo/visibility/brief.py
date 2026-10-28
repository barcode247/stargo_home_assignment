"""GEO content brief for a visibility gap, checked against brand_context.md.

Every claim carries BC/PP ids. The validator (code, not model) checks the BC-7
contract and blocks claims that cite unknown ids, use figures their source does
not contain, name competitors outside the title and FAQ questions, or use hype.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from stargo.llm.client import ChatClient, LlmError, strip_code_fence
from stargo.visibility.analysis import PromptGap

SOURCE_ID = r"(?:BC-\d[a-z]?|PP-\d)"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Claim(Strict):
    text: str = Field(min_length=1, max_length=600)
    sources: list[str] = Field(default_factory=list)


class Section(Strict):
    heading: str = Field(max_length=120)
    claims: list[Claim] = Field(min_length=1, max_length=8)


class FaqItem(Strict):
    question: str = Field(max_length=200)
    answer: list[Claim] = Field(min_length=1, max_length=4)


class BriefBody(Strict):
    title: str = Field(max_length=160)
    direct_answer: Claim
    sections: list[Section]
    faq: list[FaqItem]
    schema_org_type: str = Field(max_length=60)


class BriefIssue(Strict):
    where: str
    problem: str
    blocked: bool


class ContentBrief(Strict):
    prompt_id: str
    prompt: str
    generator: str
    created_at: str
    body: BriefBody
    issues: list[BriefIssue]
    status: Literal["ok", "needs edit"]


class InvalidBrief(Exception):
    pass


def load_sources(path: Path) -> dict[str, str]:
    """BC/PP id -> its text, parsed from brand_context.md."""
    sources: dict[str, str] = {}
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = re.match(rf"^##\s+({SOURCE_ID})\b(.*)", line)
        item = re.match(rf"^-\s+\*\*({SOURCE_ID})\b(.*)", line)
        match = heading or item
        if match:
            current = match.group(1)
            sources[current] = match.group(2).lstrip(".* ").replace("**", "")
        elif current and line.strip():
            sources[current] += " " + line.strip()
    return {k: v.strip() for k, v in sources.items()}


HYPE = re.compile(r"\b(revolutionary|game[- ]changing|cutting[- ]edge|world[- ]class|"
                  r"best[- ]in[- ]class|disruptive|unparalleled)\b", re.IGNORECASE)


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def validate_brief(body: BriefBody, sources: dict[str, str],
                   competitors: list[str]) -> list[BriefIssue]:
    issues: list[BriefIssue] = []
    words = len(body.direct_answer.text.split())
    if not 40 <= words <= 60:
        issues.append(BriefIssue(where="direct answer", blocked=False,
                                 problem=f"{words} words; the contract needs 40 to 60"))
    if not 3 <= len(body.sections) <= 5:
        issues.append(BriefIssue(where="sections", blocked=False,
                                 problem=f"{len(body.sections)} sections; needs 3 to 5"))
    if not 3 <= len(body.faq) <= 5:
        issues.append(BriefIssue(where="faq", blocked=False,
                                 problem=f"{len(body.faq)} FAQ items; needs 3 to 5"))
    if not body.schema_org_type.strip():
        issues.append(BriefIssue(where="schema", blocked=False, problem="no schema.org type"))

    competitor_re = (re.compile(r"\b(" + "|".join(map(re.escape, competitors)) + r")\b",
                                re.IGNORECASE) if competitors else None)
    claims = [("direct answer", body.direct_answer)]
    claims += [(f"section '{s.heading}'", c) for s in body.sections for c in s.claims]
    claims += [(f"FAQ '{f.question}'", c) for f in body.faq for c in f.answer]
    for where, claim in claims:
        problems = []
        if not claim.sources:
            problems.append("no BC/PP source")
        unknown = [s for s in claim.sources if s not in sources]
        if unknown:
            problems.append(f"unknown source id {', '.join(unknown)}")
        cited_text = " ".join(sources.get(s, "") for s in claim.sources)
        stray = _numbers(claim.text) - _numbers(cited_text)
        if stray:
            problems.append(f"figure {', '.join(sorted(stray))} not in cited source")
        if competitor_re and competitor_re.search(claim.text):
            problems.append("names a competitor in an answer (BC-5)")
        if HYPE.search(claim.text):
            problems.append("hype word (BC-6)")
        issues += [BriefIssue(where=where, problem=p, blocked=True) for p in problems]
    for section in body.sections:
        if competitor_re and competitor_re.search(section.heading):
            issues.append(BriefIssue(where=f"section '{section.heading}'", blocked=True,
                                     problem="names a competitor in a heading (BC-5)"))
    return issues


# ---------- template brief (no LLM key) ----------

PRODUCT_TEMPLATES = {
    "BC-3a": {
        "name": "Rate Quoting Agent",
        "answer": ("Stargo's Rate Quoting Agent is built for forwarders and carriers that "
                   "receive rate requests by email. It reads each request, pulls the relevant "
                   "tariffs and contracts, and drafts a quote for a pricing analyst to approve. "
                   "Agents draft and people approve, so every price is checked by your team."),
        "answer_sources": ["BC-3a", "BC-2", "BC-1"],
        "proof": ["PP-1"],
        "what": "It reads emailed rate requests, pulls the relevant tariffs and contracts, and "
                "drafts a quote for a pricing analyst to approve.",
    },
    "BC-3b": {
        "name": "Document Extraction",
        "answer": ("Stargo's Document Extraction reads bills of lading, air waybills, invoices "
                   "and customs paperwork and writes structured, validated fields into your TMS "
                   "or ERP. It is built for forwarders, carriers, 3PLs, air cargo handlers and "
                   "customs brokers. Agents draft the data and people approve it before use."),
        "answer_sources": ["BC-3b", "BC-2", "BC-1"],
        "proof": ["PP-2", "PP-3"],
        "what": "It extracts structured fields from bills of lading, air waybills, invoices and "
                "customs paperwork into the TMS or ERP, with validation.",
    },
    "BC-3c": {
        "name": "Invoice and Contract Reconciliation",
        "answer": ("Stargo's Invoice and Contract Reconciliation matches carrier invoices to the "
                   "rates in your contracts and flags discrepancies for review. It is built for "
                   "shippers with material freight spend, forwarders and 3PLs. Agents do the "
                   "matching and your team reviews and approves each flagged discrepancy."),
        "answer_sources": ["BC-3c", "BC-2", "BC-1"],
        "proof": [],
        "what": "It matches carrier invoices to contracted rates and flags discrepancies for "
                "review.",
    },
    "BC-3d": {
        "name": "Trade Document Checking",
        "answer": ("Stargo's Trade Document Checking validates trade documents for finance teams "
                   "before funds move. It turns messy documents and emails into checked, "
                   "structured data that a trade-finance team can trust. Agents prepare the "
                   "check and people make the decision, so humans stay in control throughout."),
        "answer_sources": ["BC-3d", "BC-1"],
        "proof": [],
        "what": "It validates trade documents for finance teams before funds move.",
    },
}
PRODUCT_TEMPLATES["BC-1"] = PRODUCT_TEMPLATES["BC-3a"]


def _proof_claims(proof_ids: list[str], sources: dict[str, str]) -> list[Claim]:
    claims = []
    for pid in proof_ids:
        text = sources.get(pid, "").strip(" .")
        if text:
            claims.append(Claim(text=f"Pilot result: {text}.", sources=[pid]))
    return claims


def template_brief_body(gap: PromptGap, sources: dict[str, str]) -> BriefBody:
    product = PRODUCT_TEMPLATES[gap.product or "BC-1"]
    title = gap.prompt[:1].upper() + gap.prompt[1:]
    if not title.endswith("?") and title.split()[0].lower() in ("how", "what", "which"):
        title += "?"
    sections = [
        Section(heading=f"What the {product['name']} does",
                claims=[Claim(text=product["what"], sources=[gap.product or "BC-3a"])]),
        Section(heading="Who it is for",
                claims=[Claim(text="Stargo serves freight forwarders, carriers, 3PLs, air cargo "
                                   "and ground handlers, customs brokers, shippers with material "
                                   "freight spend, and trade-finance teams.",
                              sources=["BC-2"])]),
        Section(heading="How people stay in control",
                claims=[Claim(text="Agents draft and people approve: Stargo turns messy "
                                   "documents, emails and datasets into operational "
                                   "transactions that a person signs off.",
                              sources=["BC-1"])]),
    ]
    if proofs := _proof_claims(product["proof"], sources):
        sections.append(Section(heading="What pilots have shown", claims=proofs))
    sections.append(Section(
        heading="What Stargo is not",
        claims=[Claim(text="Stargo is not a carrier, broker, forwarder or travel company and "
                           "does not move freight. It builds software for the teams that do.",
                      sources=["BC-5"])]))
    faq = [
        FaqItem(question=f"How does Stargo's {product['name']} help?",
                answer=[Claim(text=product["what"], sources=[gap.product or "BC-3a"])]),
        FaqItem(question="Does a person approve the output?",
                answer=[Claim(text="Yes. Agents draft and people approve.", sources=["BC-1"])]),
        FaqItem(question="Is Stargo a carrier or freight forwarder?",
                answer=[Claim(text="No. Stargo does not move freight; it builds agentic AI for "
                                   "freight, logistics and trade-finance teams.",
                              sources=["BC-5", "BC-1"])]),
    ]
    return BriefBody(title=title,
                     direct_answer=Claim(text=product["answer"], sources=product["answer_sources"]),
                     sections=sections[:5], faq=faq, schema_org_type="Article + FAQPage")


# ---------- LLM brief ----------

BRIEF_SYSTEM = """You write a content brief for an article that answer engines (ChatGPT, \
Perplexity, Gemini) can quote. The only allowed facts about Stargo are in BRAND CONTEXT.

Contract (BC-7): the title matches the buyer's question; "direct_answer" is 40 to 60 words; \
3 to 5 sections with descriptive headings; 3 to 5 FAQ items; a suggested schema.org type.
Every claim lists the BC or PP ids it comes from in "sources". Use no figure that is not \
in the cited source. Competitor names may appear only in the title or in an FAQ question \
that repeats the buyer's question, never in answers or headings. No hype words. No \
customer names. Stargo is not a carrier, broker, forwarder or travel company.

Return JSON: {"title": str, "direct_answer": {"text": str, "sources": [ids]}, \
"sections": [{"heading": str, "claims": [{"text": str, "sources": [ids]}]}], \
"faq": [{"question": str, "answer": [{"text": str, "sources": [ids]}]}], \
"schema_org_type": str}"""


class BriefGenerator:
    def __init__(self, brand_context_path: Path, client: ChatClient | None = None) -> None:
        self.brand_context = brand_context_path.read_text(encoding="utf-8")
        self.sources = load_sources(brand_context_path)
        self.client = client
        self.name = f"llm:{client.settings.label}" if client else "template-v1"

    def generate(self, gap: PromptGap, competitors: list[str], now: datetime) -> ContentBrief:
        body, generator, notes = None, self.name, []
        if self.client is not None:
            try:
                body = self._llm_body(gap)
            except (LlmError, InvalidBrief) as exc:
                notes.append(BriefIssue(where="generator", blocked=False,
                                        problem=f"model brief failed ({exc}); template shown"))
        if body is None:
            body, generator = template_brief_body(gap, self.sources), "template-v1"
        issues = notes + validate_brief(body, self.sources, competitors)
        return ContentBrief(prompt_id=gap.prompt_id, prompt=gap.prompt, generator=generator,
                            created_at=now.isoformat(), body=body, issues=issues,
                            status="needs edit" if any(i.blocked for i in issues)
                            or len(issues) > len(notes) else "ok")

    def _llm_body(self, gap: PromptGap) -> BriefBody:
        user = json.dumps({
            "buyer_question": gap.prompt,
            "cluster": gap.cluster,
            "competitors_engines_named": gap.competitors,
            "engines_missing_stargo": [e for e in ("ChatGPT", "Perplexity", "Gemini")
                                       if e not in gap.engines_mentioning],
            "brand_context": self.brand_context,
        })
        raw = strip_code_fence(self.client.complete_json(BRIEF_SYSTEM, user))
        try:
            return BriefBody.model_validate_json(raw)
        except ValidationError:
            raise InvalidBrief("brief failed schema validation") from None
