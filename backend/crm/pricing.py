"""Pure pricing math for quotations. All money is whole VND, rounded half-up at each line,
section and quote step so the printed figures always add up exactly."""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

HUNDRED = Decimal(100)


def vnd(value: Decimal) -> int:
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def pct(amount: int | Decimal, percent: Decimal) -> int:
    return vnd(Decimal(amount) * Decimal(percent) / HUNDRED)


@dataclass
class LineInput:
    quantity: Decimal
    material_unit_price: int = 0
    labor_unit_price: int = 0
    waste_percent: Decimal = Decimal(0)
    discount_percent: Decimal = Decimal(0)
    material_unit_cost: int = 0
    labor_unit_cost: int = 0


@dataclass
class LineTotals:
    material_quantity: Decimal  # quantity including waste allowance (hao hụt)
    material_amount: int
    labor_amount: int
    gross: int
    discount: int
    total: int
    cost: int


@dataclass
class SectionTotals:
    lines: list[LineTotals]
    material_amount: int
    labor_amount: int
    total: int
    cost: int
    is_optional: bool


@dataclass
class QuoteTotals:
    sections: list[SectionTotals]
    subtotal: int  # required sections only; optional sections are listed but not summed
    discount: int
    after_discount: int
    vat: int
    grand_total: int
    optional_total: int
    cost: int
    gross_profit: int
    margin_percent: Decimal
    payments: list[int] = field(default_factory=list)


def line_totals(line: LineInput) -> LineTotals:
    qty = Decimal(line.quantity)
    material_qty = qty * (1 + Decimal(line.waste_percent) / HUNDRED)
    material_amount = vnd(material_qty * line.material_unit_price)
    labor_amount = vnd(qty * line.labor_unit_price)
    gross = material_amount + labor_amount
    discount = pct(gross, line.discount_percent)
    cost = vnd(material_qty * line.material_unit_cost + qty * line.labor_unit_cost)
    return LineTotals(material_qty, material_amount, labor_amount, gross, discount, gross - discount, cost)


def section_totals(lines: list[LineInput], is_optional: bool = False) -> SectionTotals:
    computed = [line_totals(line) for line in lines]
    return SectionTotals(
        lines=computed,
        material_amount=sum(c.material_amount for c in computed),
        labor_amount=sum(c.labor_amount for c in computed),
        total=sum(c.total for c in computed),
        cost=sum(c.cost for c in computed),
        is_optional=is_optional,
    )


def split_payments(total: int, percents: list[Decimal]) -> list[int]:
    """Amount per milestone; the last one absorbs rounding so the schedule sums to `total`."""
    if not percents:
        return []
    amounts = [pct(total, p) for p in percents[:-1]]
    amounts.append(total - sum(amounts))
    return amounts


def quote_totals(
    sections: list[SectionTotals],
    discount_percent: Decimal,
    vat_rate: Decimal,
    payment_percents: list[Decimal] | None = None,
) -> QuoteTotals:
    required = [s for s in sections if not s.is_optional]
    subtotal = sum(s.total for s in required)
    discount = pct(subtotal, discount_percent)
    after_discount = subtotal - discount
    vat = pct(after_discount, vat_rate)
    grand_total = after_discount + vat
    cost = sum(s.cost for s in required)
    gross_profit = after_discount - cost
    margin = (Decimal(gross_profit) * HUNDRED / after_discount).quantize(Decimal("0.01")) if after_discount else Decimal(0)
    return QuoteTotals(
        sections=sections,
        subtotal=subtotal,
        discount=discount,
        after_discount=after_discount,
        vat=vat,
        grand_total=grand_total,
        optional_total=sum(s.total for s in sections if s.is_optional),
        cost=cost,
        gross_profit=gross_profit,
        margin_percent=margin,
        payments=split_payments(grand_total, payment_percents or []),
    )


# ---- Amount in Vietnamese words (dòng "Bằng chữ" trên báo giá) --------------

_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]


def _read_triple(n: int, full: bool) -> list[str]:
    hundreds, tens, units = n // 100, (n // 10) % 10, n % 10
    words: list[str] = []
    if full or hundreds:
        words += [_DIGITS[hundreds], "trăm"]
    if tens == 0:
        if units:
            words += (["linh"] if (full or hundreds) else []) + [_DIGITS[units]]
    elif tens == 1:
        words.append("mười")
        if units:
            words.append("lăm" if units == 5 else _DIGITS[units])
    else:
        words += [_DIGITS[tens], "mươi"]
        if units:
            words.append({1: "mốt", 4: "tư", 5: "lăm"}.get(units, _DIGITS[units]))
    return words


def _read_below_billion(n: int, full: bool) -> list[str]:
    words: list[str] = []
    for scale, size in (("triệu", 1_000_000), ("nghìn", 1_000), ("", 1)):
        group = (n // size) % 1000
        if group:
            words += _read_triple(group, full)
            if scale:
                words.append(scale)
        full = full or bool(words)
    return words


def amount_in_words(amount: int) -> str:
    if amount < 0:
        text = amount_in_words(-amount)
        return "Âm " + text[0].lower() + text[1:]
    if amount == 0:
        return "Không đồng"
    # Vietnamese reads in blocks of 9 digits joined by "tỷ": 1 500 000 000 000 -> một nghìn năm trăm tỷ.
    blocks = []
    while amount:
        blocks.append(amount % 1_000_000_000)
        amount //= 1_000_000_000
    words: list[str] = []
    for index in range(len(blocks) - 1, -1, -1):
        if blocks[index]:
            words += _read_below_billion(blocks[index], full=bool(words))
            words += ["tỷ"] * index
    text = " ".join(words) + " đồng"
    return text[0].upper() + text[1:]
