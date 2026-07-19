from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, InvalidOperation
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

PAGE_CSS = """
<style>
    .block-container { padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1180px; }
    h1, h2, h3 { letter-spacing: -0.02em; }
    [data-testid="stMetricValue"] { font-size: 1.55rem; }
    [data-testid="stMetricLabel"] { font-size: 0.92rem; }
    div[data-testid="stAlert"] { border-radius: 0.55rem; }
</style>
"""


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
    return pd.DataFrame(rows) if rows else pd.DataFrame({"Note": [empty_message]})


def _rename(frame: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    if list(frame.columns) == ["Note"]:
        return frame
    return frame.rename(columns=mapping)


def _show_table(rows: list[dict[str, object]], empty_message: str, mapping: dict[str, str]) -> None:
    frame = _rename(_frame(rows, empty_message), mapping)
    st.dataframe(frame, hide_index=True, use_container_width=True)


def _sidebar(settings_database_url: str, metrics: dict[str, int | float]) -> None:
    st.sidebar.header("How to use this screen")
    st.sidebar.markdown(
        """
1. Check **Home** for what needs attention.
2. Sort properties in **Properties**.
3. Clear items in **To review**.
4. Preview a call sheet in **Call brief**.
5. Use CLI commands for approvals, activities, and suppressions.
        """
    )
    st.sidebar.divider()
    st.sidebar.subheader("At a glance")
    st.sidebar.write(f"Properties loaded: **{metrics['records_imported']}**")
    st.sidebar.write(f"Items waiting for review: **{metrics['records_requiring_review']}**")
    st.sidebar.write(f"Open follow-ups: **{metrics['follow_ups']}**")
    st.sidebar.divider()
    st.sidebar.warning("This app never sends email, texts, letters, or calls.")
    st.sidebar.caption("Attorney review is still required before real outreach.")
    st.sidebar.caption(f"Data attribution: {ATTRIBUTION}")
    with st.sidebar.expander("Technical details"):
        st.code(settings_database_url)
        st.caption("Mutations stay in the CLI so every change stays auditable.")


def _overview(metrics: dict[str, int | float]) -> None:
    st.subheader("Home")
    st.write(
        "This is your research workbook. Scores help you decide what to study next. "
        "They are not distress scores, appraisals, or proof that anyone wants to sell."
    )

    needs_review = int(metrics["records_requiring_review"])
    follow_ups = int(metrics["follow_ups"])
    if needs_review or follow_ups:
        st.info(
            f"Next up: **{needs_review}** item(s) need research review and "
            f"**{follow_ups}** follow-up(s) are on the calendar."
        )
    else:
        st.success("No pending reviews or follow-ups. Import or score more properties when ready.")

    st.markdown("##### Pipeline health")
    first = st.columns(5)
    first[0].metric("Properties", metrics["records_imported"])
    first[1].metric("Waiting for review", metrics["records_requiring_review"])
    first[2].metric("Contacts on file", metrics["contacts"])
    first[3].metric("Calls attempted", metrics["calls_attempted"])
    first[4].metric("Suppressions / opt-outs", metrics["opt_outs_and_suppressions"])

    st.markdown("##### Outcomes that matter")
    second = st.columns(5)
    second[0].metric("Conversations", metrics["conversations"])
    second[1].metric("Decision-makers reached", metrics["decision_makers_reached"])
    second[2].metric("Seller-stated interest", metrics["seller_stated_interest"])
    second[3].metric("Partner referrals", metrics["opportunities_referred"])
    second[4].metric("Offers / closed", f"{metrics['offers']} / {metrics['closed_transactions']}")
    st.caption(
        "Optimize for verified conversations and qualified opportunities, not raw call volume."
    )


def _lead_tab(rows: list[dict[str, object]]) -> None:
    st.subheader("Properties")
    st.write(
        "Browse scored properties and filter what to research next. "
        "Higher research priority only means “look here sooner,” not “owner is distressed.”"
    )
    if not rows:
        st.info("No properties loaded yet. Import a CSV or run `fetch-pg-data` from the CLI.")
        return

    types = sorted({str(row["property_type"]) for row in rows if row["property_type"] is not None})
    filter_columns = st.columns(2)
    minimum_score = filter_columns[0].slider("Show scores at least", 0, 100, 0)
    selected_types = filter_columns[1].multiselect("Limit to property type / use", types)

    def priority(row: dict[str, object]) -> float:
        value = row["research_priority"]
        return float(value) if isinstance(value, (int, float)) else 0.0

    filtered = [
        row
        for row in rows
        if priority(row) >= minimum_score
        and (not selected_types or row["property_type"] in selected_types)
    ]
    display_rows = [
        {
            **row,
            "evidence_coverage_pct": (
                f"{float(row['evidence_coverage']) * 100:.0f}%"
                if isinstance(row["evidence_coverage"], (int, float))
                else "—"
            ),
            "outreach_eligible_label": (
                "Yes (still needs human approval)" if row["outreach_eligible"] else "No"
            ),
        }
        for row in filtered
    ]
    _show_table(
        display_rows,
        "No properties match the current filters.",
        {
            "property_id": "ID",
            "address": "Address",
            "property_type": "Type / use",
            "owner_name": "Owner name",
            "owner_verification": "Owner verification",
            "research_priority": "Research priority (0–100)",
            "evidence_coverage_pct": "Evidence coverage",
            "outreach_eligible_label": "Eligible for outreach queue?",
            "source": "Source",
            "retrieved_at": "Retrieved",
            "evidence_coverage": "Evidence coverage (raw)",
            "outreach_eligible": "Outreach eligible (raw)",
        },
    )
    st.caption(
        "“Eligible for outreach queue?” is not permission to contact anyone. "
        "Approve contacts in the CLI first."
    )


def _research_tab(rows: list[dict[str, object]]) -> None:
    st.subheader("To review")
    st.write(
        "These items need a human decision before the pipeline treats them as settled: "
        "possible duplicates and Maryland entity lookups."
    )
    if not rows:
        st.success("Nothing waiting in the review queue.")
        return
    _show_table(
        rows,
        "Nothing waiting in the review queue.",
        {
            "queue_type": "Review type",
            "record": "What to review",
            "reason": "Why it was flagged",
            "status": "Status",
            "next_step": "Suggested next step",
        },
    )
    st.caption(
        "Entity reviews must use the official Maryland Business Express lookup. "
        "This app does not scrape SDAT."
    )


def _contacts_tab(contacts: list[dict[str, object]], activities: list[dict[str, object]]) -> None:
    st.subheader("Contacts & activity")
    st.write(
        "Phone numbers and emails are hidden here on purpose. "
        "Use the CLI to add, approve, or suppress contacts."
    )
    st.markdown("##### Contacts")
    _show_table(
        contacts,
        "No contacts yet. Add one with `cre-pipeline contact-add`.",
        {
            "contact_id": "Contact ID",
            "organization": "Organization",
            "person_name": "Person",
            "role": "Role",
            "source": "Lawful source",
            "verification": "Verification",
            "approved": "Human approved?",
            "approved_by": "Approved by",
            "opt_out": "Opt-out state",
            "do_not_contact": "Do not contact?",
            "last_contact": "Last contact",
            "next_action": "Next action",
        },
    )
    st.markdown("##### Activity log")
    _show_table(
        activities,
        "No activities yet. Record them with `cre-pipeline activity-add`.",
        {
            "activity_id": "Activity ID",
            "property_id": "Property ID",
            "contact_id": "Contact ID",
            "type": "Type",
            "outcome_code": "Outcome code",
            "outcome": "Notes",
            "occurred_at": "When",
            "follow_up_at": "Follow-up due",
            "user": "Logged by",
            "template": "Template / version",
        },
    )


def _follow_ups_tab(rows: list[dict[str, object]]) -> None:
    st.subheader("Follow-ups")
    st.write(
        "This is a calendar view only. It does not create call tasks, send reminders, "
        "or contact anyone."
    )
    _show_table(
        rows,
        "No follow-ups scheduled.",
        {
            "activity_id": "Activity ID",
            "property_id": "Property ID",
            "contact_id": "Contact ID",
            "activity_type": "Type",
            "outcome_code": "Outcome code",
            "outcome": "Notes",
            "follow_up_at": "Follow-up due",
            "user_name": "Owner",
            "outreach_approved": "Still approved?",
            "do_not_contact": "Do not contact?",
        },
    )


def _suppressions_tab(rows: list[dict[str, object]]) -> None:
    st.subheader("Do-not-contact / suppressions")
    st.write(
        "Suppressed values are stored as one-way hashes, not the original phone, email, "
        "or mailing address. Matching approvals are revoked automatically."
    )
    _show_table(
        rows,
        "No suppressions yet.",
        {
            "suppression_id": "ID",
            "channel": "Channel",
            "value_hash": "Hashed value",
            "reason": "Reason",
            "source": "Source",
            "requested_at": "Recorded",
            "active": "Active?",
        },
    )


def _brief_tab(session: Session, rows: list[dict[str, object]]) -> None:
    st.subheader("Call brief")
    st.write(
        "Generate a one-page research brief and a permission-based opener. "
        "This does not place a call or create an outreach task."
    )
    if not rows:
        st.info("Load property records before generating a brief.")
        return
    labels = {
        f"{row['property_id']} — {row['address']}": cast(int, row["property_id"]) for row in rows
    }
    selected = st.selectbox("Choose a property", list(labels))
    caller_name = st.text_input(
        "Your real name for the opener",
        placeholder="Example: Miles",
        help="Use the name you will actually say on the call.",
    )
    if caller_name.strip():
        brief = generate_property_brief(session, labels[selected], caller_name.strip())
        st.download_button(
            "Download brief as Markdown",
            data=brief,
            file_name=f"property-{labels[selected]}-brief.md",
            mime="text/markdown",
        )
        st.markdown(brief)
    else:
        st.info("Enter your real name above to preview the brief and call opener.")


def _money(value: object) -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    return f"${amount:,.2f}"


def _underwriting_tab() -> None:
    st.subheader("Underwriting scenario")
    st.warning(
        "Assumptions only. This is **not** an appraisal, investment recommendation, "
        "legal advice, or tax advice."
    )
    st.write("Enter what you are assuming, then review the calculated scenario.")
    with st.form("underwriting"):
        left, right = st.columns(2)
        potential_gross_income = left.number_input(
            "Potential gross income ($ / year)", min_value=0.0, value=200000.0, step=1000.0
        )
        vacancy_rate = left.number_input(
            "Vacancy rate (example: 0.05 = 5%)",
            min_value=0.0,
            max_value=0.99,
            value=0.05,
            step=0.01,
        )
        operating_expenses = left.number_input(
            "Operating expenses ($ / year)", min_value=0.0, value=70000.0, step=1000.0
        )
        annual_debt_service = left.number_input(
            "Annual debt service ($ / year)", min_value=0.0, value=80000.0, step=1000.0
        )
        cap_rate_low = right.number_input(
            "Low cap rate (example: 0.07 = 7%)",
            min_value=0.001,
            value=0.07,
            step=0.005,
        )
        cap_rate_high = right.number_input(
            "High cap rate (example: 0.09 = 9%)",
            min_value=0.001,
            value=0.09,
            step=0.005,
        )
        cash_equity = right.number_input(
            "Cash equity ($)", min_value=0.0, value=500000.0, step=5000.0
        )
        renovation_budget = right.number_input(
            "Renovation budget ($)", min_value=0.0, value=50000.0, step=5000.0
        )
        contingency = right.number_input(
            "Contingency ($)", min_value=0.0, value=25000.0, step=1000.0
        )
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
            results = cast(dict[str, object], output["results"])
            st.markdown("##### Scenario results")
            cols = st.columns(4)
            cols[0].metric("NOI", _money(results["noi"]))
            cols[1].metric("EGI", _money(results["effective_gross_income"]))
            cols[2].metric("Value range low", _money(results["cap_rate_value_range_low"]))
            cols[3].metric("Value range high", _money(results["cap_rate_value_range_high"]))
            more = st.columns(3)
            more[0].metric("DSCR", str(results["debt_service_coverage_ratio"]))
            more[1].metric("Cash-on-cash", str(results["cash_on_cash_return"]))
            more[2].metric("Total cash basis", _money(results["total_cash_basis"]))
            with st.expander("Show full calculation details"):
                st.json(output)


def _compliance_tab() -> None:
    st.subheader("Compliance checklist")
    st.write(
        "Read this before real outreach. It is a product checklist, not legal advice. "
        "Maryland counsel should review your actual operating model."
    )
    checklist_path = Path("docs/COMPLIANCE_CHECKLIST.md")
    if checklist_path.is_file():
        st.markdown(checklist_path.read_text(encoding="utf-8"))
    else:
        st.error("Compliance checklist is unavailable.")


def main() -> None:
    st.set_page_config(
        page_title="CRE Research Pipeline",
        page_icon=":office:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
    st.title("CRE Research Pipeline")
    st.caption(
        "Local research dashboard for Prince George’s County commercial properties. "
        "No email, SMS, letter, or call is sent from this app."
    )

    settings = get_settings()
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

            _sidebar(settings.database_url, metrics)

            tabs = st.tabs(
                [
                    "Home",
                    "Properties",
                    "To review",
                    "Contacts & activity",
                    "Follow-ups",
                    "Suppressions",
                    "Call brief",
                    "Underwriting",
                    "Compliance",
                ]
            )
            with tabs[0]:
                _overview(metrics)
            with tabs[1]:
                _lead_tab(leads)
            with tabs[2]:
                _research_tab(research)
            with tabs[3]:
                _contacts_tab(contacts, activities)
            with tabs[4]:
                _follow_ups_tab(follow_ups)
            with tabs[5]:
                _suppressions_tab(suppressions)
            with tabs[6]:
                _brief_tab(session, leads)
            with tabs[7]:
                _underwriting_tab()
            with tabs[8]:
                _compliance_tab()
    except SQLAlchemyError as exc:
        st.error(
            "The database is unavailable or not migrated yet.\n\n"
            "In Terminal, run:\n"
            "1. `uv run alembic upgrade head`\n"
            "2. `uv run cre-pipeline doctor`"
        )
        st.code(type(exc).__name__)


if __name__ == "__main__":
    main()
