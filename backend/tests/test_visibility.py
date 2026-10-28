import json
from datetime import UTC, datetime

import pytest
from test_llm import FakeClient

from stargo.config import DATA_DIR
from stargo.llm.client import LlmError
from stargo.visibility.analysis import build_snapshot, is_owned, load_snapshot
from stargo.visibility.brief import (
    BriefBody,
    BriefGenerator,
    Claim,
    FaqItem,
    Section,
    load_sources,
    validate_brief,
)

NOW = datetime(2026, 10, 12, tzinfo=UTC)
SNAP = load_snapshot(DATA_DIR / "ai_answers.json")
SOURCES = load_sources(DATA_DIR / "brand_context.md")
BY_ID = {a.answer_id: a for a in SNAP.answers}


def test_owned_domain_matching():
    assert is_owned("https://stargo.co/rate-quoting", ["stargo.co"])
    assert is_owned("https://www.stargo.co", ["stargo.co"])
    assert not is_owned("https://stargo-shipping.com/news", ["stargo.co"])
    assert not is_owned("https://stargo.co.evil.example", ["stargo.co"])


def test_correct_mention_with_owned_citation():
    a = BY_ID["P1-PER"]
    assert a.mentioned and a.owned_citation and a.value == 1.0
    assert a.competitors == ["Laneframe", "QuoteHarbor"]


def test_lookalike_domain_is_not_an_owned_citation():
    a = BY_ID["P2-PER"]
    assert a.mentioned and not a.owned_citation
    assert any("stargo-shipping.com" in i for i in a.issues)


def test_lookalike_brand_is_not_a_mention():
    a = BY_ID["P5-CHA"]
    assert not a.mentioned and a.value < 0
    assert any("look-alike brand" in i for i in a.issues)


def test_wrong_claim_is_flagged():
    a = BY_ID["P5-GEM"]
    assert not a.mentioned
    assert any("carrier" in i for i in a.issues)


def test_competitor_word_boundaries():
    assert BY_ID["P2-CHA"].competitors == ["Laneframe", "DocuFreight"] or \
        sorted(BY_ID["P2-CHA"].competitors) == ["DocuFreight", "Laneframe"]


def test_gap_ranking_and_formula():
    ranks = [g.prompt_id for g in SNAP.gaps]
    assert ranks[0] == "P6"  # absent everywhere, all four competitors, priority 3
    p6 = SNAP.gaps[0]
    assert p6.gap_score == pytest.approx(66.7)
    assert ranks.index("P8") > ranks.index("P3")  # no Stargo product for benchmarking
    assert any("P5-GEM" in a for a in SNAP.alerts)


def test_a_new_engine_answer_changes_the_score():
    data = json.loads((DATA_DIR / "ai_answers.json").read_text(encoding="utf-8"))
    for answer in data["answers"]:
        if answer["prompt_id"] == "P6":
            answer["answer_text"] += " Stargo also drafts quotes from emailed rate requests."
            answer["citations"].append("https://stargo.co/rate-quoting")
    p6 = next(g for g in build_snapshot(data).gaps if g.prompt_id == "P6")
    assert p6.gap_score == 0.0


def test_template_brief_meets_the_contract():
    brief = BriefGenerator(DATA_DIR / "brand_context.md").generate(
        SNAP.gaps[0], SNAP.known_competitors, NOW)
    assert brief.status == "ok", brief.issues
    assert brief.body.title.startswith("Alternatives to Laneframe")  # title repeats question
    assert 3 <= len(brief.body.sections) <= 5 and 3 <= len(brief.body.faq) <= 5


def _body(**changes) -> BriefBody:
    claim = Claim(text="Agents draft and people approve.", sources=["BC-1"])
    body = BriefBody(
        title="Alternatives to Laneframe for freight pricing",
        direct_answer=Claim(text=" ".join(["word"] * 45), sources=["BC-1"]),
        sections=[Section(heading=f"Section {i}", claims=[claim]) for i in range(3)],
        faq=[FaqItem(question=f"Q{i}?", answer=[claim]) for i in range(3)],
        schema_org_type="FAQPage")
    return body.model_copy(update=changes)


@pytest.mark.parametrize("bad_claim, problem", [
    (Claim(text="Stargo cuts quoting time by 90%.", sources=["PP-1"]), "figure 90"),
    (Claim(text="Stargo is faster than Laneframe.", sources=["BC-3a"]), "competitor"),
    (Claim(text="A revolutionary approach.", sources=["BC-1"]), "hype"),
    (Claim(text="Trusted by Maersk.", sources=[]), "no BC/PP source"),
    (Claim(text="Stargo does it.", sources=["BC-99"]), "unknown source"),
])
def test_unsupported_claims_are_blocked(bad_claim, problem):
    body = _body(sections=[Section(heading="Bad", claims=[bad_claim])] * 3)
    issues = validate_brief(body, SOURCES, SNAP.known_competitors)
    assert any(i.blocked and problem in i.problem for i in issues)


def test_pp1_figures_are_allowed_when_cited():
    claim = Claim(text="A pilot cut turnaround from about 3 hours to under 15 minutes.",
                  sources=["PP-1"])
    assert validate_brief(_body(sections=[Section(heading="Proof", claims=[claim])] * 3),
                          SOURCES, SNAP.known_competitors) == []


def test_contract_shape_issues_are_flagged():
    issues = validate_brief(_body(direct_answer=Claim(text="Too short.", sources=["BC-1"])),
                            SOURCES, [])
    assert any("40 to 60" in i.problem for i in issues)


def test_model_brief_failure_falls_back_to_template():
    generator = BriefGenerator(DATA_DIR / "brand_context.md", FakeClient(exc=LlmError("x")))
    brief = generator.generate(SNAP.gaps[0], SNAP.known_competitors, NOW)
    assert brief.generator == "template-v1"
    assert any("model brief failed" in i.problem for i in brief.issues)
    assert brief.status == "ok"


def test_model_brief_with_competitor_claim_needs_edit():
    bad = _body(sections=[Section(heading="Why not QuoteHarbor",
                                  claims=[Claim(text="x", sources=["BC-1"])])] * 3)
    generator = BriefGenerator(DATA_DIR / "brand_context.md",
                               FakeClient(reply=bad.model_dump_json()))
    brief = generator.generate(SNAP.gaps[0], SNAP.known_competitors, NOW)
    assert brief.status == "needs edit"
