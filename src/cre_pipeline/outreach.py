from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from cre_pipeline.models import (
    Activity,
    Contact,
    FieldProvenance,
    Opportunity,
    Ownership,
    Property,
    ScoringRun,
    Suppression,
)
from cre_pipeline.schemas import normalize_text

Channel = Literal["email", "phone", "mailing"]
OUTBOUND_ACTIVITY_TYPES = {"call", "email", "letter"}
ACTIVITY_TYPES = OUTBOUND_ACTIVITY_TYPES | {"meeting", "research", "note"}
OUTCOME_CODES = {
    "attempted",
    "conversation",
    "decision_maker_reached",
    "follow_up",
    "seller_stated_interest",
    "referred_to_partner",
    "offer",
    "closed",
    "no_answer",
    "not_interested",
    "opted_out",
}

DISCOVERY_QUESTIONS = (
    "How is the property operating today?",
    "What are your plans for it over the next few years?",
    (
        "Are there any vacancy, management, maintenance, or capital-project issues "
        "you would want a buyer to understand?"
    ),
    "If you ever considered a sale, what timing and terms would matter most?",
    "Would you prefer a direct conversation with a verified buyer or licensed broker?",
    "Who is the appropriate decision-maker for future communication?",
)


class OutreachControlError(ValueError):
    pass


@dataclass(frozen=True)
class FollowUp:
    activity_id: int
    property_id: int | None
    contact_id: int | None
    activity_type: str
    outcome_code: str | None
    outcome: str | None
    follow_up_at: datetime
    user_name: str
    outreach_approved: bool
    do_not_contact: bool


def canonical_contact_value(channel: Channel, value: str) -> str:
    if channel == "email":
        return value.strip().casefold()
    if channel == "phone":
        digits = re.sub(r"\D", "", value)
        return digits[1:] if len(digits) == 11 and digits.startswith("1") else digits
    return normalize_text(value)


def contact_value_hash(channel: Channel, value: str) -> str:
    canonical = canonical_contact_value(channel, value)
    if not canonical:
        raise OutreachControlError("Contact value is empty after normalization.")
    return hashlib.sha256(f"{channel}:{canonical}".encode()).hexdigest()


def create_contact(
    session: Session,
    *,
    organization: str | None,
    person_name: str | None,
    role: str | None,
    lawful_contact_source: str,
    phone: str | None = None,
    email: str | None = None,
    mailing_address: str | None = None,
) -> Contact:
    if not organization and not person_name:
        raise OutreachControlError("An organization or person name is required.")
    if not lawful_contact_source.strip():
        raise OutreachControlError("A lawful contact source is required.")
    if not any((phone, email, mailing_address)):
        raise OutreachControlError("At least one contact channel is required.")
    contact = Contact(
        organization=organization,
        person_name=person_name,
        role=role,
        lawful_contact_source=lawful_contact_source,
        phone=phone,
        email=email,
        mailing_address=mailing_address,
        verification_state="unverified",
        opt_out_state="unknown",
        do_not_contact=False,
        outreach_approved=False,
    )
    session.add(contact)
    session.flush()
    return contact


def _channel_value(contact: Contact, channel: Channel) -> str | None:
    if channel == "phone":
        return contact.phone
    if channel == "email":
        return contact.email
    return contact.mailing_address


def add_suppression(
    session: Session,
    *,
    channel: Channel,
    value: str,
    reason: str,
    source: str,
    is_opt_out: bool,
) -> Suppression:
    hashed = contact_value_hash(channel, value)
    suppression = session.scalar(
        select(Suppression).where(
            Suppression.channel == channel,
            Suppression.normalized_value_hash == hashed,
        )
    )
    if suppression is None:
        suppression = Suppression(
            channel=channel,
            normalized_value_hash=hashed,
            reason=reason,
            requested_at=datetime.now(UTC),
            source=source,
            active=True,
        )
        session.add(suppression)
    else:
        suppression.reason = reason
        suppression.requested_at = datetime.now(UTC)
        suppression.source = source
        suppression.active = True

    for contact in session.scalars(select(Contact)).all():
        contact_value = _channel_value(contact, channel)
        if contact_value and contact_value_hash(channel, contact_value) == hashed:
            contact.do_not_contact = True
            contact.outreach_approved = False
            contact.outreach_approved_by = None
            contact.outreach_approved_at = None
            if is_opt_out:
                contact.opt_out_state = "opted_out"
    return suppression


def is_suppressed(session: Session, channel: Channel, value: str) -> bool:
    hashed = contact_value_hash(channel, value)
    return (
        session.scalar(
            select(Suppression.id).where(
                Suppression.channel == channel,
                Suppression.normalized_value_hash == hashed,
                Suppression.active.is_(True),
            )
        )
        is not None
    )


def approve_contact(session: Session, contact_id: int, approved_by: str) -> Contact:
    contact = session.get(Contact, contact_id)
    if contact is None:
        raise OutreachControlError(f"Contact {contact_id} does not exist.")
    if contact.do_not_contact or contact.opt_out_state == "opted_out":
        raise OutreachControlError("Contact is opted out or marked do-not-contact.")
    channel_values: tuple[tuple[Channel, str | None], ...] = (
        ("phone", contact.phone),
        ("email", contact.email),
        ("mailing", contact.mailing_address),
    )
    blocked_channels = [
        channel
        for channel, value in channel_values
        if value is not None and is_suppressed(session, channel, value)
    ]
    if blocked_channels:
        raise OutreachControlError(
            f"Contact has active suppression for: {', '.join(blocked_channels)}."
        )
    if not approved_by.strip():
        raise OutreachControlError("Approver name is required.")
    contact.outreach_approved = True
    contact.outreach_approved_by = approved_by
    contact.outreach_approved_at = datetime.now(UTC)
    return contact


def add_activity(
    session: Session,
    *,
    property_id: int,
    activity_type: str,
    user_name: str,
    outcome_code: str | None = None,
    outcome: str | None = None,
    follow_up_at: datetime | None = None,
    contact_id: int | None = None,
    template_version: str | None = None,
) -> Activity:
    if activity_type not in ACTIVITY_TYPES:
        raise OutreachControlError(f"Unsupported activity type: {activity_type}.")
    if outcome_code is not None and outcome_code not in OUTCOME_CODES:
        raise OutreachControlError(f"Unsupported outcome code: {outcome_code}.")
    if session.get(Property, property_id) is None:
        raise OutreachControlError(f"Property {property_id} does not exist.")
    contact = session.get(Contact, contact_id) if contact_id is not None else None
    if contact_id is not None and contact is None:
        raise OutreachControlError(f"Contact {contact_id} does not exist.")
    if activity_type in OUTBOUND_ACTIVITY_TYPES:
        if contact is None:
            raise OutreachControlError("Outbound activity requires a contact.")
        if not contact.outreach_approved or contact.do_not_contact:
            raise OutreachControlError(
                "Human approval is required and contact must not be suppressed."
            )
    activity = Activity(
        property_id=property_id,
        contact_id=contact_id,
        activity_type=activity_type,
        outcome_code=outcome_code,
        outcome=outcome,
        follow_up_at=follow_up_at,
        user_name=user_name,
        template_version=template_version,
    )
    session.add(activity)
    session.flush()
    if contact is not None and activity_type in OUTBOUND_ACTIVITY_TYPES:
        contact.last_contact_at = activity.occurred_at
        contact.next_action_at = follow_up_at
    return activity


def follow_up_queue(session: Session) -> list[FollowUp]:
    rows = session.execute(
        select(Activity, Contact)
        .outerjoin(Contact, Contact.id == Activity.contact_id)
        .where(Activity.follow_up_at.is_not(None))
        .order_by(Activity.follow_up_at, Activity.id)
    ).all()
    return [
        FollowUp(
            activity_id=activity.id,
            property_id=activity.property_id,
            contact_id=activity.contact_id,
            activity_type=activity.activity_type,
            outcome_code=activity.outcome_code,
            outcome=activity.outcome,
            follow_up_at=activity.follow_up_at,
            user_name=activity.user_name,
            outreach_approved=contact.outreach_approved if contact else False,
            do_not_contact=contact.do_not_contact if contact else False,
        )
        for activity, contact in rows
        if activity.follow_up_at is not None
    ]


def _display(value: object | None, suffix: str = "") -> str:
    return "Unknown" if value is None or value == "" else f"{value}{suffix}"


def generate_property_brief(session: Session, property_id: int, caller_name: str) -> str:
    property_record = session.scalar(
        select(Property)
        .where(Property.id == property_id)
        .options(selectinload(Property.ownerships), selectinload(Property.signals))
    )
    if property_record is None:
        raise OutreachControlError(f"Property {property_id} does not exist.")
    ownership: Ownership | None = (
        property_record.ownerships[0] if property_record.ownerships else None
    )
    score = session.scalar(
        select(ScoringRun)
        .where(ScoringRun.property_id == property_id)
        .order_by(ScoringRun.created_at.desc())
    )
    provenance = session.scalars(
        select(FieldProvenance)
        .where(
            FieldProvenance.record_type == "property",
            FieldProvenance.record_id == property_id,
        )
        .order_by(FieldProvenance.field_name)
    ).all()
    sources = sorted({f"{item.source_name}: {item.source_url}" for item in provenance})
    opportunities = session.scalars(
        select(Opportunity).where(Opportunity.property_id == property_id)
    ).all()
    activities = session.scalars(
        select(Activity)
        .where(Activity.property_id == property_id)
        .order_by(Activity.occurred_at.desc())
    ).all()

    facts = {
        "Address": property_record.address,
        "Parcel ID": property_record.parcel_id,
        "Account ID": property_record.account_id,
        "Property type/use": property_record.property_type,
        "Land-use code": property_record.land_use_code,
        "Zoning": property_record.zoning,
        "Land area": (
            f"{property_record.land_area_sqft:,.0f} sq ft"
            if property_record.land_area_sqft is not None
            else None
        ),
        "Building area": (
            f"{property_record.building_area_sqft:,.0f} sq ft"
            if property_record.building_area_sqft is not None
            else None
        ),
        "Year built": property_record.year_built,
        "Assessed land value": (
            f"${property_record.assessed_land_value:,.0f}"
            if property_record.assessed_land_value is not None
            else None
        ),
        "Assessed improvement value": (
            f"${property_record.assessed_improvement_value:,.0f}"
            if property_record.assessed_improvement_value is not None
            else None
        ),
        "Last recorded sale date": property_record.last_sale_date,
        "Last recorded sale price": (
            f"${property_record.last_sale_price:,.0f}"
            if property_record.last_sale_price is not None
            else None
        ),
    }
    missing = [name for name, value in facts.items() if value is None]
    missing_text = (
        ", ".join(missing)
        if missing
        else (
            "No core property fields are missing; source accuracy still requires "
            "human verification."
        )
    )
    seller_statements = [
        item.seller_motivation_verbatim for item in opportunities if item.seller_motivation_verbatim
    ]
    signal_lines = [
        (
            f"- **{signal.signal_type}:** {signal.value}; confidence "
            f"{signal.confidence:.0%}. Evidence: {_display(signal.evidence)}"
        )
        for signal in property_record.signals
    ] or ["- No research signals recorded. Missing data is not adverse evidence."]
    activity_lines = [
        (
            f"- {item.occurred_at.isoformat()} — {item.activity_type}: "
            f"{_display(item.outcome_code)} / {_display(item.outcome)}; "
            f"follow-up {_display(item.follow_up_at)}"
        )
        for item in activities[:5]
    ] or ["- No activities recorded."]
    source_lines = [f"- {source}" for source in sources] or ["- Source metadata unavailable."]
    fact_lines = [f"- **{name}:** {_display(value)}" for name, value in facts.items()]
    question_lines = [
        f"{index}. {question}" for index, question in enumerate(DISCOVERY_QUESTIONS, 1)
    ]
    owner_name = ownership.legal_owner_name if ownership else "Unknown"
    owner_status = ownership.verification_status if ownership else "missing"
    seller_statement_text = (
        "\n".join(f"- “{statement}”" for statement in seller_statements)
        if seller_statements
        else "- None recorded. Do not infer motivation."
    )
    score_text = (
        f"{score.score:.1f}/100 with {score.data_coverage:.0%} evidence coverage"
        if score
        else "Not scored"
    )
    next_action = activities[0].follow_up_at if activities else None
    return f"""# Property Research Brief — {property_record.address}

**Generated:** {datetime.now(UTC).isoformat()}  
**Research priority:** {score_text}  
**Important:** Research workflow only. Not an appraisal, legal opinion, investment advice,
or evidence that an owner wants or needs to sell.

## Verified/source-reported property facts
{chr(10).join(fact_lines)}

## Ownership and uncertainty
- **Source-reported legal owner:** {owner_name}
- **Verification status:** {owner_status}
- **Mailing address:** {_display(ownership.mailing_address if ownership else None)}
- A resident agent, if separately verified, is a service-of-process contact and may not
  be the owner or beneficial owner.

## Evidence-backed research signals
{chr(10).join(signal_lines)}

## Seller-stated motivation
{seller_statement_text}

## Missing information
{missing_text}
Missing data is not adverse evidence and must not be treated as a seller signal.

## Potential buyer-fit hypothesis
The source-reported use is {_display(property_record.property_type)} with
{_display(property_record.building_area_sqft, " sq ft")} of building area. Confirm fit
against a documented buyer mandate; this is not a recommendation or valuation.

## Honest call opener
“Hi, my name is {caller_name}. I research small commercial properties in Prince George’s
County and work on identifying opportunities for local buyers. I’m calling about
{property_record.address}. I don’t want to assume you’re interested in selling—would you
be open to a brief conversation about your plans for the property?”

## Discovery questions
{chr(10).join(question_lines)}

## Compliance warnings
- Confirm the decision-maker and lawful contact source.
- Check approval, opt-out, do-not-contact, National DNC/TCPA, CAN-SPAM, Maryland law,
  privacy, and licensing requirements with counsel before outreach.
- Make no claim of distress, valuation, capital, affiliation, guaranteed price, or close.
- Respect “no” immediately and ask permission before follow-up.

## Recent notes and next action
{chr(10).join(activity_lines)}
- **Next action:** {_display(next_action)}

## Sources
{chr(10).join(source_lines)}
"""


def write_property_brief(
    session: Session, property_id: int, caller_name: str, output: Path
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        generate_property_brief(session, property_id, caller_name),
        encoding="utf-8",
    )
