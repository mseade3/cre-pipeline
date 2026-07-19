from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from streamlit.testing.v1 import AppTest

from cre_pipeline.dashboard import (
    activity_rows,
    contact_control_rows,
    lead_rows,
    research_queue_rows,
    suppression_rows,
)
from cre_pipeline.models import Base
from cre_pipeline.services import (
    create_pending_entity_reviews,
    find_duplicate_candidates,
    ingest_parcels,
    score_all,
)

FIXTURE = Path("tests/fixtures/parcels.csv")


def _seed(database_url: str) -> None:
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        ingest_parcels(session, FIXTURE, "fixture", "file://fixture.csv")
        find_duplicate_candidates(session)
        create_pending_entity_reviews(session)
        score_all(session, Path("config/scoring.yaml"))


def test_dashboard_data_is_readable_and_redacts_contact_values(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'dashboard-data.db'}"
    _seed(database_url)
    with Session(create_engine(database_url)) as session:
        assert len(lead_rows(session)) == 3
        assert len(research_queue_rows(session)) == 3
        assert contact_control_rows(session) == []
        assert activity_rows(session) == []
        assert suppression_rows(session) == []


def test_streamlit_dashboard_renders_without_live_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'dashboard-app.db'}"
    _seed(database_url)
    monkeypatch.setenv("CRE_DATABASE_URL", database_url)
    app = AppTest.from_file("src/cre_pipeline/dashboard.py", default_timeout=15).run()
    assert not app.exception
    assert app.title[0].value == "CRE Research Pipeline"
    assert any("No email" in caption.value for caption in app.caption)
