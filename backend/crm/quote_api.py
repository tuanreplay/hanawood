from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .models import PriceItem, Quote
from .quote_render import render_quote
from .quote_schemas import (
    PriceItemCreate,
    PriceItemOut,
    PriceItemUpdate,
    QuoteContent,
    QuoteCreate,
    QuoteOut,
    QuoteStatus,
    QuoteSummary,
    QuoteType,
    RejectIn,
)
from .quote_service import (
    QuoteInputError,
    QuoteStateError,
    accept_quote,
    create_quote,
    list_quotes,
    load_quote,
    reject_quote,
    revise_quote,
    send_quote,
    to_out,
    to_summary,
    update_quote,
)

router = APIRouter(prefix="/api/crm", tags=["pricing & quotes"])


# ---- Price catalog --------------------------------------------------------

@router.post("/price-items", response_model=PriceItemOut, status_code=status.HTTP_201_CREATED)
def create_price_item(data: PriceItemCreate, db: Session = Depends(get_db)):
    item = PriceItem(**data.model_dump())
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "price item code already exists")
    return item


@router.get("/price-items", response_model=list[PriceItemOut])
def list_price_items(
    category: str | None = None,
    q: str | None = Query(None, max_length=100),
    active: bool | None = True,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(PriceItem)
    if category:
        stmt = stmt.where(PriceItem.category == category)
    if active is not None:
        stmt = stmt.where(PriceItem.active.is_(active))
    if q:
        pattern = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(PriceItem.code).like(pattern), func.lower(PriceItem.name).like(pattern)))
    return db.scalars(stmt.order_by(PriceItem.code).limit(limit).offset(offset)).all()


@router.patch("/price-items/{item_id}", response_model=PriceItemOut)
def update_price_item(item_id: int, data: PriceItemUpdate, db: Session = Depends(get_db)):
    # Quotes snapshot prices per line, so catalog changes never alter quotes already issued.
    item = db.get(PriceItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "price item not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


# ---- Quotes ---------------------------------------------------------------

def _quote_or_404(db: Session, quote_id: int) -> Quote:
    quote = load_quote(db, quote_id)
    if quote is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "quote not found")
    return quote


def _run(db: Session, quote_id: int, action) -> QuoteOut:
    try:
        quote = action()
    except QuoteInputError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    except QuoteStateError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return to_out(load_quote(db, quote.id if quote is not None else quote_id))


@router.post("/quotes", response_model=QuoteOut, status_code=status.HTTP_201_CREATED)
def create(data: QuoteCreate, db: Session = Depends(get_db)):
    return _run(db, 0, lambda: create_quote(db, data))


@router.get("/quotes", response_model=list[QuoteSummary])
def list_(
    status_: QuoteStatus | None = Query(None, alias="status"),
    quote_type: QuoteType | None = None,
    contact_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return [to_summary(q) for q in list_quotes(db, status_, quote_type, contact_id, limit, offset)]


@router.get("/quotes/{quote_id}", response_model=QuoteOut)
def get(quote_id: int, db: Session = Depends(get_db)):
    return to_out(_quote_or_404(db, quote_id))


@router.put("/quotes/{quote_id}", response_model=QuoteOut)
def update(quote_id: int, data: QuoteContent, db: Session = Depends(get_db)):
    quote = _quote_or_404(db, quote_id)
    return _run(db, quote_id, lambda: update_quote(db, quote, data))


@router.post("/quotes/{quote_id}/send", response_model=QuoteOut)
def send(quote_id: int, db: Session = Depends(get_db)):
    quote = _quote_or_404(db, quote_id)
    return _run(db, quote_id, lambda: send_quote(db, quote))


@router.post("/quotes/{quote_id}/accept", response_model=QuoteOut)
def accept(quote_id: int, db: Session = Depends(get_db)):
    quote = _quote_or_404(db, quote_id)
    return _run(db, quote_id, lambda: accept_quote(db, quote))


@router.post("/quotes/{quote_id}/reject", response_model=QuoteOut)
def reject(quote_id: int, data: RejectIn, db: Session = Depends(get_db)):
    quote = _quote_or_404(db, quote_id)
    return _run(db, quote_id, lambda: reject_quote(db, quote, data.reason))


@router.post("/quotes/{quote_id}/revise", response_model=QuoteOut, status_code=status.HTTP_201_CREATED)
def revise(quote_id: int, db: Session = Depends(get_db)):
    quote = _quote_or_404(db, quote_id)
    return _run(db, quote_id, lambda: revise_quote(db, quote))


@router.get("/quotes/{quote_id}/print", response_class=HTMLResponse)
def print_quote(quote_id: int, db: Session = Depends(get_db)):
    return HTMLResponse(render_quote(to_out(_quote_or_404(db, quote_id))))
