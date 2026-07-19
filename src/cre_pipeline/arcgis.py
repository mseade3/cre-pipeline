from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from cre_pipeline.schemas import ParcelImport, normalize_text

LAYER_URL = (
    "https://gis.princegeorgescountymd.gov/arcgis/rest/services/"
    "Property/Property_Flattened/MapServer/0"
)
QUERY_URL = f"{LAYER_URL}/query"
SOURCE_NAME = "Prince George's County Planning Department Property_Flattened"
ATTRIBUTION = "Prince George’s County Planning Department."

OUT_FIELDS = (
    "OBJECTID",
    "UNIQUE_ID",
    "PROPERTY_ID",
    "ACCOUNT",
    "OWNER_NAME",
    "HOUSE_NUMBER",
    "HOUSE_SUFFIX",
    "STREET_DIRECTION",
    "STREET_NAME",
    "STREET_TYPE",
    "UNIT",
    "CITY",
    "ZIP5",
    "MNCPPC_USE",
    "BPRUC",
    "ZONE_CODE1",
    "LAND_AREA_SQFT",
    "STRUCTURE_SQ_FT",
    "YEAR_BUILT",
    "FCV_LAND",
    "FCV_IMPS",
    "SALES_PRICE",
    "TRANSFER_DATE",
    "MAIL_STREET",
    "MAIL_CITY",
    "MAIL_STATE",
    "MAIL_ZIP5",
    "UPDATED_DATE",
)
REQUIRED_FIELDS = frozenset(OUT_FIELDS)
QueryValue = str | int | float | bool | None


class ArcGisSourceError(RuntimeError):
    pass


class ArcGisTransientError(ArcGisSourceError):
    pass


def _text(value: object) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _integer(value: object) -> int | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _year_built(value: object) -> int | None:
    result = _integer(value)
    if result is None or result < 1600 or result > 2200:
        return None
    return result


def _float(value: object) -> float | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _money(value: object, *, zero_is_missing: bool = False) -> Decimal | None:
    text = _text(value)
    if text is None:
        return None
    try:
        result = Decimal(text)
    except InvalidOperation:
        return None
    return None if zero_is_missing and result == 0 else result


def _date_yyyymmdd(value: object) -> date | None:
    text = _text(value)
    if text is None or len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def _join(*values: object) -> str | None:
    parts = [text for value in values if (text := _text(value))]
    return " ".join(parts) or None


def _address(attributes: Mapping[str, object]) -> str | None:
    street = _join(
        attributes.get("HOUSE_NUMBER"),
        attributes.get("HOUSE_SUFFIX"),
        attributes.get("STREET_DIRECTION"),
        attributes.get("STREET_NAME"),
        attributes.get("STREET_TYPE"),
    )
    unit = _text(attributes.get("UNIT"))
    return f"{street} UNIT {unit}" if street and unit else street


def _mailing_address(attributes: Mapping[str, object]) -> str | None:
    return _join(
        attributes.get("MAIL_STREET"),
        attributes.get("MAIL_CITY"),
        attributes.get("MAIL_STATE"),
        attributes.get("MAIL_ZIP5"),
    )


def _absentee(
    property_address: str | None,
    mailing_address: str | None,
    city: str | None,
    zip_code: str | None,
) -> bool | None:
    if property_address is None or mailing_address is None:
        return None
    full_property_address = _join(property_address, city, zip_code)
    if full_property_address is None:
        return None
    return normalize_text(full_property_address) != normalize_text(mailing_address)


def map_feature(attributes: Mapping[str, object], retrieved_at: datetime) -> ParcelImport:
    source_id = _text(attributes.get("UNIQUE_ID")) or _text(attributes.get("OBJECTID"))
    if source_id is None:
        raise ArcGisSourceError("Feature is missing UNIQUE_ID and OBJECTID.")
    address = _address(attributes)
    owner_name = _text(attributes.get("OWNER_NAME"))
    if address is None:
        raise ArcGisSourceError(f"Feature {source_id} is missing a usable property address.")
    if owner_name is None:
        raise ArcGisSourceError(f"Feature {source_id} is missing OWNER_NAME.")

    city = _text(attributes.get("CITY"))
    zip_code = _text(attributes.get("ZIP5"))
    mailing_address = _mailing_address(attributes)
    source_raw: dict[str, Any] = {
        "parcel_id": attributes.get("PROPERTY_ID"),
        "account_id": attributes.get("ACCOUNT"),
        "address": {
            key: attributes.get(key)
            for key in (
                "HOUSE_NUMBER",
                "HOUSE_SUFFIX",
                "STREET_DIRECTION",
                "STREET_NAME",
                "STREET_TYPE",
                "UNIT",
            )
        },
        "municipality": attributes.get("CITY"),
        "postal_code": attributes.get("ZIP5"),
        "property_type": attributes.get("MNCPPC_USE"),
        "land_use_code": attributes.get("BPRUC"),
        "zoning": attributes.get("ZONE_CODE1"),
        "land_area_sqft": attributes.get("LAND_AREA_SQFT"),
        "building_area_sqft": attributes.get("STRUCTURE_SQ_FT"),
        "year_built": attributes.get("YEAR_BUILT"),
        "assessed_land_value": attributes.get("FCV_LAND"),
        "assessed_improvement_value": attributes.get("FCV_IMPS"),
        "last_sale_date": attributes.get("TRANSFER_DATE"),
        "last_sale_price": attributes.get("SALES_PRICE"),
    }
    return ParcelImport(
        source_record_id=source_id,
        parcel_id=_text(attributes.get("PROPERTY_ID")),
        account_id=_text(attributes.get("ACCOUNT")),
        address=address,
        municipality=city,
        postal_code=zip_code,
        property_type=_text(attributes.get("MNCPPC_USE")),
        land_use_code=_text(attributes.get("BPRUC")),
        zoning=_text(attributes.get("ZONE_CODE1")),
        land_area_sqft=_float(attributes.get("LAND_AREA_SQFT")),
        building_area_sqft=_float(attributes.get("STRUCTURE_SQ_FT")),
        year_built=_year_built(attributes.get("YEAR_BUILT")),
        assessed_land_value=_money(attributes.get("FCV_LAND")),
        assessed_improvement_value=_money(attributes.get("FCV_IMPS")),
        last_sale_date=_date_yyyymmdd(attributes.get("TRANSFER_DATE")),
        last_sale_price=_money(attributes.get("SALES_PRICE"), zero_is_missing=True),
        owner_name=owner_name,
        owner_mailing_address=mailing_address,
        absentee_indicator=_absentee(address, mailing_address, city, zip_code),
        retrieved_at=retrieved_at,
        confidence=0.9,
        evidence_note=(
            "Official source record; values are research data, not an appraisal or "
            "evidence of seller motivation."
        ),
        source_raw=source_raw,
    )


class ArcGisPropertyAdapter:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        cache_dir: Path = Path(".cache/arcgis"),
        cache_ttl: timedelta = timedelta(hours=24),
        page_size: int = 1000,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(30),
            follow_redirects=True,
            headers={"User-Agent": "cre-pipeline/0.1 (research; human-operated)"},
        )
        self._owns_client = client is None
        self.cache_dir = cache_dir
        self.cache_ttl = cache_ttl
        self.page_size = min(max(page_size, 1), 2000)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> ArcGisPropertyAdapter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _cache_path(self, url: str, params: Mapping[str, QueryValue]) -> Path:
        encoded = json.dumps([url, sorted(params.items())], default=str, separators=(",", ":"))
        return self.cache_dir / f"{hashlib.sha256(encoded.encode()).hexdigest()}.json"

    def _request_once(self, url: str, params: Mapping[str, QueryValue]) -> dict[str, Any]:
        response = self.client.get(url, params=params)
        if response.status_code == 429 or response.status_code >= 500:
            raise ArcGisTransientError(f"Transient ArcGIS HTTP status {response.status_code}.")
        if response.is_error:
            raise ArcGisSourceError(f"ArcGIS HTTP status {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ArcGisSourceError("ArcGIS response was not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ArcGisSourceError("ArcGIS response was not a JSON object.")
        if "error" in payload:
            raise ArcGisSourceError(f"ArcGIS returned an error: {payload['error']}")
        return cast(dict[str, Any], payload)

    def _get_json(self, url: str, params: Mapping[str, QueryValue]) -> dict[str, Any]:
        cache_path = self._cache_path(url, params)
        if cache_path.is_file():
            modified = datetime.fromtimestamp(cache_path.stat().st_mtime, tz=UTC)
            if datetime.now(UTC) - modified <= self.cache_ttl:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, dict):
                    return cast(dict[str, Any], cached)

        retrying = Retrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
            retry=retry_if_exception_type((ArcGisTransientError, httpx.TransportError)),
            reraise=True,
        )
        try:
            payload = retrying(self._request_once, url, params)
        except httpx.TransportError as exc:
            raise ArcGisSourceError("ArcGIS transport failed after three attempts.") from exc
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return payload

    def metadata(self) -> dict[str, Any]:
        payload = self._get_json(LAYER_URL, {"f": "pjson"})
        fields = {
            field.get("name") for field in payload.get("fields", []) if isinstance(field, dict)
        }
        missing = REQUIRED_FIELDS - fields
        if missing:
            raise ArcGisSourceError(f"ArcGIS schema is missing required fields: {sorted(missing)}")
        max_records = payload.get("maxRecordCount")
        if not isinstance(max_records, int) or max_records < 1:
            raise ArcGisSourceError("ArcGIS metadata has no valid maxRecordCount.")
        return payload

    def records(self, limit: int) -> Iterator[ParcelImport]:
        if limit < 1:
            raise ValueError("limit must be positive")
        metadata = self.metadata()
        server_max = cast(int, metadata["maxRecordCount"])
        page_size = min(self.page_size, server_max, limit)
        offset = 0
        retrieved_at = datetime.now(UTC)
        while offset < limit:
            requested = min(page_size, limit - offset)
            params: dict[str, QueryValue] = {
                "f": "json",
                "where": "1=1",
                "outFields": ",".join(OUT_FIELDS),
                "returnGeometry": "false",
                "orderByFields": "OBJECTID",
                "resultOffset": offset,
                "resultRecordCount": requested,
            }
            payload = self._get_json(QUERY_URL, params)
            features = payload.get("features")
            if not isinstance(features, list):
                raise ArcGisSourceError("ArcGIS query response has no features array.")
            if not features:
                return
            for feature in features:
                if not isinstance(feature, dict) or not isinstance(feature.get("attributes"), dict):
                    raise ArcGisSourceError("ArcGIS feature has no attributes object.")
                yield map_feature(feature["attributes"], retrieved_at)
                offset += 1
                if offset >= limit:
                    return
            if len(features) < requested:
                return
