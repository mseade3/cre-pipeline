from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cre_pipeline.models import Suppression
from cre_pipeline.outreach import (
    OutreachControlError,
    add_activity,
    add_suppression,
    approve_contact,
    create_contact,
    follow_up_queue,
    generate_property_brief,
    is_suppressed,
)
from cre_pipeline.services import ingest_parcels, report_metrics, score_all

FIXTURE = Path("tests/fixtures/parcels.csv")


def _property_id(session: Session) -> int:
    ingest_parcels(session, FIXTURE, "fixture", "file://fixture.csv")
    session.flush()
    return 1


def test_outbound_activity_requires_approval_and_suppression_revokes_it(
    session: Session,
) -> None:
    property_id = _property_id(session)
    contact = create_contact(
        session,
        organization="Example Retail Holdings LLC",
        person_name=None,
        role="Property contact",
        lawful_contact_source="Manual business-card review",
        phone="+1 (301) 555-0100",
    )
    with pytest.raises(OutreachControlError, match="Human approval"):
        add_activity(
            session,
            property_id=property_id,
            contact_id=contact.id,
            activity_type="call",
            user_name="Test User",
        )

    approve_contact(session, contact.id, "Human Approver")
    follow_up_at = datetime.now(UTC) + timedelta(days=7)
    activity = add_activity(
        session,
        property_id=property_id,
        contact_id=contact.id,
        activity_type="call",
        outcome_code="conversation",
        outcome="Permission-based conversation completed",
        follow_up_at=follow_up_at,
        user_name="Test User",
        template_version="honest-opener-v1",
    )
    assert activity.id is not None
    assert len(follow_up_queue(session)) == 1
    metrics = report_metrics(session)
    assert metrics["calls_attempted"] == 1
    assert metrics["conversations"] == 1

    add_suppression(
        session,
        channel="phone",
        value="+1 (301) 555-0100",
        reason="Recipient opted out",
        source="Call note",
        is_opt_out=True,
    )
    assert contact.do_not_contact is True
    assert contact.outreach_approved is False
    assert contact.opt_out_state == "opted_out"
    assert is_suppressed(session, "phone", "3015550100") is True
    with pytest.raises(OutreachControlError, match="opted out"):
        approve_contact(session, contact.id, "Human Approver")

    stored = session.scalar(select(Suppression))
    assert stored is not None
    assert "3015550100" not in stored.normalized_value_hash


def test_brief_is_factual_and_contains_compliance_language(session: Session) -> None:
    property_id = _property_id(session)
    score_all(session, Path("config/scoring.yaml"))
    session.flush()
    brief = generate_property_brief(session, property_id, "Jordan Example")
    assert "Property Research Brief" in brief
    assert "Jordan Example" in brief
    assert "I don’t want to assume you’re interested in selling" in brief
    assert "Missing data is not adverse evidence" in brief
    assert "Not an appraisal" in brief
    assert "resident agent" in brief.lower()
