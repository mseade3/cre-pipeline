from __future__ import annotations

from pathlib import Path

from cre_pipeline.services import ScoreInputs, calculate_priority, load_score_config

CONFIG = Path("config/scoring.yaml")


def test_unknown_evidence_is_explicit_and_not_adverse() -> None:
    result = calculate_priority(
        load_score_config(CONFIG),
        ScoreInputs(completeness=0.5, freshness=1.0, suppressed=False),
    )
    unknown = [item for item in result.components if item.state == "unknown"]
    assert len(unknown) == 6
    assert all(item.contribution == 0 for item in unknown)
    assert result.score == 16.5
    assert result.coverage == 0


def test_entity_status_has_low_weight_and_suppression_blocks_outreach() -> None:
    config = load_score_config(CONFIG)
    result = calculate_priority(
        config,
        ScoreInputs(
            entity_administrative_status=True,
            completeness=0,
            freshness=0,
            suppressed=True,
        ),
    )
    component = next(
        item for item in result.components if item.component == "entity_administrative_status"
    )
    assert component.weight <= 3
    assert component.contribution <= 3
    assert result.outreach_eligible is False


def test_score_is_bounded() -> None:
    result = calculate_priority(
        load_score_config(CONFIG),
        ScoreInputs(
            buyer_fit=1,
            ownership_tenure_years=100,
            absentee_ownership=True,
            vacancy_underutilization=True,
            public_records=True,
            entity_administrative_status=True,
            completeness=1,
            freshness=1,
            recent_outreach=False,
            suppressed=False,
        ),
    )
    assert result.score == 100
    assert result.coverage == 1
