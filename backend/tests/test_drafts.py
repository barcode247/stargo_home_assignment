import json

import pytest
from conftest import inbound
from test_llm import FakeClient

from stargo.agents.reply_drafter import DraftNotAllowed, InvalidDraft, ReplyDrafter, validate_draft
from stargo.ingest.validation import RecordRejected
from stargo.llm.client import LlmError


def test_template_draft_for_ql_candidate(seeded):
    draft = seeded.draft_reply("HS-1008")  # Marcus, rate cards, wants a demo
    assert draft.status == "pending_approval"
    assert draft.text.startswith("Hi Marcus,")
    assert "Rate Quoting Agent" in draft.text
    assert draft.text.rstrip().endswith("Leo")


def test_template_warns_when_lead_wrote_in_another_language(seeded):
    draft = seeded.draft_reply("HS-1017")  # Noam wrote in Hebrew
    assert any("'he'" in w for w in draft.warnings)


@pytest.mark.parametrize("person_id", ["HS-1006", "HS-1018", "P-IN-010", "P-IN-015",
                                       "HS-1005"])
def test_no_draft_for_suppressed_excluded_review_or_disqualified(seeded, person_id):
    with pytest.raises(DraftNotAllowed):
        seeded.draft_reply(person_id)


def test_approval_records_approver_and_never_sends(seeded):
    seeded.draft_reply("HS-1008")
    approved = seeded.approve_draft("HS-1008", "Leo")
    assert approved.status == "approved" and approved.approved_by == "Leo"


def test_cannot_approve_after_unsubscribe(seeded):
    seeded.draft_reply("HS-1008")
    seeded.submit_inbound(inbound(from_email="m.hale@meridianhaulage.co.uk",
                                  body="Please unsubscribe me."))
    with pytest.raises(DraftNotAllowed):
        seeded.approve_draft("HS-1008", "Leo")


def test_approval_needs_a_name(seeded):
    seeded.draft_reply("HS-1008")
    with pytest.raises(RecordRejected):
        seeded.approve_draft("HS-1008", "  ")


@pytest.mark.parametrize("text", [
    "Hi, see https://stargo.co for details on our agent today.",
    "Hi, write to sales@stargo.co and we will cut costs by 40% quickly.",
    "Hi, our revolutionary agent will transform your quoting team.",
])
def test_draft_validator_blocks_links_figures_and_hype(text):
    with pytest.raises(InvalidDraft):
        validate_draft({"text": text})


def test_model_draft_failure_falls_back_to_template(seeded):
    seeded.drafter = ReplyDrafter(FakeClient(exc=LlmError("HTTP 500")))
    draft = seeded.draft_reply("HS-1008")
    assert draft.generator == "template-v1"
    assert any("Model draft failed" in w for w in draft.warnings)


def test_model_draft_is_validated_and_never_sees_raw_message(seeded):
    fake = FakeClient(reply=json.dumps({"text": "Hi Marcus, thanks. Would a short call next "
                                                "week work to look at your rate cards? Leo"}))
    seeded.drafter = ReplyDrafter(fake)
    draft = seeded.draft_reply("HS-1008")
    assert draft.generator == "llm:fake:fake-model"
    sent = fake.prompts[0][1]
    # Only Agent A's validated fields go in: not the rest of the body, not the address.
    assert "send me times" not in sent
    assert "m.hale@" not in sent
