from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .models import Contact, PaymentMilestone, PriceItem, Quote, QuoteLine, QuoteSection, utcnow
from .pricing import LineInput, amount_in_words, quote_totals, section_totals
from .quote_schemas import (
    InternalOut,
    PaymentOut,
    QuoteContent,
    QuoteCreate,
    QuoteLineIn,
    QuoteLineOut,
    QuoteOut,
    QuoteSectionOut,
    QuoteSummary,
    QuoteTotalsOut,
)
from .services import log_activity
from .settings import MIN_MARGIN_PERCENT, QUOTE_CODE_PREFIX, QUOTE_DEFAULTS

PRE_SALES_STAGES = ("subscriber", "lead", "mql")


def _pct(value) -> Decimal:
    # Fixed scale so API output is identical whether values came from the request or the database.
    return Decimal(value).quantize(Decimal("0.01"))


def _qty(value) -> Decimal:
    return Decimal(value).quantize(Decimal("0.001"))


class QuoteInputError(ValueError):
    """Request references something that does not exist (contact, price item)."""


class QuoteStateError(Exception):
    """Action not allowed in the quote's current status."""


# ---- Building quote content -----------------------------------------------

def _resolve_line(db: Session, quote_type: str, mode: str, data: QuoteLineIn, position: int) -> QuoteLine:
    item = None
    if data.price_item_id is not None:
        item = db.get(PriceItem, data.price_item_id)
        if item is None or not item.active:
            raise QuoteInputError(f"price item {data.price_item_id} not found or inactive")

    def pick(explicit, catalog_value, default=0):
        if explicit is not None:
            return explicit
        return catalog_value if item is not None else default

    catalog_material = 0
    if item is not None:
        catalog_material = item.contractor_price if quote_type == "contractor" and item.contractor_price else item.retail_price

    line = QuoteLine(
        position=position,
        price_item_id=item.id if item else None,
        description=data.description or item.name,
        unit=data.unit or item.unit,
        quantity=data.quantity,
        waste_percent=pick(data.waste_percent, item.waste_percent if item else 0, Decimal(0)),
        material_unit_price=pick(data.material_unit_price, catalog_material),
        labor_unit_price=pick(data.labor_unit_price, item.labor_price if item else 0),
        discount_percent=data.discount_percent,
        material_unit_cost=pick(data.material_unit_cost, item.material_cost if item else 0),
        labor_unit_cost=pick(data.labor_unit_cost, item.labor_cost if item else 0),
    )
    # The section's pricing mode wins over catalog values: material-only supply carries no labor,
    # labor-only work carries no material (customer supplies it), hence no waste either.
    if mode == "material_only":
        line.labor_unit_price = line.labor_unit_cost = 0
    elif mode == "labor_only":
        line.material_unit_price = line.material_unit_cost = 0
        line.waste_percent = Decimal(0)
    return line


def _apply_content(db: Session, quote: Quote, data: QuoteContent) -> None:
    defaults = QUOTE_DEFAULTS[quote.quote_type]

    contact = None
    if data.contact_id is not None:
        contact = db.get(Contact, data.contact_id)
        if contact is None:
            raise QuoteInputError(f"contact {data.contact_id} not found")
    quote.contact = contact

    full_name = " ".join(p for p in (contact.first_name, contact.last_name) if p) if contact else None
    quote.title = data.title
    quote.project_name = data.project_name
    quote.site_address = data.site_address
    quote.customer_name = data.customer_name or full_name or None
    quote.customer_phone = data.customer_phone or (contact.phone if contact else None)
    quote.customer_email = data.customer_email or (contact.email if contact else None)
    quote.discount_percent = data.discount_percent
    quote.vat_rate = Decimal(data.vat_rate)
    quote.valid_until = data.valid_until or date.today() + timedelta(days=defaults["valid_days"])
    quote.notes = data.notes
    quote.terms = defaults["terms"] if data.terms is None else data.terms

    quote.sections = []
    for s_pos, s in enumerate(data.sections):
        mode = s.pricing_mode or ("material_only" if quote.quote_type == "material" else "full")
        quote.sections.append(
            QuoteSection(
                position=s_pos,
                name=s.name,
                pricing_mode=mode,
                is_optional=s.is_optional,
                note=s.note,
                lines=[_resolve_line(db, quote.quote_type, mode, line, l_pos) for l_pos, line in enumerate(s.lines)],
            )
        )

    milestones = (
        [(m.name, m.percent) for m in data.payment_milestones] if data.payment_milestones else defaults["payments"]
    )
    quote.payment_milestones = [
        PaymentMilestone(position=i, name=name, percent=percent) for i, (name, percent) in enumerate(milestones)
    ]


def create_quote(db: Session, data: QuoteCreate) -> Quote:
    quote = Quote(quote_type=data.quote_type, status="draft", version=1)
    _apply_content(db, quote, data)
    db.add(quote)
    db.flush()
    quote.code = f"BG-{QUOTE_CODE_PREFIX[quote.quote_type]}-{quote.created_at:%Y}-{quote.id:05d}"
    db.commit()
    return quote


def update_quote(db: Session, quote: Quote, data: QuoteContent) -> Quote:
    if quote.status != "draft":
        raise QuoteStateError("only draft quotes can be edited; create a revision instead")
    _apply_content(db, quote, data)
    db.commit()
    return quote


# ---- Status workflow ------------------------------------------------------

def is_expired(quote: Quote) -> bool:
    return quote.status == "sent" and quote.valid_until < date.today()


def send_quote(db: Session, quote: Quote) -> Quote:
    if quote.status != "draft":
        raise QuoteStateError(f"cannot send a {quote.status} quote")
    quote.status = "sent"
    quote.sent_at = utcnow()
    if quote.contact:
        if quote.contact.lifecycle_stage in PRE_SALES_STAGES:
            log_activity(db, quote.contact, "stage_changed", f"{quote.contact.lifecycle_stage} -> sql")
            quote.contact.lifecycle_stage = "sql"
        log_activity(db, quote.contact, "quote_sent", quote.code)
    db.commit()
    return quote


def accept_quote(db: Session, quote: Quote) -> Quote:
    if quote.status != "sent":
        raise QuoteStateError(f"cannot accept a {quote.status} quote")
    if is_expired(quote):
        raise QuoteStateError("quote has expired; create a revision with current prices")
    quote.status = "accepted"
    quote.decided_at = utcnow()
    if quote.contact:
        if quote.contact.lifecycle_stage != "customer":
            log_activity(db, quote.contact, "stage_changed", f"{quote.contact.lifecycle_stage} -> customer")
            quote.contact.lifecycle_stage = "customer"
        log_activity(db, quote.contact, "quote_accepted", quote.code)
    db.commit()
    return quote


def reject_quote(db: Session, quote: Quote, reason: str | None) -> Quote:
    if quote.status != "sent":
        raise QuoteStateError(f"cannot reject a {quote.status} quote")
    quote.status = "rejected"
    quote.reject_reason = reason
    quote.decided_at = utcnow()
    if quote.contact:
        log_activity(db, quote.contact, "quote_rejected", f"{quote.code}: {reason or ''}".strip(": "))
    db.commit()
    return quote


def revise_quote(db: Session, quote: Quote) -> Quote:
    """Copy a sent/rejected quote into a new draft version. The sent original is superseded;
    a rejected one keeps its status so the loss reason stays in the history."""
    if quote.status not in ("sent", "rejected"):
        raise QuoteStateError(f"cannot revise a {quote.status} quote")
    if db.scalar(select(Quote.id).where(Quote.parent_id == quote.id)) is not None:
        raise QuoteStateError("this quote already has a revision; revise the latest version")

    root_code = quote.code.split("-R")[0]
    revision = Quote(
        quote_type=quote.quote_type,
        status="draft",
        version=quote.version + 1,
        parent_id=quote.id,
        code=f"{root_code}-R{quote.version}",
        contact=quote.contact,
        **{
            f: getattr(quote, f)
            for f in (
                "title", "project_name", "site_address", "customer_name", "customer_phone", "customer_email",
                "discount_percent", "vat_rate", "notes", "terms",
            )
        },
        valid_until=max(quote.valid_until, date.today() + timedelta(days=QUOTE_DEFAULTS[quote.quote_type]["valid_days"])),
        sections=[
            QuoteSection(
                position=s.position, name=s.name, pricing_mode=s.pricing_mode, is_optional=s.is_optional, note=s.note,
                lines=[
                    QuoteLine(**{
                        f: getattr(line, f)
                        for f in (
                            "position", "price_item_id", "description", "unit", "quantity", "waste_percent",
                            "material_unit_price", "labor_unit_price", "discount_percent",
                            "material_unit_cost", "labor_unit_cost",
                        )
                    })
                    for line in s.lines
                ],
            )
            for s in quote.sections
        ],
        payment_milestones=[
            PaymentMilestone(position=m.position, name=m.name, percent=m.percent) for m in quote.payment_milestones
        ],
    )
    if quote.status == "sent":
        quote.status = "superseded"
    db.add(revision)
    db.commit()
    return revision


# ---- Queries & output -----------------------------------------------------

def load_quote(db: Session, quote_id: int) -> Quote | None:
    return db.scalar(
        select(Quote)
        .where(Quote.id == quote_id)
        .options(selectinload(Quote.sections).selectinload(QuoteSection.lines), selectinload(Quote.payment_milestones))
    )


def list_quotes(db: Session, status=None, quote_type=None, contact_id=None, limit=50, offset=0) -> list[Quote]:
    stmt = select(Quote).options(
        selectinload(Quote.sections).selectinload(QuoteSection.lines), selectinload(Quote.payment_milestones)
    )
    if status:
        stmt = stmt.where(Quote.status == status)
    if quote_type:
        stmt = stmt.where(Quote.quote_type == quote_type)
    if contact_id is not None:
        stmt = stmt.where(Quote.contact_id == contact_id)
    return list(db.scalars(stmt.order_by(Quote.id.desc()).limit(limit).offset(offset)))


def _line_input(line: QuoteLine) -> LineInput:
    return LineInput(
        quantity=Decimal(line.quantity),
        material_unit_price=line.material_unit_price,
        labor_unit_price=line.labor_unit_price,
        waste_percent=Decimal(line.waste_percent),
        discount_percent=Decimal(line.discount_percent),
        material_unit_cost=line.material_unit_cost,
        labor_unit_cost=line.labor_unit_cost,
    )


def compute(quote: Quote):
    sections = [section_totals([_line_input(l) for l in s.lines], s.is_optional) for s in quote.sections]
    return quote_totals(
        sections,
        Decimal(quote.discount_percent),
        Decimal(quote.vat_rate),
        [Decimal(m.percent) for m in quote.payment_milestones],
    )


def to_out(quote: Quote) -> QuoteOut:
    t = compute(quote)
    sections = []
    for section, st in zip(quote.sections, t.sections):
        lines = [
            QuoteLineOut(
                id=line.id,
                price_item_id=line.price_item_id,
                description=line.description,
                unit=line.unit,
                quantity=_qty(line.quantity),
                waste_percent=_pct(line.waste_percent),
                material_quantity=_qty(lt.material_quantity),
                material_unit_price=line.material_unit_price,
                labor_unit_price=line.labor_unit_price,
                discount_percent=_pct(line.discount_percent),
                material_amount=lt.material_amount,
                labor_amount=lt.labor_amount,
                discount=lt.discount,
                total=lt.total,
            )
            for line, lt in zip(section.lines, st.lines)
        ]
        sections.append(
            QuoteSectionOut(
                id=section.id, name=section.name, pricing_mode=section.pricing_mode, is_optional=section.is_optional,
                note=section.note, lines=lines, material_amount=st.material_amount, labor_amount=st.labor_amount,
                total=st.total,
            )
        )
    return QuoteOut(
        **{
            f: getattr(quote, f)
            for f in (
                "id", "code", "quote_type", "status", "version", "parent_id", "contact_id", "title", "project_name",
                "site_address", "customer_name", "customer_phone", "customer_email", "valid_until", "notes", "terms", "reject_reason", "created_at", "sent_at", "decided_at",
            )
        },
        discount_percent=_pct(quote.discount_percent),
        vat_rate=_pct(quote.vat_rate),
        is_expired=is_expired(quote),
        sections=sections,
        payment_schedule=[
            PaymentOut(name=m.name, percent=_pct(m.percent), amount=amount)
            for m, amount in zip(quote.payment_milestones, t.payments)
        ],
        totals=QuoteTotalsOut(
            subtotal=t.subtotal, discount=t.discount, after_discount=t.after_discount, vat=t.vat,
            grand_total=t.grand_total, grand_total_words=amount_in_words(t.grand_total), optional_total=t.optional_total,
        ),
        internal=InternalOut(
            cost=t.cost, gross_profit=t.gross_profit, margin_percent=t.margin_percent,
            min_margin_percent=MIN_MARGIN_PERCENT, below_min_margin=t.margin_percent < MIN_MARGIN_PERCENT,
        ),
    )


def to_summary(quote: Quote) -> QuoteSummary:
    return QuoteSummary(
        id=quote.id, code=quote.code, quote_type=quote.quote_type, status=quote.status, is_expired=is_expired(quote),
        version=quote.version, title=quote.title, customer_name=quote.customer_name, valid_until=quote.valid_until,
        grand_total=compute(quote).grand_total, created_at=quote.created_at,
    )
