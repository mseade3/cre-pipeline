from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

MONEY = Decimal("0.01")
RATIO = Decimal("0.0001")


class UnderwritingError(ValueError):
    pass


@dataclass(frozen=True)
class UnderwritingAssumptions:
    potential_gross_income: Decimal
    vacancy_rate: Decimal
    operating_expenses: Decimal
    cap_rate_low: Decimal
    cap_rate_high: Decimal
    annual_debt_service: Decimal
    cash_equity: Decimal
    renovation_budget: Decimal
    contingency: Decimal


@dataclass(frozen=True)
class UnderwritingResult:
    potential_gross_income: Decimal
    vacancy_allowance: Decimal
    effective_gross_income: Decimal
    operating_expenses: Decimal
    noi: Decimal
    value_range_low: Decimal
    value_range_high: Decimal
    dscr: Decimal | None
    cash_on_cash_return: Decimal | None
    total_cash_basis: Decimal

    def as_dict(self, assumptions: UnderwritingAssumptions) -> dict[str, object]:
        def money(value: Decimal) -> str:
            return f"{value.quantize(MONEY, rounding=ROUND_HALF_UP):.2f}"

        def ratio(value: Decimal | None) -> str | None:
            return None if value is None else f"{value.quantize(RATIO, rounding=ROUND_HALF_UP):.4f}"

        return {
            "label": "Assumptions-based underwriting scenario — not an appraisal",
            "disclaimer": (
                "Outputs depend entirely on supplied assumptions and are not legal, tax, "
                "appraisal, or investment advice."
            ),
            "verified_inputs": {},
            "assumptions": {
                "potential_gross_income": money(assumptions.potential_gross_income),
                "vacancy_rate": ratio(assumptions.vacancy_rate),
                "operating_expenses": money(assumptions.operating_expenses),
                "cap_rate_low": ratio(assumptions.cap_rate_low),
                "cap_rate_high": ratio(assumptions.cap_rate_high),
                "annual_debt_service": money(assumptions.annual_debt_service),
                "cash_equity": money(assumptions.cash_equity),
                "renovation_budget": money(assumptions.renovation_budget),
                "contingency": money(assumptions.contingency),
            },
            "results": {
                "potential_gross_income": money(self.potential_gross_income),
                "vacancy_allowance": money(self.vacancy_allowance),
                "effective_gross_income": money(self.effective_gross_income),
                "operating_expenses": money(self.operating_expenses),
                "noi": money(self.noi),
                "cap_rate_value_range_low": money(self.value_range_low),
                "cap_rate_value_range_high": money(self.value_range_high),
                "debt_service_coverage_ratio": ratio(self.dscr),
                "cash_on_cash_return": ratio(self.cash_on_cash_return),
                "total_cash_basis": money(self.total_cash_basis),
            },
        }


def calculate_underwriting(
    assumptions: UnderwritingAssumptions,
) -> UnderwritingResult:
    amounts = (
        assumptions.potential_gross_income,
        assumptions.operating_expenses,
        assumptions.annual_debt_service,
        assumptions.cash_equity,
        assumptions.renovation_budget,
        assumptions.contingency,
    )
    if any(value < 0 for value in amounts):
        raise UnderwritingError(
            "Income, expense, debt, equity, and capital inputs must be nonnegative."
        )
    if not Decimal("0") <= assumptions.vacancy_rate < Decimal("1"):
        raise UnderwritingError("Vacancy rate must be at least 0 and less than 1.")
    if assumptions.cap_rate_low <= 0 or assumptions.cap_rate_high <= 0:
        raise UnderwritingError("Cap rates must be positive.")
    if assumptions.cap_rate_low > assumptions.cap_rate_high:
        raise UnderwritingError("Low cap rate may not exceed high cap rate.")

    vacancy_allowance = assumptions.potential_gross_income * assumptions.vacancy_rate
    effective_gross_income = assumptions.potential_gross_income - vacancy_allowance
    noi = effective_gross_income - assumptions.operating_expenses
    value_range_low = noi / assumptions.cap_rate_high
    value_range_high = noi / assumptions.cap_rate_low
    dscr = None if assumptions.annual_debt_service == 0 else noi / assumptions.annual_debt_service
    total_cash_basis = (
        assumptions.cash_equity + assumptions.renovation_budget + assumptions.contingency
    )
    cash_on_cash = (
        None
        if total_cash_basis == 0
        else (noi - assumptions.annual_debt_service) / total_cash_basis
    )
    return UnderwritingResult(
        potential_gross_income=assumptions.potential_gross_income,
        vacancy_allowance=vacancy_allowance,
        effective_gross_income=effective_gross_income,
        operating_expenses=assumptions.operating_expenses,
        noi=noi,
        value_range_low=value_range_low,
        value_range_high=value_range_high,
        dscr=dscr,
        cash_on_cash_return=cash_on_cash,
        total_cash_basis=total_cash_basis,
    )
