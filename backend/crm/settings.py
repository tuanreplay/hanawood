import os
from decimal import Decimal

COMPANY = {
    "name": os.getenv("CRM_COMPANY_NAME", "HANAWOOD"),
    "address": os.getenv("CRM_COMPANY_ADDRESS", ""),
    "phone": os.getenv("CRM_COMPANY_PHONE", ""),
    "email": os.getenv("CRM_COMPANY_EMAIL", ""),
    "tax_code": os.getenv("CRM_COMPANY_TAX_CODE", ""),
}

# Quotes whose gross margin falls below this are flagged for manager approval.
MIN_MARGIN_PERCENT = Decimal(os.getenv("CRM_MIN_MARGIN_PERCENT", "15"))

QUOTE_TYPE_LABELS = {
    "finishing": "BÁO GIÁ THI CÔNG HOÀN THIỆN",
    "material": "BÁO GIÁ VẬT TƯ",
    "contractor": "BÁO GIÁ NHÀ THẦU",
}
QUOTE_CODE_PREFIX = {"finishing": "HT", "material": "VT", "contractor": "NT"}

PRICING_MODE_LABELS = {
    "full": "Trọn gói vật tư + nhân công",
    "material_only": "Chỉ cung cấp vật tư",
    "labor_only": "Chỉ nhân công thi công, lắp đặt",
}

# Per-type defaults applied when the request leaves validity, payments or terms empty.
QUOTE_DEFAULTS = {
    "finishing": {
        "valid_days": 15,
        "payments": [
            ("Tạm ứng khi ký hợp đồng", Decimal(30)),
            ("Khi tập kết vật tư và thi công đạt 50% khối lượng", Decimal(40)),
            ("Sau khi nghiệm thu, bàn giao", Decimal(30)),
        ],
        "terms": "\n".join([
            "Đơn giá đã bao gồm vật tư, nhân công, vận chuyển nội thành và vệ sinh sau thi công.",
            "Khối lượng thanh toán theo nghiệm thu thực tế tại công trình; phát sinh tăng/giảm áp dụng đơn giá trong báo giá này.",
            "Mặt bằng bàn giao phải đạt điều kiện thi công theo yêu cầu kỹ thuật của từng hạng mục.",
            "Bảo hành thi công 12 tháng kể từ ngày bàn giao; vật tư bảo hành theo chính sách nhà sản xuất.",
        ]),
    },
    "material": {
        "valid_days": 7,
        "payments": [
            ("Đặt cọc khi xác nhận đơn hàng", Decimal(50)),
            ("Thanh toán phần còn lại trước khi giao hàng", Decimal(50)),
        ],
        "terms": "\n".join([
            "Giá giao tại kho; phí vận chuyển tính riêng nếu không thể hiện trong báo giá.",
            "Khối lượng vật tư đã bao gồm tỷ lệ hao hụt khuyến nghị (nếu có).",
            "Hàng cắt theo kích thước hoặc đặt riêng theo yêu cầu không áp dụng đổi trả.",
        ]),
    },
    "contractor": {
        "valid_days": 30,
        "payments": [
            ("Đặt cọc khi ký hợp đồng nguyên tắc / đơn đặt hàng", Decimal(30)),
            ("Thanh toán trong 30 ngày kể từ ngày giao hàng / nghiệm thu", Decimal(70)),
        ],
        "terms": "\n".join([
            "Đơn giá áp dụng cho đối tác nhà thầu, đại lý; không áp dụng cho khách lẻ.",
            "Giá có thể điều chỉnh khi khối lượng đặt hàng thay đổi hoặc giá nguyên liệu biến động; hai bên xác nhận lại trước mỗi đợt giao.",
            "Hạn mức và thời hạn công nợ theo hợp đồng nguyên tắc đã ký.",
        ]),
    },
}
