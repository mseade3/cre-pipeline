from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now().astimezone()


class Base(DeclarativeBase):
    pass


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    parcel_id: Mapped[str | None] = mapped_column(String(64), index=True)
    account_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source_name: Mapped[str] = mapped_column(String(120))
    source_record_id: Mapped[str] = mapped_column(String(160))
    address: Mapped[str] = mapped_column(String(250), index=True)
    address_normalized: Mapped[str] = mapped_column(String(250), index=True)
    municipality: Mapped[str | None] = mapped_column(String(120))
    postal_code: Mapped[str | None] = mapped_column(String(12))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    property_type: Mapped[str | None] = mapped_column(String(100))
    land_use_code: Mapped[str | None] = mapped_column(String(50))
    zoning: Mapped[str | None] = mapped_column(String(50))
    land_area_sqft: Mapped[float | None] = mapped_column(Float)
    building_area_sqft: Mapped[float | None] = mapped_column(Float)
    year_built: Mapped[int | None] = mapped_column(Integer)
    assessed_land_value: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    assessed_improvement_value: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    last_sale_date: Mapped[date | None] = mapped_column(Date)
    last_sale_price: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    ownerships: Mapped[list[Ownership]] = relationship(
        back_populates="property", cascade="all, delete-orphan"
    )
    signals: Mapped[list[Signal]] = relationship(
        back_populates="property", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("source_name", "source_record_id", name="uq_property_source_record"),
    )


class Ownership(Base):
    __tablename__ = "ownerships"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"))
    entity_id: Mapped[int | None] = mapped_column(ForeignKey("entities.id"), index=True)
    legal_owner_name: Mapped[str] = mapped_column(String(250))
    owner_name_normalized: Mapped[str] = mapped_column(String(250), index=True)
    owner_type: Mapped[str | None] = mapped_column(String(50))
    mailing_address: Mapped[str | None] = mapped_column(String(300))
    absentee_indicator: Mapped[bool | None] = mapped_column(Boolean)
    entity_match_confidence: Mapped[float | None] = mapped_column(Float)
    ownership_evidence: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified")
    property: Mapped[Property] = relationship(back_populates="ownerships")
    entity: Mapped[Entity | None] = relationship(back_populates="ownerships")

    __table_args__ = (
        CheckConstraint(
            "entity_match_confidence IS NULL OR "
            "(entity_match_confidence >= 0 AND entity_match_confidence <= 1)",
            name="ck_ownership_confidence",
        ),
    )


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(primary_key=True)
    legal_entity_name: Mapped[str] = mapped_column(String(250), index=True)
    maryland_department_id: Mapped[str | None] = mapped_column(String(20), unique=True)
    entity_status: Mapped[str | None] = mapped_column(String(50))
    good_standing_status: Mapped[str | None] = mapped_column(String(50))
    principal_office: Mapped[str | None] = mapped_column(String(300))
    resident_agent: Mapped[str | None] = mapped_column(String(250))
    resident_agent_warning: Mapped[str] = mapped_column(
        Text, default="Resident agent may not be the owner or beneficial owner."
    )
    verification_date: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(Text)
    ownerships: Mapped[list[Ownership]] = relationship(back_populates="entity")


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"))
    signal_type: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[str] = mapped_column(String(120))
    evidence: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str] = mapped_column(Text)
    property: Mapped[Property] = relationship(back_populates="signals")

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_signal_confidence"),
    )


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization: Mapped[str | None] = mapped_column(String(250))
    person_name: Mapped[str | None] = mapped_column(String(250))
    role: Mapped[str | None] = mapped_column(String(120))
    lawful_contact_source: Mapped[str] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(250))
    mailing_address: Mapped[str | None] = mapped_column(String(300))
    verification_state: Mapped[str] = mapped_column(String(30), default="unverified")
    opt_out_state: Mapped[str] = mapped_column(String(30), default="unknown")
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    outreach_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    outreach_approved_by: Mapped[str | None] = mapped_column(String(120))
    outreach_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    stage: Mapped[str] = mapped_column(String(50), default="research")
    asking_price: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    seller_motivation_verbatim: Mapped[str | None] = mapped_column(Text)
    timeline: Mapped[str | None] = mapped_column(String(120))
    occupancy: Mapped[str | None] = mapped_column(String(120))
    known_noi: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    debt_information_voluntary: Mapped[str | None] = mapped_column(Text)
    estimated_capital_needs: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    buyer_criteria_match: Mapped[float | None] = mapped_column(Float)
    underwriting_assumptions: Mapped[dict[str, object] | None] = mapped_column(JSON)
    next_action: Mapped[str | None] = mapped_column(Text)


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    activity_type: Mapped[str] = mapped_column(String(30))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    outcome_code: Mapped[str | None] = mapped_column(String(40))
    outcome: Mapped[str | None] = mapped_column(Text)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_name: Mapped[str] = mapped_column(String(120))
    template_version: Mapped[str | None] = mapped_column(String(80))


class Suppression(Base):
    __tablename__ = "suppressions"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(30))
    normalized_value_hash: Mapped[str] = mapped_column(String(64), index=True)
    reason: Mapped[str] = mapped_column(String(120))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        UniqueConstraint("channel", "normalized_value_hash", name="uq_suppression_channel_value"),
    )


class ManualEntityReview(Base):
    __tablename__ = "manual_entity_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_name: Mapped[str] = mapped_column(String(250))
    official_lookup_url: Mapped[str] = mapped_column(Text)
    requested_fields: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(String(120))
    review_date: Mapped[date | None] = mapped_column(Date)
    evidence_notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending")


class DuplicateCandidate(Base):
    __tablename__ = "duplicate_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id_a: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    property_id_b: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    match_rule: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    details: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("property_id_a", "property_id_b", "match_rule", name="uq_duplicate_pair"),
    )


class FieldProvenance(Base):
    __tablename__ = "field_provenance"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_type: Mapped[str] = mapped_column(String(60), index=True)
    record_id: Mapped[int] = mapped_column(Integer, index=True)
    field_name: Mapped[str] = mapped_column(String(100))
    source_name: Mapped[str] = mapped_column(String(120))
    source_url: Mapped[str] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_value: Mapped[str | None] = mapped_column(Text)
    normalized_value: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    evidence_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_provenance_confidence"),
        UniqueConstraint(
            "record_type",
            "record_id",
            "field_name",
            "source_name",
            name="uq_provenance_field_source",
        ),
    )


class ScoringRun(Base):
    __tablename__ = "scoring_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    data_coverage: Mapped[float] = mapped_column(Float)
    outreach_eligible: Mapped[bool] = mapped_column(Boolean)
    config_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    components: Mapped[list[ScoreComponent]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 100", name="ck_score_range"),
        CheckConstraint("data_coverage >= 0 AND data_coverage <= 1", name="ck_coverage_range"),
    )


class ScoreComponent(Base):
    __tablename__ = "score_components"

    id: Mapped[int] = mapped_column(primary_key=True)
    scoring_run_id: Mapped[int] = mapped_column(ForeignKey("scoring_runs.id", ondelete="CASCADE"))
    component: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(30))
    weight: Mapped[float] = mapped_column(Float)
    contribution: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    evidence_reference: Mapped[str | None] = mapped_column(Text)
    run: Mapped[ScoringRun] = relationship(back_populates="components")
