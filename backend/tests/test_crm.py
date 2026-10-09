import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from crm.api import get_sender
from crm.app import app
from crm.database import Base, get_db


class RecordingSender:
    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to, subject, body):
        self.sent.append((to, subject, body))


@pytest.fixture
def sender():
    return RecordingSender()


@pytest.fixture
def client(sender):
    # Isolated in-memory DB per test. TestClient is used without `with`, so the app's
    # lifespan (which would create tables on the real crm.db) does not run.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_sender] = lambda: sender
    yield TestClient(app)
    app.dependency_overrides.clear()


def make_contact(client, **overrides):
    payload = {"email": "An.Nguyen@Example.com", "first_name": "An", "marketing_consent": True}
    payload.update(overrides)
    r = client.post("/api/crm/contacts", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_contact_normalizes_email_and_logs_activity(client):
    c = make_contact(client, tags=["Newsletter", " newsletter ", "VIP"])
    assert c["email"] == "an.nguyen@example.com"
    assert c["lifecycle_stage"] == "lead"
    assert c["tags"] == ["newsletter", "vip"]

    detail = client.get(f"/api/crm/contacts/{c['id']}").json()
    types = [a["type"] for a in detail["activities"]]
    assert "created" in types and "consent_granted" in types


def test_duplicate_email_is_rejected(client):
    make_contact(client)
    r = client.post("/api/crm/contacts", json={"email": "an.nguyen@example.com"})
    assert r.status_code == 409


def test_invalid_email_is_rejected(client):
    r = client.post("/api/crm/contacts", json={"email": "not-an-email"})
    assert r.status_code == 422


def test_stage_change_is_recorded_in_timeline(client):
    c = make_contact(client)
    r = client.patch(f"/api/crm/contacts/{c['id']}", json={"lifecycle_stage": "mql"})
    assert r.status_code == 200 and r.json()["lifecycle_stage"] == "mql"
    detail = client.get(f"/api/crm/contacts/{c['id']}").json()
    assert any(a["type"] == "stage_changed" and a["detail"] == "lead -> mql" for a in detail["activities"])


def test_list_filters_by_stage_tag_and_search(client):
    make_contact(client, email="a@x.com", first_name="Lan", tags=["vip"], lifecycle_stage="customer")
    make_contact(client, email="b@x.com", first_name="Minh", tags=["vip"])
    make_contact(client, email="c@x.com", first_name="Hoa")

    assert len(client.get("/api/crm/contacts", params={"stage": "customer"}).json()) == 1
    assert len(client.get("/api/crm/contacts", params={"tag": "VIP"}).json()) == 2
    found = client.get("/api/crm/contacts", params={"q": "minh"}).json()
    assert [c["email"] for c in found] == ["b@x.com"]


def test_segment_respects_consent_and_unsubscribe(client):
    a = make_contact(client, email="a@x.com", tags=["vip"], marketing_consent=True)
    make_contact(client, email="b@x.com", tags=["vip"], marketing_consent=False)
    make_contact(client, email="c@x.com", tags=["vip"], marketing_consent=True)
    client.post(f"/api/crm/contacts/{a['id']}/unsubscribe")

    seg = client.post("/api/crm/segments", json={"name": "VIP", "filters": {"tags": ["vip"]}}).json()
    preview = client.get(f"/api/crm/segments/{seg['id']}/preview").json()
    assert preview["count"] == 1
    assert [c["email"] for c in preview["contacts"]] == ["c@x.com"]


def test_campaign_sends_only_to_eligible_contacts_with_personalization(client, sender):
    make_contact(client, email="a@x.com", first_name="Lan", marketing_consent=True)
    make_contact(client, email="b@x.com", first_name="Minh", marketing_consent=False)
    camp = client.post(
        "/api/crm/campaigns",
        json={"name": "Launch", "subject": "Xin chào", "body": "Chào {{first_name}}!"},
    ).json()

    r = client.post(f"/api/crm/campaigns/{camp['id']}/send")
    assert r.status_code == 200 and r.json()["recipients"] == 1
    assert sender.sent == [("a@x.com", "Xin chào", "Chào Lan!")]

    detail = client.get("/api/crm/contacts", params={"q": "a@x.com"}).json()[0]
    timeline = client.get(f"/api/crm/contacts/{detail['id']}").json()["activities"]
    assert any(a["type"] == "email_sent" for a in timeline)

    assert client.get(f"/api/crm/campaigns/{camp['id']}").json()["status"] == "sent"
    assert client.post(f"/api/crm/campaigns/{camp['id']}/send").status_code == 409


def test_campaign_to_segment_only(client, sender):
    make_contact(client, email="a@x.com", tags=["vip"])
    make_contact(client, email="b@x.com", tags=["new"])
    seg = client.post("/api/crm/segments", json={"name": "VIP", "filters": {"tags": ["vip"]}}).json()
    camp = client.post(
        "/api/crm/campaigns",
        json={"name": "VIP only", "subject": "Hi", "body": "Hello", "segment_id": seg["id"]},
    ).json()
    assert client.post(f"/api/crm/campaigns/{camp['id']}/send").json()["recipients"] == 1
    assert [s[0] for s in sender.sent] == ["a@x.com"]


def test_campaign_with_unknown_segment_is_404(client):
    r = client.post("/api/crm/campaigns", json={"name": "x", "subject": "x", "body": "x", "segment_id": 999})
    assert r.status_code == 404


def test_delete_contact_removes_activities(client):
    c = make_contact(client)
    assert client.delete(f"/api/crm/contacts/{c['id']}").status_code == 204
    assert client.get(f"/api/crm/contacts/{c['id']}").status_code == 404


def test_funnel_counts_every_stage(client):
    make_contact(client, email="a@x.com", lifecycle_stage="customer")
    make_contact(client, email="b@x.com")
    body = client.get("/api/crm/funnel").json()
    assert body["total"] == 2
    assert body["by_stage"]["customer"] == 1 and body["by_stage"]["lead"] == 1
    assert body["by_stage"]["churned"] == 0
