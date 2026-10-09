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
