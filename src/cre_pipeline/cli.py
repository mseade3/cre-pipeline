from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, cast

import typer
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from cre_pipeline import ATTRIBUTION
from cre_pipeline.adapters import CsvValidationError
from cre_pipeline.arcgis import (
    LAYER_URL,
    SOURCE_NAME,
    ArcGisPropertyAdapter,
    ArcGisSourceError,
)
from cre_pipeline.config import get_settings
from cre_pipeline.db import create_db_engine
from cre_pipeline.outreach import (
    Channel,
    OutreachControlError,
    add_activity,
    add_suppression,
    approve_contact,
    create_contact,
    follow_up_queue,
    generate_property_brief,
    is_suppressed,
    write_property_brief,
)
from cre_pipeline.services import (
    create_pending_entity_reviews,
    export_entity_review_queue,
    export_workbook,
    find_duplicate_candidates,
    import_entity_reviews,
    ingest_parcels,
    ingest_records,
    report_metrics,
    score_all,
)
from cre_pipeline.underwriting import (
    UnderwritingAssumptions,
    UnderwritingError,
    calculate_underwriting,
)

app = typer.Typer(
    no_args_is_help=True,
    help="Human-approved commercial-property research workflow. No outreach is sent.",
)


def _channel(value: str) -> Channel:
    if value not in {"email", "phone", "mailing"}:
        raise typer.BadParameter("channel must be email, phone, or mailing")
    return cast(Channel, value)


def _optional_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise typer.BadParameter("datetime must include a UTC offset")
    return parsed.astimezone(UTC)


def _decimal(value: str, name: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise typer.BadParameter(f"{name} must be a decimal number") from exc


@app.command("fetch-pg-data")
def fetch_pg_data(
    limit: Annotated[
        int,
        typer.Option(min=1, max=10_000, help="Maximum records to retrieve (1-10,000)."),
    ] = 100,
) -> None:
    """Fetch approved official Property_Flattened records with caching and retries."""
    engine = create_db_engine(get_settings())
    try:
        with ArcGisPropertyAdapter() as adapter, Session(engine) as session, session.begin():
            result = ingest_records(
                session,
                adapter.records(limit),
                source_name=SOURCE_NAME,
                source_url=LAYER_URL,
            )
    except ArcGisSourceError as exc:
        typer.echo(f"source_error={exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"inserted={result.inserted} updated={result.updated} attribution={ATTRIBUTION}")


@app.command("ingest-parcels")
def ingest_parcels_command(
    input_csv: Annotated[Path, typer.Argument(exists=True, readable=True)],
    source_name: Annotated[str, typer.Option(help="Human-readable lawful source name.")],
    source_url: Annotated[str, typer.Option(help="Source URL or file URI for provenance.")],
) -> None:
    """Validate and idempotently import a documented parcel CSV."""
    engine = create_db_engine(get_settings())
    try:
        with Session(engine) as session, session.begin():
            result = ingest_parcels(session, input_csv, source_name, source_url)
    except CsvValidationError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"inserted={result.inserted} updated={result.updated}")


@app.command("import-entity-reviews")
def import_entity_reviews_command(
    reviews_csv: Annotated[Path, typer.Argument(exists=True, readable=True)],
) -> None:
    """Import records that a human verified in the official entity lookup."""
    engine = create_db_engine(get_settings())
    try:
        with Session(engine) as session, session.begin():
            result = import_entity_reviews(session, reviews_csv)
    except CsvValidationError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"inserted={result.inserted} updated={result.updated}")


@app.command()
def deduplicate() -> None:
    """Queue deterministic duplicate candidates; never fuzzy-auto-merge."""
    engine = create_db_engine(get_settings())
    with Session(engine) as session, session.begin():
        count = find_duplicate_candidates(session)
    typer.echo(f"duplicate_candidates={count}")


@app.command()
def score() -> None:
    """Calculate and persist explainable research priorities."""
    settings = get_settings()
    engine = create_db_engine(settings)
    with Session(engine) as session, session.begin():
        count = score_all(session, settings.scoring_config)
    typer.echo(f"properties_scored={count}")


@app.command("review-queue")
def review_queue(
    output: Annotated[
        Path | None,
        typer.Option(help="Optional CSV template for manual SDAT review."),
    ] = None,
) -> None:
    """Create missing manual SDAT reviews without accessing SDAT."""
    engine = create_db_engine(get_settings())
    with Session(engine) as session, session.begin():
        created = create_pending_entity_reviews(session)
        exported = export_entity_review_queue(session, output) if output else None
        metrics = report_metrics(session)
    typer.echo(f"entity_reviews_created={created}")
    if output is not None:
        typer.echo(f"entity_reviews_exported={exported} review_file={output}")
    typer.echo(json.dumps(metrics, indent=2, sort_keys=True))


@app.command("export")
def export_command(
    output: Annotated[Path, typer.Argument(help="Destination .xlsx path.")],
) -> None:
    """Generate a neutral, approval-blocked research workbook."""
    if output.suffix.lower() != ".xlsx":
        raise typer.BadParameter("output must use the .xlsx extension")
    engine = create_db_engine(get_settings())
    with Session(engine) as session:
        export_workbook(session, output)
    typer.echo(f"workbook={output}")


@app.command()
def report() -> None:
    """Report research quality and workflow metrics."""
    engine = create_db_engine(get_settings())
    with Session(engine) as session:
        typer.echo(json.dumps(report_metrics(session), indent=2, sort_keys=True))


@app.command("contact-add")
def contact_add(
    lawful_source: Annotated[str, typer.Option(help="Lawful source URL or evidence note.")],
    organization: Annotated[str | None, typer.Option()] = None,
    person_name: Annotated[str | None, typer.Option()] = None,
    role: Annotated[str | None, typer.Option()] = None,
    phone: Annotated[str | None, typer.Option()] = None,
    email: Annotated[str | None, typer.Option()] = None,
    mailing_address: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Add a contact in an unapproved state; this sends nothing."""
    engine = create_db_engine(get_settings())
    try:
        with Session(engine) as session, session.begin():
            contact = create_contact(
                session,
                organization=organization,
                person_name=person_name,
                role=role,
                lawful_contact_source=lawful_source,
                phone=phone,
                email=email,
                mailing_address=mailing_address,
            )
            contact_id = contact.id
    except OutreachControlError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"contact_id={contact_id} outreach_approved=false")


@app.command("contact-approve")
def contact_approve(
    contact_id: Annotated[int, typer.Argument(min=1)],
    approved_by: Annotated[str, typer.Option(help="Human approver's name.")],
) -> None:
    """Record explicit human approval after suppression and opt-out checks."""
    engine = create_db_engine(get_settings())
    try:
        with Session(engine) as session, session.begin():
            contact = approve_contact(session, contact_id, approved_by)
            approved_at = contact.outreach_approved_at
    except OutreachControlError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"contact_id={contact_id} approved_at={approved_at}")


@app.command("suppress-contact")
def suppress_contact(
    channel: Annotated[str, typer.Option(help="email, phone, or mailing")],
    value: Annotated[str, typer.Option(help="Value is hashed and not stored in suppression.")],
    reason: Annotated[str, typer.Option()],
    source: Annotated[str, typer.Option(help="Who or what supplied the suppression.")],
    opt_out: Annotated[bool, typer.Option(help="Mark matching contacts opted out.")] = True,
) -> None:
    """Add or refresh a suppression and revoke matching approvals."""
    engine = create_db_engine(get_settings())
    try:
        with Session(engine) as session, session.begin():
            suppression = add_suppression(
                session,
                channel=_channel(channel),
                value=value,
                reason=reason,
                source=source,
                is_opt_out=opt_out,
            )
            suppression_id = suppression.id
    except OutreachControlError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"suppression_id={suppression_id} active=true")


@app.command("check-suppression")
def check_suppression(
    channel: Annotated[str, typer.Option(help="email, phone, or mailing")],
    value: Annotated[str, typer.Option()],
) -> None:
    """Check a contact value without displaying or storing the raw value."""
    engine = create_db_engine(get_settings())
    try:
        with Session(engine) as session:
            blocked = is_suppressed(session, _channel(channel), value)
    except OutreachControlError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"suppressed={str(blocked).lower()}")


@app.command("activity-add")
def activity_add(
    property_id: Annotated[int, typer.Argument(min=1)],
    activity_type: Annotated[
        str, typer.Option(help="call, email, letter, meeting, research, or note")
    ],
    user_name: Annotated[str, typer.Option()],
    contact_id: Annotated[int | None, typer.Option(min=1)] = None,
    outcome_code: Annotated[
        str | None,
        typer.Option(
            help=(
                "attempted, conversation, decision_maker_reached, follow_up, "
                "seller_stated_interest, referred_to_partner, offer, closed, "
                "no_answer, not_interested, or opted_out"
            )
        ),
    ] = None,
    outcome: Annotated[str | None, typer.Option()] = None,
    follow_up: Annotated[
        str | None, typer.Option(help="ISO-8601 datetime with UTC offset.")
    ] = None,
    template_version: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Record an activity; outbound types require prior human contact approval."""
    engine = create_db_engine(get_settings())
    try:
        with Session(engine) as session, session.begin():
            activity = add_activity(
                session,
                property_id=property_id,
                contact_id=contact_id,
                activity_type=activity_type,
                outcome_code=outcome_code,
                outcome=outcome,
                follow_up_at=_optional_datetime(follow_up),
                user_name=user_name,
                template_version=template_version,
            )
            activity_id = activity.id
    except OutreachControlError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"activity_id={activity_id}")


@app.command("follow-ups")
def follow_ups() -> None:
    """List follow-ups; this does not create or send call/email tasks."""
    engine = create_db_engine(get_settings())
    with Session(engine) as session:
        rows = [asdict(item) for item in follow_up_queue(session)]
    typer.echo(json.dumps(rows, indent=2, default=str))


@app.command()
def brief(
    property_id: Annotated[int, typer.Argument(min=1)],
    caller_name: Annotated[str, typer.Option(help="Truthful caller name for the opener.")],
    output: Annotated[Path | None, typer.Option(help="Optional Markdown destination.")] = None,
) -> None:
    """Generate a factual property brief and permission-based discovery script."""
    engine = create_db_engine(get_settings())
    try:
        with Session(engine) as session:
            if output is None:
                typer.echo(generate_property_brief(session, property_id, caller_name))
            else:
                write_property_brief(session, property_id, caller_name, output)
    except OutreachControlError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if output is not None:
        typer.echo(f"brief={output}")


@app.command()
def underwrite(
    potential_gross_income: Annotated[str, typer.Option()],
    vacancy_rate: Annotated[str, typer.Option(help="Decimal fraction, e.g. 0.05.")],
    operating_expenses: Annotated[str, typer.Option()],
    cap_rate_low: Annotated[str, typer.Option(help="Decimal fraction, e.g. 0.07.")],
    cap_rate_high: Annotated[str, typer.Option(help="Decimal fraction, e.g. 0.09.")],
    annual_debt_service: Annotated[str, typer.Option()],
    cash_equity: Annotated[str, typer.Option()],
    renovation_budget: Annotated[str, typer.Option()] = "0",
    contingency: Annotated[str, typer.Option()] = "0",
) -> None:
    """Run a transparent assumptions-only scenario; output is not an appraisal."""
    assumptions = UnderwritingAssumptions(
        potential_gross_income=_decimal(potential_gross_income, "potential_gross_income"),
        vacancy_rate=_decimal(vacancy_rate, "vacancy_rate"),
        operating_expenses=_decimal(operating_expenses, "operating_expenses"),
        cap_rate_low=_decimal(cap_rate_low, "cap_rate_low"),
        cap_rate_high=_decimal(cap_rate_high, "cap_rate_high"),
        annual_debt_service=_decimal(annual_debt_service, "annual_debt_service"),
        cash_equity=_decimal(cash_equity, "cash_equity"),
        renovation_budget=_decimal(renovation_budget, "renovation_budget"),
        contingency=_decimal(contingency, "contingency"),
    )
    try:
        result = calculate_underwriting(assumptions)
    except UnderwritingError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(result.as_dict(assumptions), indent=2))


@app.command()
def dashboard(
    port: Annotated[int, typer.Option(min=1024, max=65535)] = 8501,
) -> None:
    """Launch the optional read-only dashboard on localhost."""
    dashboard_path = Path(__file__).with_name("dashboard.py")
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(dashboard_path),
        "--server.address",
        "127.0.0.1",
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    typer.echo(f"dashboard=http://127.0.0.1:{port}")
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        raise typer.Exit(exc.returncode) from exc


@app.command()
def doctor() -> None:
    """Check configuration, database, migration, attribution, and deferred sources."""
    settings = get_settings()
    checks: dict[str, dict[str, str]] = {}
    engine = create_db_engine(settings)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            current = MigrationContext.configure(connection).get_current_revision()
        script = ScriptDirectory.from_config(Config("alembic.ini"))
        expected = script.get_current_head()
        checks["database"] = {"status": "ok", "detail": "connection successful"}
        checks["migrations"] = {
            "status": "ok" if current == expected else "error",
            "detail": f"current={current} expected={expected}",
        }
    except SQLAlchemyError as exc:
        checks["database"] = {"status": "error", "detail": type(exc).__name__}
        checks["migrations"] = {"status": "error", "detail": "database unavailable"}

    docs = Path("docs/PLAN.md").read_text(encoding="utf-8") + Path(
        "docs/DATA_SOURCES.md"
    ).read_text(encoding="utf-8")
    checks["attribution"] = {
        "status": "ok" if ATTRIBUTION in docs else "error",
        "detail": ATTRIBUTION,
    }
    checks["scoring_config"] = {
        "status": "ok" if settings.scoring_config.is_file() else "error",
        "detail": str(settings.scoring_config),
    }
    checks["writable_paths"] = {
        "status": "ok" if os.access(Path("."), os.W_OK) else "error",
        "detail": str(Path.cwd()),
    }
    dashboard_path = Path(__file__).with_name("dashboard.py")
    try:
        import streamlit

        checks["dashboard"] = {
            "status": "ok" if dashboard_path.is_file() else "error",
            "detail": (
                f"streamlit={streamlit.__version__}; "
                f"localhost-only read-only UI at {dashboard_path.name}"
            ),
        }
    except ImportError:
        checks["dashboard"] = {
            "status": "error",
            "detail": "streamlit is not installed; run uv sync",
        }
    try:
        with ArcGisPropertyAdapter(cache_ttl=timedelta(0)) as adapter:
            metadata = adapter.metadata()
        checks["source_availability"] = {
            "status": "ok",
            "detail": (
                f"Property_Flattened layer={metadata.get('id')} "
                f"maxRecordCount={metadata.get('maxRecordCount')}"
            ),
        }
    except (ArcGisSourceError, OSError) as exc:
        checks["source_availability"] = {
            "status": "error",
            "detail": type(exc).__name__,
        }
    typer.echo(json.dumps(checks, indent=2, sort_keys=True))
    if any(check["status"] == "error" for check in checks.values()):
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
