from decimal import Decimal

from crm.pricing import LineInput, amount_in_words, line_totals, quote_totals, section_totals, split_payments


def test_line_applies_waste_to_material_only_then_discount():
    t = line_totals(LineInput(quantity=Decimal(40), material_unit_price=450_000, labor_unit_price=80_000,
                              waste_percent=Decimal(5), discount_percent=Decimal(10)))
    assert t.material_quantity == Decimal(42)
    assert t.material_amount == 18_900_000
    assert t.labor_amount == 3_200_000
    assert t.discount == 2_210_000
    assert t.total == 19_890_000


def test_rounding_is_half_up_to_whole_vnd():
    t = line_totals(LineInput(quantity=Decimal("1.5"), material_unit_price=333))
    assert t.material_amount == 500  # 499.5 -> 500


def test_optional_sections_are_excluded_from_totals():
    required = section_totals([LineInput(quantity=Decimal(1), material_unit_price=1_000_000, material_unit_cost=700_000)])
    optional = section_totals([LineInput(quantity=Decimal(1), material_unit_price=5_000_000)], is_optional=True)
    t = quote_totals([required, optional], Decimal(0), Decimal(10))
    assert t.subtotal == 1_000_000
    assert t.optional_total == 5_000_000
    assert t.vat == 100_000 and t.grand_total == 1_100_000
    assert t.margin_percent == Decimal("30.00")


def test_payment_schedule_always_sums_to_total():
    amounts = split_payments(1_000_001, [Decimal(30), Decimal(40), Decimal(30)])
    assert amounts == [300_000, 400_000, 300_001]
    assert sum(amounts) == 1_000_001


def test_amount_in_words():
    cases = {
        0: "Không đồng",
        15: "Mười lăm đồng",
        21: "Hai mươi mốt đồng",
        105: "Một trăm linh năm đồng",
        1_000_005: "Một triệu không trăm linh năm đồng",
        38_782_800: "Ba mươi tám triệu bảy trăm tám mươi hai nghìn tám trăm đồng",
        2_000_000_000: "Hai tỷ đồng",
        1_500_000_000_000: "Một nghìn năm trăm tỷ đồng",
    }
    for amount, words in cases.items():
        assert amount_in_words(amount) == words
