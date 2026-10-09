"""Printable customer copy of a quote (A4 HTML). Internal cost and margin are never rendered."""

from decimal import Decimal
from html import escape

from .quote_schemas import QuoteOut
from .settings import COMPANY, PRICING_MODE_LABELS, QUOTE_TYPE_LABELS


def money(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def qty(d: Decimal) -> str:
    text = f"{Decimal(d).normalize():f}"
    return text.replace(".", ",")


def roman(n: int) -> str:
    out = ""
    for value, sym in ((100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out += sym
            n -= value
    return out


def _e(value) -> str:
    return escape(str(value)) if value not in (None, "") else ""


CSS = """
*{box-sizing:border-box}
body{font-family:"Times New Roman",Times,serif;font-size:13px;color:#111;margin:0;background:#f2f2f2}
.page{background:#fff;max-width:210mm;margin:16px auto;padding:14mm 12mm;position:relative}
.head{display:flex;justify-content:space-between;gap:16px;border-bottom:2px solid #7a4a1e;padding-bottom:8px}
.brand{font-size:22px;font-weight:bold;color:#7a4a1e;letter-spacing:1px}
.muted{color:#555}
h1{text-align:center;font-size:20px;margin:16px 0 4px;color:#7a4a1e}
.sub{text-align:center;margin-bottom:12px}
.info{display:grid;grid-template-columns:1fr 1fr;gap:2px 24px;margin-bottom:12px}
table{width:100%;border-collapse:collapse}
th,td{border:1px solid #999;padding:4px 5px;vertical-align:top}
th{background:#f3ebe3;text-align:center}
td.n{text-align:right;white-space:nowrap}
td.c{text-align:center}
tr.sec td{background:#faf6f1;font-weight:bold}
tr.sub td{font-weight:bold}
tr.opt td{color:#555;font-style:italic}
.tag{font-weight:normal;font-style:italic;color:#555}
.sum{margin-top:10px;width:60%;margin-left:auto}
.sum td:first-child{text-align:left}
.grand td{font-weight:bold;font-size:14px;background:#f3ebe3}
.words{margin:6px 0 14px;font-style:italic}
h2{font-size:14px;margin:16px 0 6px;color:#7a4a1e}
ul{margin:4px 0;padding-left:20px}
.sign{display:grid;grid-template-columns:1fr 1fr;text-align:center;margin-top:28px;font-weight:bold}
.sign span{display:block;font-weight:normal;font-style:italic;margin-bottom:70px}
.mark{position:absolute;top:40%;left:0;right:0;text-align:center;font-size:72px;color:rgba(200,0,0,.12);
      transform:rotate(-20deg);pointer-events:none;font-weight:bold}
@media print{body{background:#fff}.page{margin:0;padding:10mm;max-width:none}@page{size:A4;margin:8mm}}
"""


def render_quote(q: QuoteOut) -> str:
    show_labor = q.quote_type != "material" and any(s.pricing_mode != "material_only" for s in q.sections)
    show_material = any(s.pricing_mode != "labor_only" for s in q.sections)
    show_waste = any(l.waste_percent for s in q.sections for l in s.lines)
    show_disc = any(l.discount_percent for s in q.sections for l in s.lines)

    headers = ["STT", "Hạng mục / Diễn giải", "ĐVT", "Khối lượng"]
    if show_waste:
        headers.append("Hao hụt")
    if show_material:
        headers.append("Đơn giá vật tư")
    if show_labor:
        headers.append("Đơn giá nhân công")
    if show_disc:
        headers.append("CK")
    headers.append("Thành tiền")
    ncols = len(headers)

    rows = []
    for i, s in enumerate(q.sections, start=1):
        tags = [PRICING_MODE_LABELS[s.pricing_mode]]
        if s.is_optional:
            tags.append("Hạng mục tùy chọn – chưa tính vào tổng")
        rows.append(
            f'<tr class="sec{" opt" if s.is_optional else ""}"><td class="c">{roman(i)}</td>'
            f'<td colspan="{ncols - 1}">{_e(s.name)} <span class="tag">({"; ".join(tags)})</span>'
            + (f'<div class="tag">{_e(s.note)}</div>' if s.note else "")
            + "</td></tr>"
        )
        for j, l in enumerate(s.lines, start=1):
            cells = [f'<td class="c">{j}</td>', f"<td>{_e(l.description)}</td>", f'<td class="c">{_e(l.unit)}</td>',
                     f'<td class="n">{qty(l.quantity)}</td>']
            if show_waste:
                cells.append(f'<td class="n">{qty(l.waste_percent) + "%" if l.waste_percent else ""}</td>')
            if show_material:
                cells.append(f'<td class="n">{money(l.material_unit_price) if l.material_unit_price else ""}</td>')
            if show_labor:
                cells.append(f'<td class="n">{money(l.labor_unit_price) if l.labor_unit_price else ""}</td>')
            if show_disc:
                cells.append(f'<td class="n">{qty(l.discount_percent) + "%" if l.discount_percent else ""}</td>')
            cells.append(f'<td class="n">{money(l.total)}</td>')
            rows.append(f'<tr{" class=opt" if s.is_optional else ""}>{"".join(cells)}</tr>')
        rows.append(
            f'<tr class="sub{" opt" if s.is_optional else ""}"><td></td><td colspan="{ncols - 2}">Cộng hạng mục {roman(i)}</td>'
            f'<td class="n">{money(s.total)}</td></tr>'
        )

    t = q.totals
    summary = [("Tổng giá trị các hạng mục", t.subtotal)]
    if t.discount:
        summary += [(f"Chiết khấu ({qty(q.discount_percent)}%)", -t.discount), ("Giá trị sau chiết khấu", t.after_discount)]
    summary.append((f"Thuế GTGT ({qty(q.vat_rate)}%)", t.vat))
    summary_rows = "".join(f'<tr><td>{label}</td><td class="n">{money(v)}</td></tr>' for label, v in summary)
    summary_rows += f'<tr class="grand"><td>TỔNG GIÁ TRỊ THANH TOÁN</td><td class="n">{money(t.grand_total)}</td></tr>'
    if t.optional_total:
        summary_rows += f'<tr class="opt"><td>Hạng mục tùy chọn (chưa gồm VAT, chưa tính vào tổng)</td><td class="n">{money(t.optional_total)}</td></tr>'

    payments = "".join(
        f'<tr><td class="c">{i}</td><td>{_e(p.name)}</td><td class="c">{qty(p.percent)}%</td><td class="n">{money(p.amount)}</td></tr>'
        for i, p in enumerate(q.payment_schedule, start=1)
    )
    terms = "".join(f"<li>{_e(line)}</li>" for line in q.terms.splitlines() if line.strip())
    notes = "".join(f"<li>{_e(line)}</li>" for line in q.notes.splitlines() if line.strip())

    mark = "BẢN NHÁP" if q.status == "draft" else "HẾT HIỆU LỰC" if q.is_expired else ""
    company_lines = " · ".join(
        _e(v) for v in (COMPANY["address"], COMPANY["phone"] and f"ĐT: {COMPANY['phone']}", COMPANY["email"],
                        COMPANY["tax_code"] and f"MST: {COMPANY['tax_code']}") if v
    )
    info = [
        ("Khách hàng", q.customer_name), ("Điện thoại", q.customer_phone), ("Email", q.customer_email),
        ("Công trình", q.project_name), ("Địa chỉ công trình", q.site_address),
    ]
    info_html = "".join(f"<div><b>{k}:</b> {_e(v)}</div>" for k, v in info if v)
    waste_note = (
        "<p class='muted'><i>Thành tiền vật tư được tính trên khối lượng đã cộng tỷ lệ hao hụt.</i></p>" if show_waste else ""
    )

    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(q.code)} – {_e(q.title)}</title><style>{CSS}</style></head>
<body><div class="page">
{f'<div class="mark">{mark}</div>' if mark else ''}
<div class="head"><div><div class="brand">{_e(COMPANY['name'])}</div><div class="muted">{company_lines}</div></div>
<div style="text-align:right"><div><b>Số:</b> {_e(q.code)}</div><div><b>Ngày:</b> {q.created_at:%d/%m/%Y}</div>
<div><b>Hiệu lực đến:</b> {q.valid_until:%d/%m/%Y}</div></div></div>
<h1>{QUOTE_TYPE_LABELS[q.quote_type]}</h1>
<div class="sub"><b>{_e(q.title)}</b>{f' – Phiên bản {q.version}' if q.version > 1 else ''}</div>
<div class="info">{info_html}</div>
<p>{_e(COMPANY['name'])} trân trọng gửi Quý khách bảng báo giá chi tiết như sau:</p>
<table><thead><tr>{''.join(f'<th>{h}</th>' for h in headers)}</tr></thead><tbody>{''.join(rows)}</tbody></table>
{waste_note}
<table class="sum">{summary_rows}</table>
<div class="words"><b>Bằng chữ:</b> {t.grand_total_words}.</div>
<h2>Tiến độ thanh toán</h2>
<table><thead><tr><th>Đợt</th><th>Nội dung</th><th>Tỷ lệ</th><th>Số tiền</th></tr></thead><tbody>{payments}</tbody></table>
{f'<h2>Điều khoản</h2><ul>{terms}</ul>' if terms else ''}
{f'<h2>Ghi chú</h2><ul>{notes}</ul>' if notes else ''}
<div class="sign"><div>KHÁCH HÀNG<span>(Ký, ghi rõ họ tên)</span></div>
<div>ĐẠI DIỆN {_e(COMPANY['name'])}<span>(Ký, ghi rõ họ tên)</span></div></div>
</div></body></html>"""
