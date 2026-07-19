from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from cre_pipeline.adapters import CsvValidationError, ParcelCsvAdapter
from cre_pipeline.schemas import EntityReviewImport, ParcelImport


def test_invalid_coordinates_are_rejected() -> None:
    with pytest.raises(ValueError, match="latitude"):
        ParcelImport.model_validate(
            {
                "source_record_id": "bad",
                "address": "1 Test Way",
                "owner_name": "Test LLC",
                "latitude": 100,
                "retrieved_at": "2026-07-19T00:00:00Z",
            }
        )


def test_csv_validation_reports_row(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.csv"
    invalid.write_text(
        "source_record_id,address,owner_name,retrieved_at\nbad,,Example LLC,2026-07-19T00:00:00Z\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvValidationError, match="row 2"):
        list(ParcelCsvAdapter(invalid).records())


def test_entity_review_requires_official_lookup_url() -> None:
    with pytest.raises(ValueError, match="official Maryland entity search"):
        EntityReviewImport.model_validate(
            {
                "entity_name": "Example LLC",
                "reviewer": "Reviewer",
                "review_date": "2026-07-19",
                "official_lookup_url": "https://example.com/entity",
            }
        )


def test_alembic_upgrade_creates_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "migration.db"
    monkeypatch.setenv("CRE_DATABASE_URL", f"sqlite:///{database}")
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    tables = set(inspect(create_engine(f"sqlite:///{database}")).get_table_names())
    assert {"properties", "ownerships", "field_provenance", "scoring_runs"} <= tables
    ownership_columns = {
        column["name"]
        for column in inspect(create_engine(f"sqlite:///{database}")).get_columns("ownerships")
    }
    assert "entity_id" in ownership_columns
    contact_columns = {
        column["name"]
        for column in inspect(create_engine(f"sqlite:///{database}")).get_columns("contacts")
    }
    assert {"outreach_approved_by", "outreach_approved_at"} <= contact_columns
    activity_columns = {
        column["name"]
        for column in inspect(create_engine(f"sqlite:///{database}")).get_columns("activities")
    }
    assert "outcome_code" in activity_columns
