from conftest import inbound


def test_seed_garbage_record_is_rejected_with_reasons(seeded):
    rejection = next(r for r in seeded.store.rejections() if r.ref == "IN-019")
    assert "email: invalid email address" in rejection.reasons
    assert "message text is empty" in rejection.reasons


def test_missing_identity_is_rejected(seeded):
    result = seeded.submit_inbound(inbound(from_email="", linkedin_url=""))
    assert not result.accepted
    assert any("email address or a LinkedIn" in r for r in result.reasons)


def test_bad_channel_and_source_rejected(seeded):
    result = seeded.submit_inbound(inbound(channel="fax", source="billboard"))
    assert not result.accepted
    assert len(result.reasons) == 2


def test_blank_source_is_not_recorded_not_an_error(seeded):
    result = seeded.submit_inbound(inbound(source="", body="Please show us a demo."))
    assert result.accepted
    q = next(q for q in seeded.store.qualifications() if q.person_id == result.person_id)
    assert q.first_source is None


def test_received_at_defaults_to_now(seeded):
    result = seeded.submit_inbound(inbound(received_at=None, body="Demo please."))
    message = next(m for m in seeded.store.messages() if m.id == result.message_id)
    assert message.received_at == seeded.clock()


def test_naive_timestamp_is_read_as_israel_time(seeded):
    result = seeded.submit_inbound(inbound(received_at="2026-10-06T10:00:00", body="Demo?"))
    message = next(m for m in seeded.store.messages() if m.id == result.message_id)
    assert message.received_at.utcoffset().total_seconds() == 3 * 3600


def test_rejected_input_never_reaches_messages(seeded):
    before = seeded.store.message_count()
    seeded.submit_inbound(inbound(from_email="not-an-email"))
    assert seeded.store.message_count() == before
