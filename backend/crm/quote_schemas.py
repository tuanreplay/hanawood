from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

QuoteType = Literal["finishing", "material", "contractor"]
PricingMode = Literal["full", "material_only", "labor_only"]
QuoteStatus = Literal["draft", "sent", "accepted", "rejected", "superseded"]
VatRate = Literal[0, 5, 8, 10]

Percent = Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)]
Money = Annotated[int, Field(ge=0, le=100_000_000_000)]


# ---- Price catalog --------------------------------------------------------

class PriceItemBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    unit: str = Field(min_length=1, max_length=16)
    category: str | None = Field(None, max_length=64)
    retail_price: int = Field(0, ge=0)
    contractor_price: int = Field(0, ge=0, description="Giá đại lý / nhà thầu; 0 = dùng giá bán lẻ")
    labor_price: int = Field(0, ge=0)
    material_cost: int = Field(0, ge=0)
    labor_cost: int = Field(0, ge=0)
    waste_percent: Percent = Decimal(0)
    active: bool = True


class PriceItemCreate(PriceItemBase):
    code: str = Field(min_length=1, max_length=32)


class PriceItemUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    unit: str | None = Field(None, min_length=1, max_length=16)
    category: str | None = Field(None, max_length=64)
    retail_price: int | None = Field(None, ge=0)
    contractor_price: int | None = Field(None, ge=0)
    labor_price: int | None = Field(None, ge=0)
    material_cost: int | None = Field(None, ge=0)
    labor_cost: int | None = Field(None, ge=0)
    waste_percent: Percent | None = None
    active: bool | None = None


class PriceItemOut(PriceItemCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


# ---- Quote input ----------------------------------------------------------

class QuoteLineIn(BaseModel):
    """Either reference a catalog item (prices are filled from the tier matching the quote type)
    or give description/unit/prices manually. Explicit values always override the catalog."""

    price_item_id: int | None = None
    description: str | None = Field(None, max_length=500)
    unit: str | None = Field(None, max_length=16)
    quantity: Decimal = Field(gt=0, le=10_000_000, decimal_places=3)
    waste_percent: Percent | None = None
    material_unit_price: Money | None = None
    labor_unit_price: Money | None = None
    discount_percent: Percent = Decimal(0)
    material_unit_cost: Money | None = None
    labor_unit_cost: Money | None = None

    @model_validator(mode="after")
    def _needs_item_or_description(self):
        if self.price_item_id is None and not (self.description and self.unit):
            raise ValueError("line needs price_item_id or both description and unit")
        return self


class QuoteSectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    pricing_mode: PricingMode | None = Field(
        None, description="full = vật tư + nhân công, material_only = chỉ vật tư, labor_only = chỉ nhân công"
    )
    is_optional: bool = Field(False, description="Hạng mục tùy chọn: hiển thị nhưng không cộng vào tổng")
    note: str = Field("", max_length=2000)
    lines: list[QuoteLineIn] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _prices_match_mode(self):
        for line in self.lines:
            if self.pricing_mode == "material_only" and line.labor_unit_price:
                raise ValueError(f"section '{self.name}' is material_only but a line has labor price")
            if self.pricing_mode == "labor_only" and line.material_unit_price:
                raise ValueError(f"section '{self.name}' is labor_only but a line has material price")
        return self


class PaymentMilestoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    percent: Decimal = Field(gt=0, le=100, decimal_places=2)


class QuoteContent(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    contact_id: int | None = None
    project_name: str | None = Field(None, max_length=255)
    site_address: str | None = Field(None, max_length=255)
    customer_name: str | None = Field(None, max_length=255)
    customer_phone: str | None = Field(None, max_length=32)
    customer_email: str | None = Field(None, max_length=255)
    discount_percent: Percent = Decimal(0)
    vat_rate: VatRate = 10
    valid_until: date | None = Field(None, description="Mặc định theo loại báo giá")
    notes: str = Field("", max_length=5000)
    terms: str | None = Field(None, max_length=10000, description="Mặc định theo loại báo giá")
    sections: list[QuoteSectionIn] = Field(min_length=1, max_length=100)
    payment_milestones: list[PaymentMilestoneIn] | None = Field(
        None, max_length=20, description="Mặc định theo loại báo giá; tổng phải bằng 100%"
    )

    @model_validator(mode="after")
    def _payments_sum_to_100(self):
        if self.payment_milestones and sum(m.percent for m in self.payment_milestones) != 100:
            raise ValueError("payment milestones must sum to 100%")
        if not any(not s.is_optional for s in self.sections):
            raise ValueError("quote needs at least one non-optional section")
        return self


class QuoteCreate(QuoteContent):
    quote_type: QuoteType

    @model_validator(mode="after")
    def _material_quote_has_no_labor(self):
        if self.quote_type == "material":
            for section in self.sections:
                if section.pricing_mode not in (None, "material_only"):
                    raise ValueError("material quotes only allow material_only sections")
        return self


class RejectIn(BaseModel):
    reason: str | None = Field(None, max_length=2000)


# ---- Quote output ---------------------------------------------------------

class QuoteLineOut(BaseModel):
    id: int
    price_item_id: int | None
    description: str
    unit: str
    quantity: Decimal
    waste_percent: Decimal
    material_quantity: Decimal
    material_unit_price: int
    labor_unit_price: int
    discount_percent: Decimal
    material_amount: int
    labor_amount: int
    discount: int
    total: int


class QuoteSectionOut(BaseModel):
    id: int
    name: str
    pricing_mode: PricingMode
    is_optional: bool
    note: str
    lines: list[QuoteLineOut]
    material_amount: int
    labor_amount: int
    total: int


class PaymentOut(BaseModel):
    name: str
    percent: Decimal
    amount: int


class QuoteTotalsOut(BaseModel):
    subtotal: int
    discount: int
    after_discount: int
    vat: int
    grand_total: int
    grand_total_words: str
    optional_total: int


class InternalOut(BaseModel):
    """Internal-only figures; never printed on the customer copy."""

    cost: int
    gross_profit: int
    margin_percent: Decimal
    min_margin_percent: Decimal
    below_min_margin: bool


class QuoteOut(BaseModel):
    id: int
    code: str
    quote_type: QuoteType
    status: QuoteStatus
    is_expired: bool
    version: int
    parent_id: int | None
    contact_id: int | None
    title: str
    project_name: str | None
    site_address: str | None
    customer_name: str | None
    customer_phone: str | None
    customer_email: str | None
    discount_percent: Decimal
    vat_rate: Decimal
    valid_until: date
    notes: str
    terms: str
    reject_reason: str | None
    created_at: datetime
    sent_at: datetime | None
    decided_at: datetime | None
    sections: list[QuoteSectionOut]
    payment_schedule: list[PaymentOut]
    totals: QuoteTotalsOut
    internal: InternalOut


class QuoteSummary(BaseModel):
    id: int
    code: str
    quote_type: QuoteType
    status: QuoteStatus
    is_expired: bool
    version: int
    title: str
    customer_name: str | None
    valid_until: date
    grand_total: int
    created_at: datetime
