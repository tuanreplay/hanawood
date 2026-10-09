from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Text,
)
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


# ---- Pricing & quotations -------------------------------------------------
# Money is stored as whole VND (BigInteger); quantities and percents as Numeric.


class PriceItem(Base):
    """Catalog entry with one price per customer tier plus internal costs for margin control."""

    __tablename__ = "crm_price_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    unit: Mapped[str] = mapped_column(String(16))
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    retail_price: Mapped[int] = mapped_column(BigInteger, default=0)
    contractor_price: Mapped[int] = mapped_column(BigInteger, default=0)
    labor_price: Mapped[int] = mapped_column(BigInteger, default=0)
    material_cost: Mapped[int] = mapped_column(BigInteger, default=0)
    labor_cost: Mapped[int] = mapped_column(BigInteger, default=0)
    waste_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Quote(Base):
    __tablename__ = "crm_quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str | None] = mapped_column(String(40), unique=True, index=True)  # set after insert
    quote_type: Mapped[str] = mapped_column(String(16), index=True)  # finishing | material | contractor
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("crm_quotes.id", ondelete="SET NULL"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("crm_contacts.id", ondelete="SET NULL"), index=True)

    title: Mapped[str] = mapped_column(String(255))
    project_name: Mapped[str | None] = mapped_column(String(255))
    site_address: Mapped[str | None] = mapped_column(String(255))
    # Customer details are snapshotted so a printed quote never changes after the contact is edited.
    customer_name: Mapped[str | None] = mapped_column(String(255))
    customer_phone: Mapped[str | None] = mapped_column(String(32))
    customer_email: Mapped[str | None] = mapped_column(String(255))

    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("10"))
    valid_until: Mapped[date] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, default="")
    terms: Mapped[str] = mapped_column(Text, default="")
    reject_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    contact: Mapped[Contact | None] = relationship()
    sections: Mapped[list["QuoteSection"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan", order_by="QuoteSection.position"
    )
    payment_milestones: Mapped[list["PaymentMilestone"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan", order_by="PaymentMilestone.position"
    )


class QuoteSection(Base):
    """A work package (hạng mục). Each one picks its own pricing mode, so a single quote can mix
    turnkey work, material-only supply and labor-only installation."""

    __tablename__ = "crm_quote_sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("crm_quotes.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(255))
    pricing_mode: Mapped[str] = mapped_column(String(16))  # full | material_only | labor_only
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")

    quote: Mapped[Quote] = relationship(back_populates="sections")
    lines: Mapped[list["QuoteLine"]] = relationship(
        back_populates="section", cascade="all, delete-orphan", order_by="QuoteLine.position"
    )


class QuoteLine(Base):
    __tablename__ = "crm_quote_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("crm_quote_sections.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    price_item_id: Mapped[int | None] = mapped_column(ForeignKey("crm_price_items.id", ondelete="SET NULL"))
    description: Mapped[str] = mapped_column(String(500))
    unit: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    waste_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    material_unit_price: Mapped[int] = mapped_column(BigInteger, default=0)
    labor_unit_price: Mapped[int] = mapped_column(BigInteger, default=0)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    # Internal cost snapshot for margin reporting; never printed.
    material_unit_cost: Mapped[int] = mapped_column(BigInteger, default=0)
    labor_unit_cost: Mapped[int] = mapped_column(BigInteger, default=0)

    section: Mapped[QuoteSection] = relationship(back_populates="lines")


class PaymentMilestone(Base):
    __tablename__ = "crm_quote_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("crm_quotes.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(255))
    percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))

    quote: Mapped[Quote] = relationship(back_populates="payment_milestones")
