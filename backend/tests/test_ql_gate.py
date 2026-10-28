import pytest
from conftest import inbound

from stargo.rules.buyer import is_relevant_buyer


def cond(q, key):
    return next(c for c in q.conditions if c.key == key)


@pytest.mark.parametrize("person_id", ["HS-1001", "HS-1004", "HS-1009", "HS-1013", "HS-1017",
                                       "P-IN-011"])
def test_accepted_leads_meeting_all_five_are_ql(quals, person_id):
    q = quals[person_id]
    assert q.status == "QL"
    assert q.gate_1_to_4_met
    assert all(c.met for c in q.conditions)


def test_all_four_without_acceptance_is_candidate(quals):
    q = quals["HS-1008"]
    assert q.status == "QL candidate"
    assert cond(q, "sales_acceptance").met is None


def test_stated_facts_behind_free_email_are_marked_unverified(quals):
    q = quals["P-IN-011"]  # Yossi, gmail, states 40-person brokerage in Haifa
    icp = cond(q, "icp_fit")
    assert icp.met is True and icp.verified is False
    assert any("unverified" in e for e in icp.evidence)
    assert q.owner == "Noa"


def test_existing_customer_is_excluded_even_when_accepted(quals):
    q = quals["HS-1011"]
    assert (q.status, q.exclusion, q.owner) == ("excluded", "existing_customer", "Sam")
    assert not q.gate_1_to_4_met


def test_preexisting_open_deal_goes_to_deal_owner(quals):
    q = quals["HS-1012"]
    assert (q.status, q.exclusion, q.owner) == ("excluded", "preexisting_open_deal", "Mei")


def test_deal_created_after_acceptance_is_not_preexisting(seeded):
    assert seeded._snapshot().commercial["HS-1015"] is None


@pytest.mark.parametrize("person_id, exclusion, owner", [
    ("HS-1018", "competitor_or_vendor", None),
    ("HS-1019", "investor", "Founders"),
    ("P-IN-015", "job_seeker", None),
    ("HS-1007", "auto_reply", "Leo"),
])
def test_never_a_new_acquisition_ql(quals, person_id, exclusion, owner):
    q = quals[person_id]
    assert (q.status, q.exclusion, q.owner) == ("excluded", exclusion, owner)


def test_unsubscribe_is_suppressed_without_owner(quals):
    q = quals["HS-1006"]
    assert (q.status, q.owner) == ("suppressed", None)


def test_not_interested_is_nurture(quals):
    assert quals["HS-1002"].status == "nurture"


def test_sales_rejection_disqualifies_and_has_no_owner(quals):
    q = quals["HS-1005"]
    assert (q.status, q.owner) == ("disqualified", None)


def test_researched_only_contacts_are_not_leads(quals):
    assert "HS-1003" not in quals  # CFO, researched, no inbound
    assert "HS-1014" not in quals  # CRM status says "QL", but no inbound or acceptance


def test_researched_contact_who_writes_in_is_assessed(seeded):
    result = seeded.submit_inbound(inbound(
        from_email="erik.lund@nordhavenfreight.com",
        body="We re-key 2,000 invoices a month by hand. Can we see a demo?"))
    q = next(q for q in seeded.store.qualifications() if q.person_id == result.person_id)
    assert result.person_id == "HS-1003"
    assert q.status == "QL candidate"
    assert q.owner == "Dana"


def test_accepted_but_failing_condition_is_not_ql(seeded):
    seeded.record_decision("HS-1006", "accepted", decided_by="Dana")
    seeded.submit_inbound(inbound(from_email="greta.holm@balticacargo.eu",
                                  body="Actually, we re-key invoices by hand. Demo?"))
    q = next(q for q in seeded.store.qualifications() if q.person_id == "HS-1006")
    assert q.status == "suppressed"  # the earlier unsubscribe still wins


def test_accepted_marketing_manager_shows_failing_condition(seeded):
    result = seeded.submit_inbound(inbound(
        from_email="new.marketer@balticacargo.eu",
        body="I am the marketing manager. We re-key invoices by hand. Demo please?"))
    seeded.record_decision(result.person_id, "accepted", decided_by="Dana")
    q = next(q for q in seeded.store.qualifications() if q.person_id == result.person_id)
    assert q.status == "disqualified"
    assert cond(q, "relevant_buyer").met is False
    assert cond(q, "sales_acceptance").met is True
    assert "acceptance does not override" in q.rationale


def test_unknown_region_routes_to_triage(seeded):
    result = seeded.submit_inbound(inbound(
        from_email="ceo@somewhere-logistics.com",
        body="I own a 50-person freight forwarder. We quote 300 rate requests a week "
             "by hand. Can we get a demo?"))
    q = next(q for q in seeded.store.qualifications() if q.person_id == result.person_id)
    assert q.status == "needs review"
    assert q.owner == "Triage queue"
    assert any("Company fit" in f for f in q.review_flags)


@pytest.mark.parametrize("title, employees, expected", [
    ("Head of Pricing", 850, True),
    ("Customs Manager", None, True),
    ("Customer Service Team Lead", 2200, False),
    ("Marketing Manager", 2200, False),
    ("Supply Chain Analyst", 9000, False),
    ("COO", 90, True),
    ("owner", 40, True),
    ("owner", 400, False),
    ("owner", None, None),
    (None, None, None),
])
def test_relevant_buyer(title, employees, expected):
    assert is_relevant_buyer(title, employees)[0] is expected


def test_score_never_changes_status(quals):
    # Wim scores high on pain and intent, but sales rejected him and he is a team lead.
    q = quals["HS-1005"]
    assert q.score.total >= 40
    assert q.status == "disqualified"
