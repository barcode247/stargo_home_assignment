from conftest import inbound


def test_same_email_different_casing_is_one_person(seeded):
    index = seeded._snapshot().index
    assert index.by_message["IN-001"] == index.by_message["IN-021"] == "HS-1001"


def test_linkedin_variant_matches_crm(seeded):
    # CRM has www. and lowercase; inbound has no www and mixed case.
    assert seeded._snapshot().index.by_message["IN-009"] == "HS-1013"


def test_email_and_linkedin_link_across_channels(seeded):
    index = seeded._snapshot().index
    assert index.by_message["IN-002"] == index.by_message["IN-003"] == "HS-1004"


def test_subdomain_email_matches_its_own_contact(seeded):
    assert seeded._snapshot().index.by_message["IN-013"] == "HS-1002"


def test_shared_company_domain_does_not_merge_people(seeded):
    index = seeded._snapshot().index
    assert index.by_message["IN-010"] != "HS-1015"  # ops@halden-fwd.de is not Felix


def test_same_name_different_email_stays_separate(seeded):
    result = seeded.submit_inbound(inbound(from_name="Anouk de Vries",
                                           from_email="anouk@otherco.com",
                                           body="Can we book a demo?"))
    assert result.accepted
    assert result.person_id != "HS-1001"


def test_new_message_by_linkedin_joins_existing_person(seeded):
    result = seeded.submit_inbound(inbound(
        from_email=None, linkedin_url="linkedin.com/in/AnOuK-DeVries-NF/",
        channel="linkedin_dm", body="Any update on the demo?"))
    assert result.person_id == "HS-1001"


def test_message_linking_two_established_people_is_rejected(seeded):
    # Anouk's email with Pieter's LinkedIn would merge two real contacts and corrupt the KPIs.
    before = len(seeded.store.messages())
    result = seeded.submit_inbound(inbound(
        from_email="anouk.devries@nordhavenfreight.com",
        linkedin_url="https://www.linkedin.com/in/pieterclaes-bcl", body="Demo please"))
    assert not result.accepted
    assert "two different people" in result.reasons[0]
    assert len(seeded.store.messages()) == before
    assert seeded.qualification("HS-1001").status == "QL"
    assert seeded.qualification("HS-1004").status == "QL"


def test_linkedin_only_lead_is_linked_when_they_email_from_a_known_address(seeded):
    first = seeded.submit_inbound(inbound(
        from_email=None, linkedin_url="linkedin.com/in/erik-lund-nf",
        channel="linkedin_dm", body="Thanks for connecting."))
    second = seeded.submit_inbound(inbound(
        from_email="erik.lund@nordhavenfreight.com", linkedin_url="linkedin.com/in/erik-lund-nf",
        received_at="2026-10-07T10:00:00+03:00",
        body="Following up from LinkedIn: can we book a demo for rate quoting?"))
    assert second.accepted and first.accepted
    assert second.person_id == "HS-1003"
    assert seeded.qualification("HS-1003").message_ids[0] == first.message_id


def test_qualified_person_counted_once_across_messages(quals):
    assert quals["HS-1001"].message_ids == ["IN-001", "IN-021"]
