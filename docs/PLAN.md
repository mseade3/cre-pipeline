# CRE Research Pipeline Implementation Plan

Last researched: July 19, 2026

This is a research and workflow tool, not an appraisal, legal opinion, investment
recommendation, brokerage service, or claim that an owner is motivated to sell.

## Scope

The MVP imports user-provided parcel CSV files, preserves field-level provenance,
deduplicates conservatively, calculates an explainable 0–100 **research priority**,
creates human review queues, and exports a controlled Excel workbook. It is designed
for neighborhood retail, small strip centers, flex/industrial, and small warehouses in
Prince George’s County, Maryland.

Milestone 1 is offline-first. It does not scrape websites, automate outreach, infer
private financial facts, or claim that administrative status, vacancy, tax information,
property age, or violations prove seller distress.

## Architecture

1. Source adapters validate source rows into canonical Pydantic records.
2. Services write normalized SQLAlchemy entities and field provenance to SQLite.
3. Deduplication performs exact, deterministic matching and queues ambiguity.
4. Scoring reads versioned YAML and stores every component and evidence note.
5. CLI commands require explicit operator action; exports never send communications.

Adapters are replaceable and cannot bypass canonical validation. Live sources will use
bounded retries, pagination, local caching, and schema snapshots only after approval.
Structured logs redact values whose keys contain email, phone, address, token, secret,
password, or authorization.

## Data sources and licenses

- Prince George’s County Planning Department GIS Open Data Portal: official open data
  states that copying, modification, distribution, and analysis, including commercial
  use, are allowed with attribution. Required attribution:
  **“Prince George’s County Planning Department.”**
- Official `Property/Property_Flattened` ArcGIS MapServer, layer 0: metadata advertises
  a 2,000-record maximum, standardized queries, and JSON/GeoJSON/PBF. Milestone 2 is
  approved and implemented with a committed 112-field metadata snapshot, schema
  validation, bounded pagination/retries, local caching, and field-level provenance.
- User-provided CSV: accepted only with a declared lawful source URL and retrieval
  timestamp.
- Maryland Business Express/SDAT: manual lookup only in this MVP. SDAT’s usage statement
  prohibits data mining, robots, screen scraping, and similar extraction. No documented
  public entity API was found. A paid Corporate Master File route exists but its fields
  and reuse license must be confirmed before integration.

See `docs/DATA_SOURCES.md` for URLs, restrictions, and unresolved questions.

## Compliance risks and controls

- No communication is sent by this software.
- All contacts begin do-not-contact/opt-out aware and outreach approval defaults false.
- Suppression blocks outreach eligibility independent of research priority.
- Source and evidence are required for important enriched fields.
- Resident agents are stored separately and explicitly are not treated as beneficial
  owners.
- Scripts and exports must not claim licensing, capital, affiliation, buying authority,
  distress, guaranteed price, or guaranteed closing.
- Federal and Maryland calling, texting, email, privacy, and real-estate licensing
  applicability requires advice from qualified counsel.

See `docs/COMPLIANCE_CHECKLIST.md`.

## Database schema

Normalized tables cover properties, ownership, entities, signals, contacts,
opportunities, activities, suppressions, manual entity reviews, duplicate candidates,
scoring runs/components, and field provenance. Confidence is constrained to 0–1.
Source record identity is unique. Resident-agent records carry a mandatory warning.

Important field provenance stores source name, source URL, retrieval time, raw value,
normalized value, confidence, and evidence notes. Database records contain no secrets.

## Lead-scoring methodology

The score is a configurable research-priority ranking, never a distress prediction.
Default maximum positive weights total 100:

- documented buyer fit: 30
- ownership tenure: 15
- absentee ownership: 10
- evidence-backed vacancy/underutilization: 10
- permitted public-record signals: 10
- entity administrative status: 3
- data quality/freshness: 22

Unknown evidence is labeled `unknown` and contributes no signal points; it is not
converted to adverse evidence. Each score stores weight, input state, contribution,
reason, evidence reference, data coverage, and config version. Recent outreach is a
workflow penalty. Suppression blocks outreach but does not imply property condition.

## Testing strategy

Unit tests cover validation, scoring bounds and unknowns, low entity-status weight,
suppression, and deterministic duplicate detection. Integration tests use temporary
SQLite databases and local CSV fixtures. No test calls a government service. Workbook
tests inspect sheet names, filters, frozen headers, and validation rules.

## MVP milestones

1. Completed: repository, database, CSV import, deduplication, scoring, Excel export,
   tests/docs.
2. Completed: approved Planning Department ArcGIS adapter with schema snapshot,
   pagination, caching, bounded retries, provenance, and attribution.
3. Completed: manual SDAT review queue, exact-name entity linkage, provenance, and
   idempotent CSV re-import; no scraping.
4. Completed: factual briefs, human-approved contacts, activities, follow-up visibility,
   hashed suppression/opt-out controls, and assumptions-based underwriting clearly
   labeled “not an appraisal.” No communication is sent.
5. Completed: optional localhost-only, read-only Streamlit dashboard after CLI
   verification. It displays workflow state and calculates in-memory scenarios but
   cannot mutate approval/suppression records or send communications.

## Unknowns requiring human verification

- Counsel must assess TCPA, National DNC, TSR, CAN-SPAM, Maryland telephone solicitation,
  MODPA/PIPA, and real-estate licensing/compensation for the exact operating model.
- Re-verify the ArcGIS schema and source terms before changing mappings or adding layers.
- Confirm whether purchased SDAT bulk data includes current status/good-standing fields,
  update semantics, and permitted reuse.
- Confirm lawful source and permission for every imported contact.
- A licensed broker/attorney must define when research, referral, negotiation, marketing,
  or compensation becomes regulated brokerage activity.
- A human must verify buyer criteria, buying authority, capital claims, and every
  communication before use.
