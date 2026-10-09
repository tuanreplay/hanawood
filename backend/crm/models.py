from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


contact_tags = Table(
    "crm_contact_tags",
    Base.metadata,
    Column("contact_id", ForeignKey("crm_contacts.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("crm_tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "crm_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)


class Contact(Base):
    __tablename__ = "crm_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str | None] = mapped_column(String(64))
    lifecycle_stage: Mapped[str] = mapped_column(String(32), default="lead", index=True)
    # Explicit opt-in for marketing email (consent record for PDPD / GDPR compliance).
    marketing_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    unsubscribed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    tags: Mapped[list[Tag]] = relationship(secondary=contact_tags)
    activities: Mapped[list["Activity"]] = relationship(
        back_populates="contact",
        cascade="all, delete-orphan",
        order_by="Activity.id.desc()",
    )


class Activity(Base):
    """Immutable timeline entry: stage changes, consent changes, emails sent, notes."""

    __tablename__ = "crm_activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("crm_contacts.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    contact: Mapped[Contact] = relationship(back_populates="activities")


class Segment(Base):
    """Saved audience definition. Filters are evaluated at send time, not stored as member lists."""

    __tablename__ = "crm_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    filters: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Campaign(Base):
    __tablename__ = "crm_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    segment_id: Mapped[int | None] = mapped_column(ForeignKey("crm_segments.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    segment: Mapped[Segment | None] = relationship()
