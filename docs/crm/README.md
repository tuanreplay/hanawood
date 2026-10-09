# Marketing CRM — Nghiên cứu & Thiết kế

Tài liệu này ghi lại kết quả nghiên cứu các CRM marketing phổ biến, quyết định phạm vi cho phiên bản đầu (MVP), và lộ trình tiếp theo. Mã nguồn nằm tại `backend/crm/`.

Module **Hệ thống giá & Báo giá** (báo giá hoàn thiện, vật tư, nhà thầu): xem [QUOTATION.md](QUOTATION.md).

## 1. Nghiên cứu nhanh: CRM marketing chuyên nghiệp thường có gì

Tham khảo HubSpot Marketing Hub, Salesforce Marketing Cloud, Zoho CRM, Mailchimp/Brevo và các giải pháp tương tự. Nhóm tính năng cốt lõi:

| Nhóm | Tính năng điển hình | Ưu tiên |
|---|---|---|
| Quản lý liên hệ | Hồ sơ contact, dedupe theo email/SĐT, tag, nguồn (source), lịch sử tương tác | P0 |
| Vòng đời (lifecycle) | Subscriber → Lead → MQL → SQL → Customer → Churned | P0 |
| Consent & hủy đăng ký | Lưu bằng chứng đồng ý, link hủy đăng ký, không gửi cho người chưa đồng ý | P0 (bắt buộc pháp lý) |
| Phân khúc (segment) | Lọc động theo stage/tag/hành vi, xem trước số lượng | P0 |
| Chiến dịch email | Soạn thảo, cá nhân hóa, gửi theo segment, theo dõi trạng thái | P0 |
| Timeline hoạt động | Mọi sự kiện (tạo, đổi stage, đồng ý, gửi mail, mở/click) trên một dòng thời gian | P0 |
| Import/Export | Import CSV có ánh xạ cột, export có kiểm soát | P1 |
| Form & landing capture | Form nhúng, webhook từ website/Facebook Lead Ads | P1 |
| Automation / workflow | Chuỗi email theo trigger (drip), chấm điểm lead (lead scoring) | P1 |
| Báo cáo & phân tích | Phễu chuyển đổi, tỷ lệ mở/click, ROI theo kênh | P1 |
| Đa kênh | SMS brandname, Zalo OA, Messenger | P2 |
| Tích hợp | Google Ads/Meta CAPI, Google Sheets, Zapier/webhook, kế toán | P2 |
| Phân quyền & audit | Vai trò (admin/marketer/viewer), audit log | P2 |

## 2. Bối cảnh Việt Nam cần lưu ý

- **Nghị định 13/2023/NĐ-CP (bảo vệ dữ liệu cá nhân)**: cần có sự đồng ý rõ ràng trước khi dùng dữ liệu cho marketing, lưu lại bằng chứng đồng ý và cho phép rút đồng ý / yêu cầu xóa dữ liệu. MVP đã có `marketing_consent`, nhật ký `consent_granted` / `consent_withdrawn`, và endpoint xóa contact. **Nên có luật sư/chuyên gia pháp lý rà soát lại trước khi vận hành thật.**
- **Chống spam email**: cần SPF/DKIM/DMARC cho tên miền gửi, link hủy đăng ký trong mọi email (MVP mới có endpoint hủy, chưa có link trong email).
- **Kênh phổ biến**: Zalo OA và SMS brandname thường quan trọng hơn email với khách Việt. Đây là lộ trình P2.

## 3. Phạm vi MVP đã build

Đã làm (có test):

- Contacts: tạo (dedupe theo email, chuẩn hóa email/tag), sửa, tìm/lọc theo stage, tag, từ khóa; xóa (right-to-erasure).
- Timeline (`crm_activities`): ghi lại tạo mới, đổi stage, đồng ý/rút đồng ý, hủy đăng ký, gửi email.
- Hủy đăng ký: contact bị loại khỏi mọi chiến dịch sau đó.
- Segments: lọc theo stage + tag (ANY) + consent; xem trước số lượng.
- Campaigns: tạo nháp → gửi một lần (chặn gửi lại), cá nhân hóa `{{first_name}}`, chỉ gửi cho contact đã đồng ý và chưa hủy đăng ký.
- Phễu (funnel): đếm contact theo từng stage.

Chưa làm (cố ý để ngoài MVP):

- Gửi email thật: hiện dùng `LogEmailSender` (chỉ ghi log). Cần thay bằng SMTP/SES/SendGrid.
- Gửi hàng loạt bất đồng bộ (queue/worker) — gửi trực tiếp trong request chỉ phù hợp vài trăm người.
- Theo dõi mở/click, bounce, unsubscribe link có chữ ký (signed token).
- Import CSV, xác thực (auth), phân quyền, giao diện người dùng (frontend).
- Automation/drip, lead scoring, đa kênh.

## 4. Thiết kế dữ liệu

```
crm_contacts ──< crm_activities        (timeline, chỉ thêm, không sửa)
crm_contacts >──< crm_tags             (qua crm_contact_tags)
crm_segments   (lưu filter dạng JSON, không lưu danh sách thành viên)
crm_campaigns >── crm_segments         (segment_id, có thể null = toàn bộ đã đồng ý)
```

Quyết định:

- Segment lưu **điều kiện lọc**, không lưu danh sách thành viên, nên luôn đúng với dữ liệu hiện tại.
- Điều kiện gửi mail luôn loại `unsubscribed = true`, và mặc định yêu cầu `marketing_consent = true`.
- Timeline là bảng chỉ thêm (append-only) để làm bằng chứng khi kiểm tra.
- Dùng SQLAlchemy 2.0 nên chuyển được từ SQLite sang PostgreSQL bằng biến môi trường `CRM_DATABASE_URL`.

## 5. API (prefix `/api/crm`)

| Method | Đường dẫn | Mô tả |
|---|---|---|
| POST | `/contacts` | Tạo contact (409 nếu trùng email) |
| GET | `/contacts?stage=&tag=&q=&limit=&offset=` | Danh sách, lọc, phân trang |
| GET | `/contacts/{id}` | Chi tiết + timeline |
| PATCH | `/contacts/{id}` | Cập nhật, ghi nhận đổi stage/consent |
| POST | `/contacts/{id}/unsubscribe` | Hủy đăng ký |
| DELETE | `/contacts/{id}` | Xóa hẳn (204) |
| POST | `/segments` | Tạo segment |
| GET | `/segments/{id}/preview` | Số lượng + mẫu contact |
| POST | `/campaigns` | Tạo chiến dịch nháp |
| GET | `/campaigns/{id}` | Chi tiết chiến dịch |
| POST | `/campaigns/{id}/send` | Gửi (một lần) |
| GET | `/funnel` | Số lượng theo từng stage |

## 6. Chạy thử

```bash
cd backend
pip install -r requirements-dev.txt   # hoặc chỉ cần fastapi, sqlalchemy, pydantic
python -m pytest                      # toàn bộ test CRM + báo giá
uvicorn crm.app:app --reload          # http://localhost:8000/docs
```

Lưu ý: `pydantic==2.5.0` trong `requirements.txt` không có wheel cho Python 3.13 (chỉ tới 3.12). Đã kiểm thử với `fastapi==0.104.1`, `pydantic==2.9.2`, `sqlalchemy==2.0.36` trên Python 3.13. Nên dùng Python 3.11/3.12 nếu muốn giữ nguyên pin cũ.

## 7. Lộ trình đề xuất

1. **Sprint 1 (xong MVP)**: contacts, timeline, consent, segment, campaign nháp.
2. **Sprint 2**: tích hợp nhà cung cấp email thật, link hủy đăng ký có chữ ký, queue gửi nền, webhook mở/click/bounce.
3. **Sprint 3**: import CSV, form capture, auth + phân quyền, frontend (danh sách contact, phễu, soạn chiến dịch).
4. **Sprint 4**: automation (drip), lead scoring, báo cáo ROI theo kênh.
5. **Sprint 5**: Zalo OA / SMS brandname, tích hợp Meta/Google Ads.
