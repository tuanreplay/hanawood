import logging
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Activity, Campaign, Contact, Tag, utcnow
from .schemas import ContactCreate, ContactUpdate, SegmentFilters, Stage

logger = logging.getLogger(__name__)

STAGES: tuple[Stage, ...] = ("subscriber", "lead", "mql", "sql", "customer", "churned")


class DuplicateContact(Exception):
    pass


class CampaignAlreadySent(Exception):
    pass


class EmailSender(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class LogEmailSender:
    """Development sender: writes to the log instead of delivering mail.
    Replace with an SMTP / SES / SendGrid implementation in production."""

    def send(self, to: str, subject: str, body: str) -> None:
        logger.info("CRM email to=%s subject=%r", to, subject)


def personalize(text: str, contact: Contact) -> str:
    return text.replace("{{first_name}}", contact.first_name or "bạn")


def get_or_create_tags(db: Session, names: list[str]) -> list[Tag]:
    tags = []
    for name in names:
        tag = db.scalar(select(Tag).where(Tag.name == name))
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
        tags.append(tag)
    return tags


def log_activity(db: Session, contact: Contact, type_: str, detail: str = "") -> None:
    db.add(Activity(contact=contact, type=type_, detail=detail))


def create_contact(db: Session, data: ContactCreate) -> Contact:
    if db.scalar(select(Contact.id).where(Contact.email == data.email)) is not None:
        raise DuplicateContact(data.email)

    contact = Contact(
        email=data.email,
        first_name=data.first_name,
        last_name=data.last_name,
        phone=data.phone,
        source=data.source,
        lifecycle_stage=data.lifecycle_stage,
        marketing_consent=data.marketing_consent,
        tags=get_or_create_tags(db, data.tags),
    )
    db.add(contact)
    log_activity(db, contact, "created", f"source={data.source or 'manual'}")
    if data.marketing_consent:
        log_activity(db, contact, "consent_granted", "at signup")
    try:
        db.commit()
    except Exception:  # unique-constraint race between the check above and the insert
        db.rollback()
        raise DuplicateContact(data.email)
    db.refresh(contact)
    return contact


def update_contact(db: Session, contact: Contact, data: ContactUpdate) -> Contact:
    fields = data.model_dump(exclude_unset=True)
    for key in ("lifecycle_stage", "marketing_consent"):
        if fields.get(key) is None:
            fields.pop(key, None)

    if "tags" in fields:
        contact.tags = get_or_create_tags(db, fields.pop("tags") or [])

    new_stage = fields.pop("lifecycle_stage", None)
    if new_stage and new_stage != contact.lifecycle_stage:
        log_activity(db, contact, "stage_changed", f"{contact.lifecycle_stage} -> {new_stage}")
        contact.lifecycle_stage = new_stage

    if "marketing_consent" in fields and fields["marketing_consent"] != contact.marketing_consent:
        log_activity(db, contact, "consent_granted" if fields["marketing_consent"] else "consent_withdrawn")

    for key, value in fields.items():
        setattr(contact, key, value)

    db.commit()
    db.refresh(contact)
    return contact


def unsubscribe_contact(db: Session, contact: Contact) -> Contact:
    if not contact.unsubscribed:
        contact.unsubscribed = True
        contact.marketing_consent = False
        log_activity(db, contact, "unsubscribed")
        db.commit()
        db.refresh(contact)
    return contact


def audience_query(filters: SegmentFilters):
    stmt = select(Contact).where(Contact.unsubscribed.is_(False))
    if filters.stages:
        stmt = stmt.where(Contact.lifecycle_stage.in_(filters.stages))
    if filters.tags:
        stmt = stmt.where(Contact.tags.any(Tag.name.in_(filters.tags)))
    if filters.require_consent:
        stmt = stmt.where(Contact.marketing_consent.is_(True))
    return stmt.order_by(Contact.id)


def send_campaign(db: Session, campaign: Campaign, sender: EmailSender) -> int:
    if campaign.status != "draft":
        raise CampaignAlreadySent(campaign.id)

    filters = SegmentFilters(**campaign.segment.filters) if campaign.segment else SegmentFilters()
    contacts = db.scalars(audience_query(filters)).all()

    for contact in contacts:
        sender.send(contact.email, campaign.subject, personalize(campaign.body, contact))
        log_activity(db, contact, "email_sent", campaign.name)

    campaign.status = "sent"
    campaign.recipient_count = len(contacts)
    campaign.sent_at = utcnow()
    db.commit()
    return len(contacts)


def funnel(db: Session) -> dict[str, int]:
    rows = db.execute(select(Contact.lifecycle_stage, func.count(Contact.id)).group_by(Contact.lifecycle_stage)).all()
    counts = {stage: 0 for stage in STAGES}
    counts.update({stage: count for stage, count in rows})
    return counts
