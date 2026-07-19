# Data Sources

Verified July 19, 2026. URLs and schemas can change; retrieval metadata must be stored
with each import. This document records observations, not legal conclusions.

## Prince George’s County Planning Department

Required attribution: **“Prince George’s County Planning Department.”**

- Open Data Portal and use constraints:
  https://gisdata.pgplanning.org/opendata/
- GIS metadata catalog:
  https://gisdata.pgplanning.org/metadata/
- Planning Department maps and REST links:
  https://pgplanning.org/data-tools/maps/
- Property service directory:
  https://gis.princegeorgescountymd.gov/arcgis/rest/services/Property
- Property Flattened layer metadata:
  https://gis.princegeorgescountymd.gov/arcgis/rest/services/Property/Property_Flattened/MapServer/layers
- Layer query base (not called in Milestone 1):
  https://gis.princegeorgescountymd.gov/arcgis/rest/services/Property/Property_Flattened/MapServer/0/query

Verified metadata for layer 0 includes 112 fields, a 2,000-record maximum, standardized
queries, advanced queries/statistics, and JSON, GeoJSON, and PBF formats. The exact
metadata retrieved July 19, 2026 is stored at
`docs/schemas/property_flattened_layer_0.json` (SHA-256
`9ce7e5acdca46769669bf5d2167c70860538068a1b6de1b223d900d925414c08`).

The approved adapter maps only verified fields: `UNIQUE_ID`, `OBJECTID`, `PROPERTY_ID`,
`ACCOUNT`, `OWNER_NAME`, property-address components, mailing-address components,
`CITY`, `ZIP5`, `MNCPPC_USE`, `BPRUC`, `ZONE_CODE1`, `LAND_AREA_SQFT`,
`STRUCTURE_SQ_FT`, `YEAR_BUILT`, `FCV_LAND`, `FCV_IMPS`, `SALES_PRICE`,
`TRANSFER_DATE`, and `UPDATED_DATE`. `STRUCTURE_SQ_FT`, `YEAR_BUILT`, and
`TRANSFER_DATE` are strings in the source schema and are parsed conservatively.

Requests use `where=1=1`, the explicit field allowlist, `returnGeometry=false`, stable
`OBJECTID` ordering, and `resultOffset`/`resultRecordCount` pagination. Page size never
exceeds the advertised server maximum. Transient HTTP/transport failures receive at
most three attempts with exponential waiting. Raw JSON is cached locally for 24 hours.
Each invocation is bounded to 10,000 records. Cache files are excluded from Git.

The service returned HTTP 200 for metadata and count queries on July 19, 2026; the
count response was 353,063. This count is operational metadata, not a claim about the
number of qualified commercial properties.

The official portal also listed `Property_Flattened_Py.zip` as FGDB and shapefile
downloads on July 19, 2026. Bulk files are preferred when they avoid unnecessary
requests. The portal says data may be modified or deleted, makes no warranties, and
requires Planning Department attribution.

## User-provided CSV

Milestone 1 accepts a documented CSV source. Each import requires:

- source name
- source URL (a file URI is acceptable for an internal/manual file)
- retrieval timestamp
- raw values and normalized values
- confidence and optional evidence notes

Contact data should not be imported unless its collection and intended use are lawful.

## Maryland Business Express / SDAT

- Official manual entity lookup:
  https://egov.maryland.gov/BusinessExpress/EntitySearch
- SDAT services and paid public-release files:
  https://dat.maryland.gov/pages/services.aspx
- SDAT website usage statement:
  https://dat.maryland.gov/about/pages/website-usage-statements.aspx

No documented public API for entity status, good standing, principal office, or resident
agent was found. SDAT’s usage statement says data mining, robots, screen scraping, and
similar extraction tools may not be used. This project therefore does not automate or
scrape the portal.

The approved workflow is a manual-review queue followed by CSV import. The reviewer
records entity name, official lookup URL, requested fields, reviewer, review date, and
evidence notes. A resident agent is a service-of-process contact and may be unrelated to
the beneficial owner; the application preserves this warning.

Milestone 3 implements this as:

```bash
uv run cre-pipeline review-queue --output exports/entity-review-queue.csv
# A human completes the CSV using its official lookup URLs.
uv run cre-pipeline import-entity-reviews exports/entity-review-queue.csv
```

The importer accepts only HTTPS URLs on `egov.maryland.gov` under the official
`/BusinessExpress/EntitySearch` path. It stores raw and normalized values, source URL,
manual review date, confidence, reviewer evidence notes, and the resident-agent warning.
It links an entity to ownership only when normalized legal names match exactly; no fuzzy
ownership inference is performed. Re-importing the same reviewed row updates rather
than duplicating its entity, completed queue item, or provenance.

SDAT documents a paid Corporate Master File through SpecPrint. Before using it, confirm
in writing the exact fields (especially status/good standing), update semantics, price,
delivery format, and rights for storage, enrichment, export, and commercial use.

## Deferred sources

Code, permits, tax, vacancy, and contact enrichment are not enabled in Milestone 1.
Each future source requires an official download, documented government REST service,
user-provided file, or licensed API plus a recorded schema and terms review. Browser
automation is prohibited unless permission is clearly established.
