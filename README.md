# CRE Research Pipeline

An offline-first, compliance-minded research workflow for small commercial properties in
Prince George’s County, Maryland.

It ranks **research priority**, not distress. It does not appraise property, provide
legal/tax/investment advice, send outreach, claim buying authority, or infer seller
motivation. Every communication remains a separate human-approved action.

Required data attribution: **“Prince George’s County Planning Department.”**

## Requirements and setup

Install Python 3.12+ and
[uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
uv sync
uv run alembic upgrade head
uv run cre-pipeline doctor
```

Configuration is read from `.env`; copy `.env.example` if local overrides are needed.
SQLite defaults to `data/cre_pipeline.db`.

## CSV import

See `tests/fixtures/parcels.csv` for the canonical header. Each row requires
`source_record_id`, `address`, `owner_name`, and `retrieved_at`. The command also
requires a lawful source name and URL:

```bash
uv run cre-pipeline ingest-parcels tests/fixtures/parcels.csv \
  --source-name "Local fictional fixture" \
  --source-url "file://tests/fixtures/parcels.csv"
```

Invalid rows fail the whole import with row-level messages. Re-importing the same
`source_name` and `source_record_id` updates the record and its provenance.

## Milestone 1 pipeline

```bash
uv run cre-pipeline deduplicate
uv run cre-pipeline score
uv run cre-pipeline review-queue --output exports/entity-review-queue.csv
uv run cre-pipeline import-entity-reviews tests/fixtures/entity_reviews.csv
uv run cre-pipeline export exports/leads.xlsx
uv run cre-pipeline report
uv run cre-pipeline doctor
```

Duplicate candidates are queued, not fuzzy-merged. The entity review command only
imports a file a human already verified; it never accesses Maryland Business Express.
Open the review queue, use only the official URL already included in each row, fill the
requested fields, reviewer, review date, and evidence notes, then import that completed
CSV. Import validates the official Maryland host, stores field-level provenance, links
only exact normalized entity names, and remains idempotent. Resident agents are always
accompanied by the warning that they may not be owners or beneficial owners.

The workbook’s outreach queue is blocked pending human approval.

## Approved Prince George’s County source

Milestone 2 adds the official `Property/Property_Flattened` layer 0 adapter. It validates
the live schema before import, requests no geometry, paginates in stable `OBJECTID`
order, retries transient failures at most three times, and caches raw JSON responses for
24 hours under `.cache/arcgis/`.

```bash
uv run alembic upgrade head
uv run cre-pipeline fetch-pg-data --limit 100
uv run cre-pipeline deduplicate
uv run cre-pipeline score
uv run cre-pipeline export exports/pg-research.xlsx
```

The command fetches records only; it sends no outreach. `--limit` is bounded to 10,000
per invocation. The committed schema snapshot is
`docs/schemas/property_flattened_layer_0.json`.

## Human-controlled outreach workflow

Milestone 4 adds factual briefs and CRM controls, but still sends nothing:

```bash
# Add a sourced contact. It starts unapproved.
uv run cre-pipeline contact-add \
  --organization "Example Owner LLC" \
  --lawful-source "Manual review: official/source URL" \
  --phone "+1 301 555 0100"

# Explicit human approval is required before an outbound activity can be recorded.
uv run cre-pipeline contact-approve 1 --approved-by "Your Name"

# Record completed/manual work and an authorized follow-up.
uv run cre-pipeline activity-add 1 --activity-type call --contact-id 1 \
  --user-name "Your Name" --outcome-code conversation \
  --outcome "Asked permission to follow up" \
  --follow-up "2026-08-01T10:00:00-04:00" \
  --template-version "honest-opener-v1"
uv run cre-pipeline follow-ups

# Generate a factual Markdown brief. This does not create a call task.
uv run cre-pipeline brief 1 --caller-name "Your Name" \
  --output exports/property-1-brief.md

# Opt-out/suppression values are hashed; matching approvals are revoked.
uv run cre-pipeline suppress-contact --channel phone --value "+1 301 555 0100" \
  --reason "Recipient opted out" --source "Call note"
uv run cre-pipeline check-suppression --channel phone --value "+1 301 555 0100"
```

The system does not unsuppress contacts automatically. Correcting a suppression requires
manual database/administrator review so an opt-out is not casually reversed.

## Assumptions-based underwriting

The calculator clearly separates assumptions from verified inputs and labels all output
as not an appraisal:

```bash
uv run cre-pipeline underwrite \
  --potential-gross-income 200000 --vacancy-rate 0.05 \
  --operating-expenses 70000 --cap-rate-low 0.07 --cap-rate-high 0.09 \
  --annual-debt-service 80000 --cash-equity 500000 \
  --renovation-budget 50000 --contingency 25000
```

## Optional local dashboard

Milestone 5 provides a read-only Streamlit dashboard after the CLI pipeline is migrated:

```bash
uv sync
uv run alembic upgrade head
uv run cre-pipeline doctor
uv run cre-pipeline dashboard
```

Open `http://127.0.0.1:8501`. The launcher binds only to localhost, runs headless, and
disables Streamlit usage-stat collection.

Use the tabs left to right:
**Home → Properties → To review → Contacts & activity → Follow-ups → Suppressions →
Call brief → Underwriting → Compliance.** The sidebar explains what each screen is for.

The dashboard is read-only. It cannot add contacts, approve outreach, remove
suppressions, or send communications. Use the audited CLI commands for mutations.

## Quality checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

Tests use fictional local fixtures and temporary SQLite databases. They never depend on
live government services.

## Manual and deferred work

- Prince George’s County ArcGIS ingestion is approved and implemented. Any additional
  Planning Department or County layer requires a separate schema/terms review.
- SDAT/Business Express is manual-only because no documented public API was found and
  SDAT prohibits screen scraping/data mining. Use `review-queue --output` and
  `import-entity-reviews`; a resident agent is never assumed to be the beneficial owner.
- Code, permit, tax, vacancy, and contact sources require separate permission review.
- Additional source layers, automated outreach, and public dashboard hosting remain
  out of scope.
- No automatic email, SMS, letters, call tasks, browser automation, CAPTCHA bypass,
  proxy rotation, or authentication bypass exists.

Read `docs/PLAN.md`, `docs/DATA_SOURCES.md`, and
`docs/COMPLIANCE_CHECKLIST.md` before using real records.
