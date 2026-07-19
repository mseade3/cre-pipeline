from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cre_pipeline.models import Entity, FieldProvenance, ManualEntityReview, Ownership
from cre_pipeline.services import (
    RESIDENT_AGENT_WARNING,
    create_pending_entity_reviews,
    export_entity_review_queue,
    import_entity_reviews,
    ingest_parcels,
)

PARCEL_FIXTURE = Path("tests/fixtures/parcels.csv")
REVIEW_FIXTURE = Path("tests/fixtures/entity_reviews.csv")


def test_manual_queue_export_contains_blank_review_fields(session: Session, tmp_path: Path) -> None:
    ingest_parcels(session, PARCEL_FIXTURE, "fixture", "file://fixture.csv")
    assert create_pending_entity_reviews(session) == 2
    output = tmp_path / "entity-review-queue.csv"
    assert export_entity_review_queue(session, output) == 2

    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert all(row["reviewer"] == "" for row in rows)
    assert all(row["review_date"] == "" for row in rows)
    assert all(row["resident_agent_warning"] == RESIDENT_AGENT_WARNING for row in rows)
    assert all("egov.maryland.gov" in row["official_lookup_url"] for row in rows)


def test_entity_review_import_is_idempotent_linked_and_provenanced(session: Session) -> None:
    ingest_parcels(session, PARCEL_FIXTURE, "fixture", "file://fixture.csv")
    create_pending_entity_reviews(session)
    first = import_entity_reviews(session, REVIEW_FIXTURE)
    session.flush()
    second = import_entity_reviews(session, REVIEW_FIXTURE)
    session.flush()

    assert first.inserted == 1
    assert second.updated == 1
    entity = session.scalar(select(Entity))
    assert entity is not None
    assert entity.resident_agent_warning == RESIDENT_AGENT_WARNING
    linked = session.scalars(select(Ownership).where(Ownership.entity_id == entity.id)).all()
    assert len(linked) == 2
    assert all(item.entity_match_confidence == 1.0 for item in linked)
    assert all(item.verification_status == "manual_entity_name_match" for item in linked)
    assert (
        session.scalar(
            select(func.count())
            .select_from(FieldProvenance)
            .where(
                FieldProvenance.record_type == "entity",
                FieldProvenance.record_id == entity.id,
            )
        )
        == 7
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(ManualEntityReview)
            .where(ManualEntityReview.status == "completed")
        )
        == 1
    )
