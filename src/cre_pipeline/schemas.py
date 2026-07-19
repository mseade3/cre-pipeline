from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from urllib.parse import urlparse

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator


def blank_to_none(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


OptionalString = Annotated[str | None, BeforeValidator(blank_to_none)]
OptionalFloat = Annotated[float | None, BeforeValidator(blank_to_none)]
OptionalInt = Annotated[int | None, BeforeValidator(blank_to_none)]
OptionalDecimal = Annotated[Decimal | None, BeforeValidator(blank_to_none)]
OptionalDate = Annotated[date | None, BeforeValidator(blank_to_none)]
OptionalBool = Annotated[bool | None, BeforeValidator(blank_to_none)]


def normalize_text(value: str) -> str:
    return " ".join(re.sub(r"[^A-Z0-9 ]+", " ", value.upper()).split())


class ParcelImport(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_record_id: str = Field(min_length=1, max_length=160)
    parcel_id: OptionalString = None
    account_id: OptionalString = None
    address: str = Field(min_length=3, max_length=250)
    municipality: OptionalString = None
    postal_code: OptionalString = None
    latitude: OptionalFloat = None
    longitude: OptionalFloat = None
    property_type: OptionalString = None
    land_use_code: OptionalString = None
    zoning: OptionalString = None
    land_area_sqft: OptionalFloat = Field(default=None, ge=0)
    building_area_sqft: OptionalFloat = Field(default=None, ge=0)
    year_built: OptionalInt = Field(default=None, ge=1600, le=2200)
    assessed_land_value: OptionalDecimal = Field(default=None, ge=0)
    assessed_improvement_value: OptionalDecimal = Field(default=None, ge=0)
    last_sale_date: OptionalDate = None
    last_sale_price: OptionalDecimal = Field(default=None, ge=0)
    owner_name: str = Field(min_length=1, max_length=250)
    owner_type: OptionalString = None
    owner_mailing_address: OptionalString = None
    absentee_indicator: OptionalBool = None
    ownership_tenure_years: OptionalFloat = Field(default=None, ge=0)
    buyer_fit: OptionalFloat = Field(default=None, ge=0, le=1)
    vacancy_evidence: OptionalBool = None
    public_record_signal: OptionalBool = None
    entity_administrative_issue: OptionalBool = None
    retrieved_at: datetime
    confidence: float = Field(default=0.8, ge=0, le=1)
    evidence_note: OptionalString = None
    source_raw: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @field_validator("latitude")
    @classmethod
    def valid_latitude(cls, value: float | None) -> float | None:
        if value is not None and not -90 <= value <= 90:
            raise ValueError("latitude must be between -90 and 90")
        return value

    @field_validator("longitude")
    @classmethod
    def valid_longitude(cls, value: float | None) -> float | None:
        if value is not None and not -180 <= value <= 180:
            raise ValueError("longitude must be between -180 and 180")
        return value


class EntityReviewImport(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    entity_name: str = Field(min_length=1, max_length=250)
    maryland_department_id: OptionalString = None
    entity_status: OptionalString = None
    good_standing_status: OptionalString = None
    principal_office: OptionalString = None
    resident_agent: OptionalString = None
    reviewer: str = Field(min_length=1, max_length=120)
    review_date: date
    official_lookup_url: str
    evidence_notes: OptionalString = None
    verification_confidence: float = Field(default=0.9, ge=0, le=1)

    @field_validator("official_lookup_url")
    @classmethod
    def official_maryland_lookup_only(cls, value: str) -> str:
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "egov.maryland.gov"
            or not parsed.path.lower().startswith("/businessexpress/entitysearch")
        ):
            raise ValueError("official_lookup_url must use the official Maryland entity search")
        return value
