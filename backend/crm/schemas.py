from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Stage = Literal["subscriber", "lead", "mql", "sql", "customer", "churned"]
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def _clean_tags(tags: list[str]) -> list[str]:
    return list(dict.fromkeys(t.strip().lower() for t in tags if t.strip()))


class ContactCreate(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=255)
    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=32)
    source: str | None = Field(None, max_length=64)
    lifecycle_stage: Stage = "lead"
    marketing_consent: bool = False
    tags: list[str] = Field(default_factory=list)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, v: list[str]) -> list[str]:
        return _clean_tags(v)


class ContactUpdate(BaseModel):
    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=32)
    lifecycle_stage: Stage | None = None
    marketing_consent: bool | None = None
    tags: list[str] | None = None

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _clean_tags(v)


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    detail: str
    created_at: datetime


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    first_name: str | None
    last_name: str | None
    phone: str | None
    source: str | None
    lifecycle_stage: str
    marketing_consent: bool
    unsubscribed: bool
    tags: list[str]
    created_at: datetime

    @field_validator("tags", mode="before")
    @classmethod
    def _tag_names(cls, v):
        return [t.name if hasattr(t, "name") else t for t in v]


class ContactDetail(ContactOut):
    activities: list[ActivityOut]


class SegmentFilters(BaseModel):
    stages: list[Stage] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list, description="Contact matches if it has ANY of these tags")
    require_consent: bool = True

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, v: list[str]) -> list[str]:
        return _clean_tags(v)


class SegmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    filters: SegmentFilters = Field(default_factory=SegmentFilters)


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    filters: SegmentFilters


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    subject: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=100_000, description="Supports {{first_name}} placeholder")
    segment_id: int | None = None


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    subject: str
    body: str
    segment_id: int | None
    status: str
    recipient_count: int
    created_at: datetime
    sent_at: datetime | None


class SendResult(BaseModel):
    campaign_id: int
    recipients: int


class SegmentPreview(BaseModel):
    count: int
    contacts: list[ContactOut]


class FunnelOut(BaseModel):
    total: int
    by_stage: dict[str, int]
