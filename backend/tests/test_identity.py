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


def test_qualified_person_counted_once_across_messages(quals):
    assert quals["HS-1001"].message_ids == ["IN-001", "IN-021"]
