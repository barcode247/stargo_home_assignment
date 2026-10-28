from datetime import date

import pytest
from conftest import add_in_week_candidate, inbound

WEEK = date(2026, 10, 4)


def line(pack, key):
    return next(x for x in pack.acquisition + pack.expansion if x.key == key)


def people(kpi_line):
    return sorted(r.person_id for r in kpi_line.records)


def test_seed_week_numbers(seeded):
    pack = seeded.kpi_pack(WEEK)
    assert people(line(pack, "qls")) == sorted(
        ["HS-1001", "HS-1004", "HS-1009", "HS-1013", "HS-1017", "P-IN-011"])
    assert line(pack, "meetings_booked").actual == 4
    assert line(pack, "meetings_held").actual == 3
    assert line(pack, "opportunities").actual == 2
    assert [x.target for x in pack.acquisition] == [25, 15, 12, 5]


def test_duplicate_acceptance_counts_once(seeded):
    rachel = next(r for r in line(seeded.kpi_pack(WEEK), "qls").records
                  if r.person_id == "HS-1009")
    assert {"SD-003", "SD-004"} <= set(rachel.refs)


def test_expansion_reported_separately(seeded):
    pack = seeded.kpi_pack(WEEK)
    assert people(line(pack, "expansion_accepted")) == ["HS-1011"]
    assert people(line(pack, "expansion_meeting_booked")) == ["HS-1011"]
    assert "HS-1011" not in people(line(pack, "meetings_booked"))


def test_source_uses_earliest_inbound(seeded):
    pack = seeded.kpi_pack(WEEK)
    by_source = {s.source: s for s in pack.qls_by_source}
    # Anouk: IN-001 event-email before IN-021 paid. Pieter: IN-002 email before IN-003 DM.
    assert sorted(r.person_id for r in by_source["event-email"].records) == ["HS-1001",
                                                                            "HS-1004"]
    assert by_source["paid"].count == 1
    assert by_source["new-connection"].count == 1


def test_unreceived_feed_is_unknown_not_zero(seeded):
    by_source = {s.source: s for s in seeded.kpi_pack(WEEK).qls_by_source}
    assert by_source["historical-reactivation"].count is None
    assert by_source["warm-network"].count == 1


def test_late_acceptance_counts_in_its_own_week(seeded):
    pack = seeded.kpi_pack(WEEK)
    assert "HS-1016" not in people(line(pack, "qls"))  # Priya accepted Sun 11 Oct
    assert any(r.person_id == "HS-1016" for r in pack.not_counted)
    next_week = seeded.kpi_pack(date(2026, 10, 11))
    assert "HS-1016" in people(line(next_week, "qls"))


def test_meetings_from_earlier_cohorts_count_by_event_date(seeded):
    held = line(seeded.kpi_pack(WEEK), "meetings_held")
    assert "HS-1015" in people(held)  # Felix accepted in September, meeting held 4 Oct


def test_decision_inside_week_changes_pack(seeded):
    lead = add_in_week_candidate(seeded)
    seeded.record_decision(lead, "accepted", decided_by="Dana",
                           decided_at="2026-10-08T18:00:00+03:00")
    assert lead in people(line(seeded.kpi_pack(WEEK), "qls"))


def test_decision_outside_week_does_not_change_pack(seeded):
    lead = add_in_week_candidate(seeded)
    seeded.record_decision(lead, "accepted", decided_by="Dana",
                           decided_at="2026-10-09T09:00:00+03:00")  # Friday
    assert lead not in people(line(seeded.kpi_pack(WEEK), "qls"))


def test_acceptance_before_any_inbound_is_not_counted(seeded):
    # Marcus's only message arrived Fri 9 Oct; as the week stood, there was nothing to accept.
    seeded.record_decision("HS-1008", "accepted", decided_by="Leo",
                           decided_at="2026-10-07T10:00:00+03:00")
    pack = seeded.kpi_pack(WEEK)
    assert "HS-1008" not in people(line(pack, "qls"))
    assert any(r.person_id == "HS-1008" for r in pack.not_counted)


def test_rejection_later_in_week_removes_ql(seeded):
    seeded.record_decision("HS-1013", "rejected", decided_by="Leo",
                           decided_at="2026-10-08T12:00:00+03:00")
    pack = seeded.kpi_pack(WEEK)
    assert "HS-1013" not in people(line(pack, "qls"))
    assert any(r.person_id == "HS-1013" for r in pack.not_counted)


def test_accepted_needs_review_lead_is_not_counted(seeded):
    seeded.record_decision("P-IN-010", "accepted", decided_by="Leo",
                           decided_at="2026-10-07T09:00:00+03:00")
    pack = seeded.kpi_pack(WEEK)
    assert "P-IN-010" not in people(line(pack, "qls"))
    assert any(r.person_id == "P-IN-010" for r in pack.not_counted)


def test_friday_inbound_counts_when_accepted(seeded):
    # Marcus wrote Fri 00:30 Israel time; accepting him the next Sunday counts then.
    seeded.record_decision("HS-1008", "accepted", decided_by="Leo",
                           decided_at="2026-10-11T09:00:00+03:00")
    assert "HS-1008" in people(line(seeded.kpi_pack(date(2026, 10, 11)), "qls"))


@pytest.mark.parametrize("body", ["Please unsubscribe me.",
                                  "Thanks, but we are not interested any more."])
def test_later_messages_do_not_rewrite_a_past_week(seeded, body):
    # Tom was accepted on 7 Oct. A decline or unsubscribe on 12 Oct changes his status now,
    # but the 4 Oct week is replayed as it stood, so he still counts there.
    seeded.submit_inbound(inbound(from_email="tom.becker@kestrelsc.com", body=body,
                                  received_at="2026-10-12T09:00:00+03:00"))
    expected_now = "suppressed" if "unsubscribe" in body else "QL"
    assert seeded.qualification("HS-1013").status == expected_now
    assert "HS-1013" in people(line(seeded.kpi_pack(WEEK), "qls"))


def test_pack_and_decisions_survive_restart(make_pipeline):
    first = make_pipeline()
    lead = add_in_week_candidate(first)
    first.record_decision(lead, "accepted", decided_by="Dana",
                          decided_at="2026-10-07T09:00:00+03:00")
    first.store.close()

    second = make_pipeline()  # same database file, seed is skipped
    assert second.store.message_count() == 21  # 20 valid seed + 1 pasted
    assert lead in people(line(second.kpi_pack(WEEK), "qls"))
    assert second.store.kpi_pack(WEEK.isoformat())["acquisition"][0]["actual"] == 7
