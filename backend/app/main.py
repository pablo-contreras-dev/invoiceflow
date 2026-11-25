from __future__ import annotations

import os
import csv
import hashlib
import json
from io import StringIO
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, create_engine, func, select, text, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./invoiceflow.sqlite3")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class InvoiceRecord(Base):
    __tablename__ = "invoice_records"
    __table_args__ = (
        Index("ix_invoice_supplier_invoice", "supplier_tax_id", "invoice_number"),
        Index("uq_invoice_records_idempotency_key", "idempotency_key", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_name: Mapped[str] = mapped_column(String(200))
    supplier_tax_id: Mapped[str] = mapped_column(String(32))
    invoice_number: Mapped[str] = mapped_column(String(80))
    issue_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    net_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(24), index=True)
    reasons: Mapped[str] = mapped_column(String(500), default="")
    duplicate_of_id: Mapped[int | None] = mapped_column(nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_decision: Mapped[str | None] = mapped_column(String(12), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InvoiceReviewEvent(Base):
    __tablename__ = "invoice_review_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoice_records.id", ondelete="CASCADE"), index=True)
    decision: Mapped[str] = mapped_column(String(12))
    reviewer: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InvoiceIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    supplier_name: Annotated[str, StringConstraints(min_length=2, max_length=200)]
    supplier_tax_id: Annotated[str, StringConstraints(min_length=5, max_length=32)]
    invoice_number: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    issue_date: date
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$", min_length=3, max_length=3)]
    net_amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    tax_amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    total_amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class InvoiceReviewIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    decision: Literal["approved", "rejected"]
    reviewer: Annotated[str, StringConstraints(min_length=2, max_length=120)]
    note: Annotated[str, StringConstraints(max_length=500)] = ""


class InvoiceOut(BaseModel):
    id: int
    status: Literal["validated", "needs_review", "rejected"]
    reasons: list[str]
    duplicate_of_id: int | None
    created_at: datetime
    replayed: bool = False
    review_decision: Literal["approved", "rejected"] | None = None
    reviewed_by: str | None = None
    review_note: str | None = None
    reviewed_at: datetime | None = None


class InvoiceReviewOut(BaseModel):
    id: int
    invoice_id: int
    decision: Literal["approved", "rejected"]
    reviewer: str
    note: str
    created_at: datetime


class InvoiceSummary(InvoiceOut):
    supplier_name: str
    supplier_tax_id: str
    invoice_number: str
    issue_date: date
    currency: str
    net_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal


class InvoicePage(BaseModel):
    items: list[InvoiceSummary]
    total: int
    limit: int
    offset: int


app = FastAPI(
    title="InvoiceFlow API",
    description="Recepción y validación trazable de facturas de demostración.",
    version="0.1.0",
)


def get_session():
    with SessionLocal() as session:
        yield session


def payload_fingerprint(payload: InvoiceIn) -> str:
    normalized = payload.model_dump(mode="json")
    for field in ("net_amount", "tax_amount", "total_amount"):
        normalized[field] = format(getattr(payload, field), ".2f")
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def invoice_output(record: InvoiceRecord, *, replayed: bool = False) -> InvoiceOut:
    return InvoiceOut(
        id=record.id,
        status=record.status,  # type: ignore[arg-type]
        reasons=record.reasons.split(",") if record.reasons else [],
        duplicate_of_id=record.duplicate_of_id,
        created_at=record.created_at,
        replayed=replayed,
        review_decision=record.review_decision,  # type: ignore[arg-type]
        reviewed_by=record.reviewed_by,
        review_note=record.review_note,
        reviewed_at=record.reviewed_at,
    )


@app.get("/health", tags=["operations"])
def health(session: Annotated[Session, Depends(get_session)]) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok", "database": "ok"}


@app.post("/invoices", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED, tags=["invoices"])
def receive_invoice(
    payload: InvoiceIn,
    session: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
    ] = None,
) -> InvoiceOut:
    request_hash = payload_fingerprint(payload)
    if idempotency_key:
        previous_request = session.scalar(
            select(InvoiceRecord).where(InvoiceRecord.idempotency_key == idempotency_key)
        )
        if previous_request is not None:
            if previous_request.request_hash != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency-Key was already used with a different invoice payload",
                )
            return invoice_output(previous_request, replayed=True)

    reasons: list[str] = []
    if payload.net_amount + payload.tax_amount != payload.total_amount:
        reasons.append("total_mismatch")

    duplicate = session.scalar(
        select(InvoiceRecord)
        .where(
            InvoiceRecord.supplier_tax_id == payload.supplier_tax_id,
            InvoiceRecord.invoice_number == payload.invoice_number,
        )
        .order_by(InvoiceRecord.id)
    )
    if duplicate is not None:
        reasons.append("possible_duplicate")

    record = InvoiceRecord(
        **payload.model_dump(),
        status="needs_review" if reasons else "validated",
        reasons=",".join(reasons),
        duplicate_of_id=duplicate.id if duplicate else None,
        idempotency_key=idempotency_key,
        request_hash=request_hash if idempotency_key else None,
        created_at=datetime.now(timezone.utc),
    )
    session.add(record)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if idempotency_key:
            previous_request = session.scalar(
                select(InvoiceRecord).where(InvoiceRecord.idempotency_key == idempotency_key)
            )
            if previous_request is not None:
                if previous_request.request_hash != request_hash:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Idempotency-Key was already used with a different invoice payload",
                    ) from exc
                return invoice_output(previous_request, replayed=True)
        raise HTTPException(status_code=500, detail="Could not persist invoice record") from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail="Could not persist invoice record") from exc
    session.refresh(record)
    return invoice_output(record)


@app.get("/invoices", response_model=InvoicePage, tags=["invoices"])
def list_invoices(
    session: Annotated[Session, Depends(get_session)],
    invoice_status: Annotated[Literal["validated", "needs_review", "rejected"] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InvoicePage:
    query = select(InvoiceRecord)
    count_query = select(func.count()).select_from(InvoiceRecord)
    if invoice_status is not None:
        query = query.where(InvoiceRecord.status == invoice_status)
        count_query = count_query.where(InvoiceRecord.status == invoice_status)
    records = session.scalars(
        query.order_by(InvoiceRecord.created_at.desc(), InvoiceRecord.id.desc()).limit(limit).offset(offset)
    ).all()
    total = session.scalar(count_query) or 0
    items = [
        InvoiceSummary(
            id=row.id,
            status=row.status,  # type: ignore[arg-type]
            reasons=row.reasons.split(",") if row.reasons else [],
            duplicate_of_id=row.duplicate_of_id,
            created_at=row.created_at,
            supplier_name=row.supplier_name,
            supplier_tax_id=row.supplier_tax_id,
            invoice_number=row.invoice_number,
            issue_date=row.issue_date,
            currency=row.currency,
            net_amount=row.net_amount,
            tax_amount=row.tax_amount,
            total_amount=row.total_amount,
            review_decision=row.review_decision,  # type: ignore[arg-type]
            reviewed_by=row.reviewed_by,
            review_note=row.review_note,
            reviewed_at=row.reviewed_at,
        )
        for row in records
    ]
    return InvoicePage(items=items, total=total, limit=limit, offset=offset)


def csv_cell(value: object) -> str:
    """Neutralize spreadsheet formulas in text cells before creating CSV output."""
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


@app.get("/invoices/export.csv", tags=["invoices"])
def export_invoices(
    session: Annotated[Session, Depends(get_session)],
    invoice_status: Annotated[Literal["validated", "needs_review", "rejected"] | None, Query(alias="status")] = None,
) -> StreamingResponse:
    query = select(InvoiceRecord).order_by(InvoiceRecord.created_at.desc(), InvoiceRecord.id.desc())
    if invoice_status is not None:
        query = query.where(InvoiceRecord.status == invoice_status)
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        ["id", "status", "reasons", "duplicate_of_id", "supplier_name", "supplier_tax_id",
         "invoice_number", "issue_date", "currency", "net_amount", "tax_amount", "total_amount",
         "review_decision", "reviewed_by", "review_note", "reviewed_at", "created_at"]
    )
    for row in session.scalars(query):
        writer.writerow(
            [row.id, row.status, row.reasons, row.duplicate_of_id or "", csv_cell(row.supplier_name),
             csv_cell(row.supplier_tax_id), csv_cell(row.invoice_number), row.issue_date.isoformat(),
             row.currency, row.net_amount, row.tax_amount, row.total_amount, row.review_decision or "",
             csv_cell(row.reviewed_by or ""), csv_cell(row.review_note or ""),
             row.reviewed_at.isoformat() if row.reviewed_at else "", row.created_at.isoformat()]
        )
    output.seek(0)
    return StreamingResponse(
        iter(["\ufeff" + output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=invoiceflow-invoices.csv"},
    )


@app.post("/invoices/{invoice_id}/review", response_model=InvoiceReviewOut, status_code=status.HTTP_201_CREATED, tags=["reviews"])
def review_invoice(
    invoice_id: int,
    payload: InvoiceReviewIn,
    session: Annotated[Session, Depends(get_session)],
) -> InvoiceReviewOut:
    record = session.get(InvoiceRecord, invoice_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Invoice record not found")
    if record.status != "needs_review":
        raise HTTPException(status_code=409, detail="Only invoices awaiting review can be resolved")

    now = datetime.now(timezone.utc)
    resulting_status = "validated" if payload.decision == "approved" else "rejected"
    transition = session.execute(
        update(InvoiceRecord)
        .where(InvoiceRecord.id == invoice_id, InvoiceRecord.status == "needs_review")
        .values(
            status=resulting_status,
            review_decision=payload.decision,
            reviewed_by=payload.reviewer,
            review_note=payload.note,
            reviewed_at=now,
        )
    )
    if transition.rowcount != 1:
        session.rollback()
        raise HTTPException(status_code=409, detail="Invoice was already resolved by another review")

    event = InvoiceReviewEvent(
        invoice_id=record.id,
        decision=payload.decision,
        reviewer=payload.reviewer,
        note=payload.note,
        created_at=now,
    )
    session.add(event)
    try:
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail="Could not persist review decision") from exc
    session.refresh(event)
    return InvoiceReviewOut(
        id=event.id,
        invoice_id=event.invoice_id,
        decision=event.decision,  # type: ignore[arg-type]
        reviewer=event.reviewer,
        note=event.note,
        created_at=event.created_at,
    )


@app.get("/invoices/{invoice_id}/reviews", response_model=list[InvoiceReviewOut], tags=["reviews"])
def get_invoice_reviews(
    invoice_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> list[InvoiceReviewOut]:
    if session.get(InvoiceRecord, invoice_id) is None:
        raise HTTPException(status_code=404, detail="Invoice record not found")
    events = session.scalars(
        select(InvoiceReviewEvent)
        .where(InvoiceReviewEvent.invoice_id == invoice_id)
        .order_by(InvoiceReviewEvent.created_at, InvoiceReviewEvent.id)
    ).all()
    return [
        InvoiceReviewOut(
            id=event.id,
            invoice_id=event.invoice_id,
            decision=event.decision,  # type: ignore[arg-type]
            reviewer=event.reviewer,
            note=event.note,
            created_at=event.created_at,
        )
        for event in events
    ]


@app.get("/invoices/{invoice_id}", response_model=InvoiceOut, tags=["invoices"])
def get_invoice(invoice_id: int, session: Annotated[Session, Depends(get_session)]) -> InvoiceOut:
    record = session.get(InvoiceRecord, invoice_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Invoice record not found")
    return invoice_output(record)


app.mount("/dashboard", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="dashboard")
