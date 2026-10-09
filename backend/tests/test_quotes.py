from datetime import date, timedelta

import pytest

from conftest import make_contact

CATALOG = [
    {"code": "SG-OAK12", "name": "Sàn gỗ sồi 12mm", "unit": "m2", "category": "san-go",
     "retail_price": 450_000, "contractor_price": 390_000, "labor_price": 80_000,
     "material_cost": 300_000, "labor_cost": 50_000, "waste_percent": "5"},
    {"code": "PK-NEP", "name": "Nẹp kết thúc", "unit": "md", "category": "phu-kien",
     "retail_price": 60_000, "contractor_price": 50_000, "labor_price": 15_000,
     "material_cost": 35_000, "labor_cost": 8_000},
    {"code": "CUA-01", "name": "Cửa gỗ phòng ngủ", "unit": "bộ", "category": "cua",
     "retail_price": 6_500_000, "contractor_price": 5_800_000, "labor_price": 500_000,
     "material_cost": 4_500_000, "labor_cost": 300_000},
]


@pytest.fixture
def items(client):
    ids = {}
    for payload in CATALOG:
        r = client.post("/api/crm/price-items", json=payload)
        assert r.status_code == 201, r.text
        ids[payload["code"]] = r.json()["id"]
    return ids


def finishing_payload(items, **overrides):
    payload = {
        "quote_type": "finishing",
        "title": "Hoàn thiện sàn gỗ và cửa căn hộ A12",
        "project_name": "Căn hộ A12",
        "site_address": "Q.7, TP.HCM",
        "discount_percent": "5",
        "vat_rate": 8,
        "sections": [
            {"name": "Sàn gỗ phòng khách", "lines": [
                {"price_item_id": items["SG-OAK12"], "quantity": "40"},
                {"price_item_id": items["PK-NEP"], "quantity": "20"},
            ]},
            {"name": "Cửa phòng ngủ", "pricing_mode": "material_only", "lines": [
                {"price_item_id": items["CUA-01"], "quantity": "2"},
            ]},
            {"name": "Lắp sàn phòng ngủ (khách cấp vật tư)", "pricing_mode": "labor_only", "lines": [
                {"price_item_id": items["SG-OAK12"], "quantity": "15"},
            ]},
            {"name": "Tủ bếp (phương án tham khảo)", "is_optional": True, "lines": [
                {"description": "Tủ bếp gỗ sồi trọn bộ", "unit": "bộ", "quantity": "1", "material_unit_price": 25_000_000},
            ]},
        ],
    }
    payload.update(overrides)
    return payload


def create(client, payload):
    r = client.post("/api/crm/quotes", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def test_finishing_quote_mixes_pricing_modes_per_section(client, items):
    q = create(client, finishing_payload(items))
    assert q["code"].startswith("BG-HT-") and q["status"] == "draft"

    living, doors, labor_only, kitchen = q["sections"]
    assert living["pricing_mode"] == "full"
    assert living["lines"][0]["material_quantity"] == "42.000"  # 40 m2 + 5% waste
    assert living["total"] == 23_600_000
    assert doors["labor_amount"] == 0 and doors["total"] == 13_000_000
    assert labor_only["material_amount"] == 0 and labor_only["total"] == 1_200_000
    assert labor_only["lines"][0]["waste_percent"] == "0.00"
    assert kitchen["is_optional"] and kitchen["total"] == 25_000_000

    t = q["totals"]
    assert t["subtotal"] == 37_800_000
    assert t["discount"] == 1_890_000
    assert t["vat"] == 2_872_800
    assert t["grand_total"] == 38_782_800
    assert t["optional_total"] == 25_000_000
    assert t["grand_total_words"] == "Ba mươi tám triệu bảy trăm tám mươi hai nghìn tám trăm đồng"

    assert q["internal"]["cost"] == 25_210_000
    assert q["internal"]["margin_percent"] == "29.80"
    assert q["internal"]["below_min_margin"] is False

    assert [p["percent"] for p in q["payment_schedule"]] == ["30.00", "40.00", "30.00"]
    assert sum(p["amount"] for p in q["payment_schedule"]) == t["grand_total"]
    assert q["valid_until"] == str(date.today() + timedelta(days=15))


def test_material_quote_never_charges_labor(client, items):
    q = create(client, {
        "quote_type": "material", "title": "Vật tư sàn gỗ",
        "sections": [{"name": "Sàn gỗ", "lines": [{"price_item_id": items["SG-OAK12"], "quantity": "100"}]}],
    })
    assert q["code"].startswith("BG-VT-")
    assert q["sections"][0]["pricing_mode"] == "material_only"
    assert q["sections"][0]["labor_amount"] == 0
    assert q["totals"]["subtotal"] == 47_250_000  # 105 m2 x 450 000
    assert q["totals"]["grand_total"] == 51_975_000
    assert [p["percent"] for p in q["payment_schedule"]] == ["50.00", "50.00"]


def test_material_quote_rejects_labor_sections(client, items):
    r = client.post("/api/crm/quotes", json={
        "quote_type": "material", "title": "x",
        "sections": [{"name": "s", "pricing_mode": "full", "lines": [{"price_item_id": items["SG-OAK12"], "quantity": "1"}]}],
    })
    assert r.status_code == 422


def test_contractor_quote_uses_contractor_tier_and_flags_low_margin(client, items):
    q = create(client, {
        "quote_type": "contractor", "title": "Cung cấp sàn gỗ dự án", "discount_percent": "10",
        "sections": [{"name": "Sàn gỗ tầng 2-5", "pricing_mode": "material_only",
                      "lines": [{"price_item_id": items["SG-OAK12"], "quantity": "500"}]}],
    })
    assert q["code"].startswith("BG-NT-")
    assert q["sections"][0]["lines"][0]["material_unit_price"] == 390_000
    assert q["totals"]["subtotal"] == 204_750_000
    assert q["totals"]["after_discount"] == 184_275_000
    assert q["internal"]["margin_percent"] == "14.53"
    assert q["internal"]["below_min_margin"] is True


def test_explicit_prices_override_catalog(client, items):
    q = create(client, finishing_payload(items, sections=[
        {"name": "Sàn", "lines": [{"price_item_id": items["SG-OAK12"], "quantity": "10",
                                   "material_unit_price": 400_000, "waste_percent": "0", "description": "Sàn gỗ KM"}]},
    ]))
    line = q["sections"][0]["lines"][0]
    assert line["description"] == "Sàn gỗ KM"
    assert line["material_unit_price"] == 400_000 and line["labor_unit_price"] == 80_000
    assert line["total"] == 4_800_000


def test_catalog_price_change_does_not_alter_existing_quote(client, items):
    q = create(client, finishing_payload(items))
    client.patch(f"/api/crm/price-items/{items['SG-OAK12']}", json={"retail_price": 999_000})
    assert client.get(f"/api/crm/quotes/{q['id']}").json()["totals"]["grand_total"] == 38_782_800


@pytest.mark.parametrize("change, detail", [
    ({"payment_milestones": [{"name": "a", "percent": "50"}, {"name": "b", "percent": "40"}]}, "100%"),
    ({"vat_rate": 7}, None),
    ({"sections": [{"name": "s", "lines": [{"quantity": "1"}]}]}, "description"),
    ({"sections": [{"name": "s", "pricing_mode": "material_only",
                    "lines": [{"description": "x", "unit": "m2", "quantity": "1", "labor_unit_price": 1}]}]}, "material_only"),
    ({"sections": [{"name": "s", "is_optional": True,
                    "lines": [{"description": "x", "unit": "m2", "quantity": "1"}]}]}, "non-optional"),
])
def test_invalid_quote_input_is_rejected(client, items, change, detail):
    r = client.post("/api/crm/quotes", json=finishing_payload(items, **change))
    assert r.status_code == 422
    if detail:
        assert detail in r.text


def test_unknown_references_are_rejected(client, items):
    assert client.post("/api/crm/quotes", json=finishing_payload(items, contact_id=999)).status_code == 422
    bad_item = finishing_payload(items, sections=[{"name": "s", "lines": [{"price_item_id": 999, "quantity": "1"}]}])
    assert client.post("/api/crm/quotes", json=bad_item).status_code == 422


def test_duplicate_price_item_code_conflicts(client, items):
    assert client.post("/api/crm/price-items", json=CATALOG[0]).status_code == 409


def test_quote_lifecycle_moves_contact_through_pipeline(client, items):
    contact = make_contact(client, first_name="Lan", last_name="Trần", phone="0909000111")
    q = create(client, finishing_payload(items, contact_id=contact["id"]))
    assert q["customer_name"] == "Lan Trần" and q["customer_phone"] == "0909000111"

    # Draft can be edited; after sending it is locked.
    edit = finishing_payload(items, contact_id=contact["id"], discount_percent="0")
    edit.pop("quote_type")
    assert client.put(f"/api/crm/quotes/{q['id']}", json=edit).json()["totals"]["discount"] == 0

    sent = client.post(f"/api/crm/quotes/{q['id']}/send").json()
    assert sent["status"] == "sent" and sent["sent_at"]
    assert client.put(f"/api/crm/quotes/{q['id']}", json=edit).status_code == 409
    assert client.get(f"/api/crm/contacts/{contact['id']}").json()["lifecycle_stage"] == "sql"

    assert client.post(f"/api/crm/quotes/{q['id']}/accept").json()["status"] == "accepted"
    detail = client.get(f"/api/crm/contacts/{contact['id']}").json()
    assert detail["lifecycle_stage"] == "customer"
    types = [a["type"] for a in detail["activities"]]
    assert "quote_sent" in types and "quote_accepted" in types

    assert client.post(f"/api/crm/quotes/{q['id']}/revise").status_code == 409


def test_revision_supersedes_sent_quote(client, items):
    q = create(client, finishing_payload(items))
    client.post(f"/api/crm/quotes/{q['id']}/send")

    r1 = client.post(f"/api/crm/quotes/{q['id']}/revise")
    assert r1.status_code == 201
    r1 = r1.json()
    assert r1["code"] == f"{q['code']}-R1" and r1["version"] == 2 and r1["status"] == "draft"
    assert r1["parent_id"] == q["id"]
    assert r1["totals"]["grand_total"] == q["totals"]["grand_total"]
    assert client.get(f"/api/crm/quotes/{q['id']}").json()["status"] == "superseded"
    assert client.post(f"/api/crm/quotes/{q['id']}/revise").status_code == 409

    client.post(f"/api/crm/quotes/{r1['id']}/send")
    r2 = client.post(f"/api/crm/quotes/{r1['id']}/revise").json()
    assert r2["code"] == f"{q['code']}-R2" and r2["version"] == 3


def test_rejected_quote_keeps_reason_and_can_be_revised_once(client, items):
    contact = make_contact(client)
    q = create(client, finishing_payload(items, contact_id=contact["id"]))
    client.post(f"/api/crm/quotes/{q['id']}/send")
    rejected = client.post(f"/api/crm/quotes/{q['id']}/reject", json={"reason": "Giá cao hơn đối thủ"}).json()
    assert rejected["status"] == "rejected" and rejected["reject_reason"] == "Giá cao hơn đối thủ"

    assert client.post(f"/api/crm/quotes/{q['id']}/revise").status_code == 201
    assert client.get(f"/api/crm/quotes/{q['id']}").json()["status"] == "rejected"
    assert client.post(f"/api/crm/quotes/{q['id']}/revise").status_code == 409


def test_expired_quote_cannot_be_accepted(client, items):
    q = create(client, finishing_payload(items, valid_until=str(date.today() - timedelta(days=1))))
    sent = client.post(f"/api/crm/quotes/{q['id']}/send").json()
    assert sent["is_expired"] is True
    assert client.post(f"/api/crm/quotes/{q['id']}/accept").status_code == 409


def test_list_filters_quotes(client, items):
    create(client, finishing_payload(items))
    create(client, {"quote_type": "material", "title": "VT",
                    "sections": [{"name": "s", "lines": [{"price_item_id": items["PK-NEP"], "quantity": "1"}]}]})
    listed = client.get("/api/crm/quotes", params={"quote_type": "material"}).json()
    assert len(listed) == 1 and listed[0]["grand_total"] == 66_000
    assert len(client.get("/api/crm/quotes", params={"status": "draft"}).json()) == 2


def test_print_view_is_customer_safe(client, items):
    q = create(client, finishing_payload(items, title="<script>alert(1)</script>"))
    html = client.get(f"/api/crm/quotes/{q['id']}/print").text
    assert "BÁO GIÁ THI CÔNG HOÀN THIỆN" in html
    assert q["code"] in html
    assert "38.782.800" in html
    assert "Ba mươi tám triệu bảy trăm tám mươi hai nghìn tám trăm đồng" in html
    assert "Cộng hạng mục IV" in html and "Chỉ nhân công" in html
    assert "BẢN NHÁP" in html
    assert "<script>alert(1)</script>" not in html
    assert "25.210.000" not in html  # internal cost never printed

    material = create(client, {"quote_type": "material", "title": "VT",
                               "sections": [{"name": "s", "lines": [{"price_item_id": items["PK-NEP"], "quantity": "1"}]}]})
    material_html = client.get(f"/api/crm/quotes/{material['id']}/print").text
    assert "BÁO GIÁ VẬT TƯ" in material_html and "Đơn giá nhân công" not in material_html
