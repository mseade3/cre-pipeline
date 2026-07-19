from __future__ import annotations

from decimal import Decimal

import pytest

from cre_pipeline.underwriting import (
    UnderwritingAssumptions,
    UnderwritingError,
    calculate_underwriting,
)


def _assumptions() -> UnderwritingAssumptions:
    return UnderwritingAssumptions(
        potential_gross_income=Decimal("200000"),
        vacancy_rate=Decimal("0.05"),
        operating_expenses=Decimal("70000"),
        cap_rate_low=Decimal("0.07"),
        cap_rate_high=Decimal("0.09"),
        annual_debt_service=Decimal("80000"),
        cash_equity=Decimal("500000"),
        renovation_budget=Decimal("50000"),
        contingency=Decimal("25000"),
    )


def test_underwriting_formulas_and_label() -> None:
    assumptions = _assumptions()
    result = calculate_underwriting(assumptions)
    assert result.vacancy_allowance == Decimal("10000.00")
    assert result.effective_gross_income == Decimal("190000.00")
    assert result.noi == Decimal("120000.00")
    assert result.value_range_low == Decimal("120000") / Decimal("0.09")
    assert result.value_range_high == Decimal("120000") / Decimal("0.07")
    assert result.dscr == Decimal("1.5")
    assert result.cash_on_cash_return == Decimal("40000") / Decimal("575000")
    output = result.as_dict(assumptions)
    assert output["verified_inputs"] == {}
    assert "not an appraisal" in str(output["label"]).lower()


def test_underwriting_rejects_invalid_rates() -> None:
    assumptions = _assumptions()
    invalid = UnderwritingAssumptions(
        **{
            **assumptions.__dict__,
            "vacancy_rate": Decimal("1.0"),
        }
    )
    with pytest.raises(UnderwritingError, match="Vacancy"):
        calculate_underwriting(invalid)
