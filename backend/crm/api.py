from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Campaign, Contact, Segment, Tag
from .schemas import (
    CampaignCreate,
    CampaignOut,
    ContactCreate,
    ContactDetail,
    ContactOut,
    ContactUpdate,
    FunnelOut,
    SegmentCreate,
    SegmentFilters,
    SegmentOut,
    SegmentPreview,
    SendResult,
    Stage,
)
from .services import (
    STAGES,
    CampaignAlreadySent,
    DuplicateContact,
    EmailSender,
    LogEmailSender,
    audience_query,
    create_contact,
    funnel,
    send_campaign,
    unsubscribe_contact,
    update_contact,
)

router = APIRouter(prefix="/api/crm", tags=["crm"])


def get_sender() -> EmailSender:
    return LogEmailSender()


def _contact_or_404(db: Session, contact_id: int) -> Contact:
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "contact not found")
    return contact


# ---- Contacts -------------------------------------------------------------

@router.post("/contacts", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
def create_contact_endpoint(data: ContactCreate, db: Session = Depends(get_db)):
    try:
        return create_contact(db, data)
    except DuplicateContact:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already exists")


@router.get("/contacts", response_model=list[ContactOut])
def list_contacts(
    stage: Stage | None = None,
    tag: str | None = None,
    q: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Contact)
    if stage:
        stmt = stmt.where(Contact.lifecycle_stage == stage)
    if tag:
        stmt = stmt.where(Contact.tags.any(Tag.name == tag.strip().lower()))
    if q:
        pattern = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Contact.email).like(pattern),
                func.lower(Contact.first_name).like(pattern),
                func.lower(Contact.last_name).like(pattern),
            )
        )
    return db.scalars(stmt.order_by(Contact.id).limit(limit).offset(offset)).all()


@router.get("/contacts/{contact_id}", response_model=ContactDetail)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    return _contact_or_404(db, contact_id)


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
def patch_contact(contact_id: int, data: ContactUpdate, db: Session = Depends(get_db)):
    return update_contact(db, _contact_or_404(db, contact_id), data)


@router.post("/contacts/{contact_id}/unsubscribe", response_model=ContactOut)
def unsubscribe(contact_id: int, db: Session = Depends(get_db)):
    return unsubscribe_contact(db, _contact_or_404(db, contact_id))


@router.delete("/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    # Hard delete for right-to-erasure requests; activities cascade.
    db.delete(_contact_or_404(db, contact_id))
    db.commit()


# ---- Segments -------------------------------------------------------------

@router.post("/segments", response_model=SegmentOut, status_code=status.HTTP_201_CREATED)
def create_segment(data: SegmentCreate, db: Session = Depends(get_db)):
    segment = Segment(name=data.name, filters=data.filters.model_dump())
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


@router.get("/segments/{segment_id}/preview", response_model=SegmentPreview)
def preview_segment(segment_id: int, limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    segment = db.get(Segment, segment_id)
    if segment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "segment not found")
    stmt = audience_query(SegmentFilters(**segment.filters))
    count = db.scalar(select(func.count()).select_from(stmt.subquery()))
    contacts = db.scalars(stmt.limit(limit)).all()
    return SegmentPreview(count=count, contacts=contacts)


# ---- Campaigns ------------------------------------------------------------

@router.post("/campaigns", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
def create_campaign(data: CampaignCreate, db: Session = Depends(get_db)):
    if data.segment_id is not None and db.get(Segment, data.segment_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "segment not found")
    campaign = Campaign(**data.model_dump())
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "campaign not found")
    return campaign


@router.post("/campaigns/{campaign_id}/send", response_model=SendResult)
def send(campaign_id: int, db: Session = Depends(get_db), sender: EmailSender = Depends(get_sender)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "campaign not found")
    try:
        recipients = send_campaign(db, campaign, sender)
    except CampaignAlreadySent:
        raise HTTPException(status.HTTP_409_CONFLICT, "campaign already sent")
    return SendResult(campaign_id=campaign.id, recipients=recipients)


# ---- Reporting ------------------------------------------------------------

@router.get("/funnel", response_model=FunnelOut)
def get_funnel(db: Session = Depends(get_db)):
    by_stage = funnel(db)
    return FunnelOut(total=sum(by_stage.values()), by_stage={s: by_stage.get(s, 0) for s in STAGES})
