from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import cast

import pandas as pd
import streamlit as st
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from cre_pipeline import ATTRIBUTION
from cre_pipeline.config import get_settings
from cre_pipeline.db import create_db_engine
from cre_pipeline.models import (
    Activity,
    Contact,
    DuplicateCandidate,
    ManualEntityReview,
    Ownership,
    Property,
    ScoringRun,
    Suppression,
)
from cre_pipeline.outreach import follow_up_queue, generate_property_brief
from cre_pipeline.services import report_metrics
from cre_pipeline.underwriting import (
    UnderwritingAssumptions,
    UnderwritingError,
    calculate_underwriting,
)


def _latest_scores(session: Session) -> dict[int, ScoringRun]:
    runs = session.scalars(
        select(ScoringRun).order_by(ScoringRun.property_id, ScoringRun.created_at.desc())
    ).all()
    return {run.property_id: run for run in runs}


def lead_rows(session: Session) -> list[dict[str, object]]:
    scores = _latest_scores(session)
    properties = session.scalars(
        select(Property).options(selectinload(Property.ownerships)).order_by(Property.id)
    ).all()
    rows: list[dict[str, object]] = []
    for property_record in properties:
        ownership: Ownership | None = (
            property_record.ownerships[0] if property_record.ownerships else None
        )
        score = scores.get(property_record.id)
        rows.append(
            {
                "property_id": property_record.id,
                "address": property_record.address,
                "property_type": property_record.property_type,
                "owner_name": ownership.legal_owner_name if ownership else None,
                "owner_verification": (ownership.verification_status if ownership else "missing"),
                "research_priority": score.score if score else None,
                "evidence_coverage": score.data_coverage if score else None,
                "outreach_eligible": score.outreach_eligible if score else False,
                "source": property_record.source_name,
                "retrieved_at": property_record.retrieved_at,
            }
        )
    return rows


def research_queue_rows(session: Session) -> list[dict[str, object]]:
    duplicates = session.scalars(
        select(DuplicateCandidate)
        .where(DuplicateCandidate.status == "pending")
        .order_by(DuplicateCandidate.id)
    ).all()
    entity_reviews = session.scalars(
        select(ManualEntityReview)
        .where(ManualEntityReview.status == "pending")
        .order_by(ManualEntityReview.entity_name)
    ).all()
    rows: list[dict[str, object]] = [
        {
            "queue_type": "duplicate",
            "record": f"{item.property_id_a} ↔ {item.property_id_b}",
            "reason": item.match_rule,
            "status": item.status,
            "next_step": "Human merge review",
        }
        for item in duplicates
    ]
    rows.extend(
        {
            "queue_type": "entity",
            "record": item.entity_name,
            "reason": item.requested_fields,
            "status": item.status,
            "next_step": "Manual official Maryland lookup; no scraping",
        }
        for item in entity_reviews
    )
    return rows


def contact_control_rows(session: Session) -> list[dict[str, object]]:
    contacts = session.scalars(select(Contact).order_by(Contact.id)).all()
    return [
        {
            "contact_id": item.id,
            "organization": item.organization,
            "person_name": item.person_name,
            "role": item.role,
            "source": item.lawful_contact_source,
            "verification": item.verification_state,
            "approved": item.outreach_approved,
            "approved_by": item.outreach_approved_by,
            "opt_out": item.opt_out_state,
            "do_not_contact": item.do_not_contact,
            "last_contact": item.last_contact_at,
            "next_action": item.next_action_at,
        }
        for item in contacts
    ]


def activity_rows(session: Session) -> list[dict[str, object]]:
    activities = session.scalars(select(Activity).order_by(Activity.occurred_at.desc())).all()
    return [
        {
            "activity_id": item.id,
            "property_id": item.property_id,
            "contact_id": item.contact_id,
            "type": item.activity_type,
            "outcome_code": item.outcome_code,
            "outcome": item.outcome,
            "occurred_at": item.occurred_at,
            "follow_up_at": item.follow_up_at,
            "user": item.user_name,
            "template": item.template_version,
        }
        for item in activities
    ]


def suppression_rows(session: Session) -> list[dict[str, object]]:
    suppressions = session.scalars(select(Suppression).order_by(Suppression.id)).all()
    return [
        {
            "suppression_id": item.id,
            "channel": item.channel,
            "value_hash": f"{item.normalized_value_hash[:12]}…",
            "reason": item.reason,
            "source": item.source,
            "requested_at": item.requested_at,
            "active": item.active,
        }
        for item in suppressions
    ]


def _frame(rows: list[dict[str, object]], empty_message: str) -> pd.DataFrame:
    return pd.DataFrame(rows) if rows else pd.DataFrame({"status": [empty_message]})


def _overview(metrics: dict[str, int | float]) -> None:
    first = st.columns(5)
    first[0].metric("Properties", metrics["records_imported"])
    first[1].metric("Research reviews", metrics["records_requiring_review"])
    first[2].metric("Contacts", metrics["contacts"])
    first[3].metric("Conversations", metrics["conversations"])
    first[4].metric("Decision-makers", metrics["decision_makers_reached"])
    second = st.columns(5)
    second[0].metric("Follow-ups", metrics["follow_ups"])
    second[1].metric("Seller-stated interest", metrics["seller_stated_interest"])
    second[2].metric("Partner referrals", metrics["opportunities_referred"])
    second[3].metric("Offers", metrics["offers"])
    second[4].metric("Closed", metrics["closed_transactions"])
    st.caption("Conversation quality and qualified opportunities matter more than raw call volume.")


def _lead_tab(rows: list[dict[str, object]]) -> None:
    st.subheader("Research priorities")
    if not rows:
        st.info("No properties loaded.")
        return
    types = sorted({str(row["property_type"]) for row in rows if row["property_type"] is not None})
    filter_columns = st.columns(2)
    minimum_score = filter_columns[0].slider("Minimum research priority", 0, 100, 0)
    selected_types = filter_columns[1].multiselect("Property type/use", types)

    def priority(row: dict[str, object]) -> float:
        value = row["research_priority"]
        return float(value) if isinstance(value, (int, float)) else 0.0

    filtered = [
        row
        for row in rows
        if priority(row) >= minimum_score
        and (not selected_types or row["property_type"] in selected_types)
    ]
    st.dataframe(
        _frame(filtered, "No properties match the current filters."),
        hide_index=True,
        use_container_width=True,
    )
    st.caption("Research priority is not a distress score or appraisal.")


def _brief_tab(session: Session, rows: list[dict[str, object]]) -> None:
    st.subheader("Factual property brief")
    if not rows:
        st.info("Load property records before generating a brief.")
        return
    labels = {
        f"{row['property_id']} — {row['address']}": cast(int, row["property_id"]) for row in rows
    }
    selected = st.selectbox("Property", list(labels))
    caller_name = st.text_input("Truthful caller name")
    st.caption("Generating a brief does not create or send an outreach task.")
    if caller_name.strip():
        brief = generate_property_brief(session, labels[selected], caller_name.strip())
        st.code(brief, language="markdown")
        st.download_button(
            "Download Markdown brief",
            data=brief,
            file_name=f"property-{labels[selected]}-brief.md",
            mime="text/markdown",
        )
    else:
        st.info("Enter the truthful caller name to preview the permission-based opener.")


def _underwriting_tab() -> None:
    st.subheader("Assumptions-based scenario")
    st.warning("Not an appraisal, investment recommendation, legal advice, or tax advice.")
    with st.form("underwriting"):
        left, right = st.columns(2)
        potential_gross_income = left.number_input(
            "Potential gross income", min_value=0.0, value=200000.0, step=1000.0
        )
        vacancy_rate = left.number_input(
            "Vacancy rate (decimal)", min_value=0.0, max_value=0.99, value=0.05, step=0.01
        )
        operating_expenses = left.number_input(
            "Operating expenses", min_value=0.0, value=70000.0, step=1000.0
        )
        annual_debt_service = left.number_input(
            "Annual debt service", min_value=0.0, value=80000.0, step=1000.0
        )
        cap_rate_low = right.number_input(
            "Low cap rate (decimal)", min_value=0.001, value=0.07, step=0.005
        )
        cap_rate_high = right.number_input(
            "High cap rate (decimal)", min_value=0.001, value=0.09, step=0.005
        )
        cash_equity = right.number_input("Cash equity", min_value=0.0, value=500000.0, step=5000.0)
        renovation_budget = right.number_input(
            "Renovation budget", min_value=0.0, value=50000.0, step=5000.0
        )
        contingency = right.number_input("Contingency", min_value=0.0, value=25000.0, step=1000.0)
        submitted = st.form_submit_button("Calculate scenario")
    if submitted:
        assumptions = UnderwritingAssumptions(
            potential_gross_income=Decimal(str(potential_gross_income)),
            vacancy_rate=Decimal(str(vacancy_rate)),
            operating_expenses=Decimal(str(operating_expenses)),
            cap_rate_low=Decimal(str(cap_rate_low)),
            cap_rate_high=Decimal(str(cap_rate_high)),
            annual_debt_service=Decimal(str(annual_debt_service)),
            cash_equity=Decimal(str(cash_equity)),
            renovation_budget=Decimal(str(renovation_budget)),
            contingency=Decimal(str(contingency)),
        )
        try:
            output = calculate_underwriting(assumptions).as_dict(assumptions)
        except UnderwritingError as exc:
            st.error(str(exc))
        else:
            st.json(output)


def _compliance_tab() -> None:
    st.subheader("Compliance checklist")
    checklist_path = Path("docs/COMPLIANCE_CHECKLIST.md")
    if checklist_path.is_file():
        st.markdown(checklist_path.read_text(encoding="utf-8"))
    else:
        st.error("Compliance checklist is unavailable.")


def main() -> None:
    st.set_page_config(page_title="CRE Research Pipeline", layout="wide")
    st.title("CRE Research Pipeline")
    st.caption(
        "Local, human-controlled research operations. No email, SMS, letter, or call is sent."
    )
    st.sidebar.warning("Attorney review remains required before real outreach.")
    st.sidebar.caption(f"Attribution: {ATTRIBUTION}")
    settings = get_settings()
    st.sidebar.code(settings.database_url)

    try:
        engine = create_db_engine(settings)
        with Session(engine) as session:
            metrics = report_metrics(session)
            leads = lead_rows(session)
            research = research_queue_rows(session)
            contacts = contact_control_rows(session)
            activities = activity_rows(session)
            follow_ups = [asdict(item) for item in follow_up_queue(session)]
            suppressions = suppression_rows(session)

            tabs = st.tabs(
                [
                    "Overview",
                    "Leads",
                    "Research Queue",
                    "Contacts & Activity",
                    "Follow-Ups",
                    "Suppressions",
                    "Property Brief",
                    "Underwriting",
                    "Compliance",
                ]
            )
            with tabs[0]:
                _overview(metrics)
            with tabs[1]:
                _lead_tab(leads)
            with tabs[2]:
                st.dataframe(
                    _frame(research, "No pending research reviews."),
                    hide_index=True,
                    use_container_width=True,
                )
            with tabs[3]:
                st.subheader("Contact controls")
                st.dataframe(
                    _frame(contacts, "No contacts."),
                    hide_index=True,
                    use_container_width=True,
                )
                st.subheader("Activities")
                st.dataframe(
                    _frame(activities, "No activities."),
                    hide_index=True,
                    use_container_width=True,
                )
            with tabs[4]:
                st.dataframe(
                    _frame(follow_ups, "No follow-ups."),
                    hide_index=True,
                    use_container_width=True,
                )
                st.caption("Visibility only; this dashboard does not dispatch tasks.")
            with tabs[5]:
                st.dataframe(
                    _frame(suppressions, "No suppressions."),
                    hide_index=True,
                    use_container_width=True,
                )
            with tabs[6]:
                _brief_tab(session, leads)
            with tabs[7]:
                _underwriting_tab()
            with tabs[8]:
                _compliance_tab()
    except SQLAlchemyError as exc:
        st.error(
            "Database unavailable or not migrated. Run `uv run alembic upgrade head` "
            "and `uv run cre-pipeline doctor`."
        )
        st.code(type(exc).__name__)


if __name__ == "__main__":
    main()
