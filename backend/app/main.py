from __future__ import annotations

import os
import csv
from io import StringIO
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import Date, DateTime, Index, Numeric, String, create_engine, func, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.exc import SQLAlchemyError


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./invoiceflow.sqlite3")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class InvoiceRecord(Base):
    __tablename__ = "invoice_records"
    __table_args__ = (Index("ix_invoice_supplier_invoice", "supplier_tax_id", "invoice_number"),)

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


class InvoiceOut(BaseModel):
    id: int
    status: Literal["validated", "needs_review"]
    reasons: list[str]
    duplicate_of_id: int | None
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


@app.get("/health", tags=["operations"])
def health(session: Annotated[Session, Depends(get_session)]) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok", "database": "ok"}


@app.post("/invoices", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED, tags=["invoices"])
def receive_invoice(payload: InvoiceIn, session: Annotated[Session, Depends(get_session)]) -> InvoiceOut:
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
        created_at=datetime.now(timezone.utc),
    )
    session.add(record)
    try:
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail="Could not persist invoice record") from exc
    session.refresh(record)
    return InvoiceOut(
        id=record.id,
        status=record.status,  # type: ignore[arg-type]
        reasons=record.reasons.split(",") if record.reasons else [],
        duplicate_of_id=record.duplicate_of_id,
        created_at=record.created_at,
    )


@app.get("/invoices", response_model=InvoicePage, tags=["invoices"])
def list_invoices(
    session: Annotated[Session, Depends(get_session)],
    invoice_status: Annotated[Literal["validated", "needs_review"] | None, Query(alias="status")] = None,
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
    invoice_status: Annotated[Literal["validated", "needs_review"] | None, Query(alias="status")] = None,
) -> StreamingResponse:
    query = select(InvoiceRecord).order_by(InvoiceRecord.created_at.desc(), InvoiceRecord.id.desc())
    if invoice_status is not None:
        query = query.where(InvoiceRecord.status == invoice_status)
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        ["id", "status", "reasons", "duplicate_of_id", "supplier_name", "supplier_tax_id",
         "invoice_number", "issue_date", "currency", "net_amount", "tax_amount", "total_amount", "created_at"]
    )
    for row in session.scalars(query):
        writer.writerow(
            [row.id, row.status, row.reasons, row.duplicate_of_id or "", csv_cell(row.supplier_name),
             csv_cell(row.supplier_tax_id), csv_cell(row.invoice_number), row.issue_date.isoformat(),
             row.currency, row.net_amount, row.tax_amount, row.total_amount, row.created_at.isoformat()]
        )
    output.seek(0)
    return StreamingResponse(
        iter(["\ufeff" + output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=invoiceflow-invoices.csv"},
    )


@app.get("/invoices/{invoice_id}", response_model=InvoiceOut, tags=["invoices"])
def get_invoice(invoice_id: int, session: Annotated[Session, Depends(get_session)]) -> InvoiceOut:
    record = session.get(InvoiceRecord, invoice_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Invoice record not found")
    return InvoiceOut(
        id=record.id,
        status=record.status,  # type: ignore[arg-type]
        reasons=record.reasons.split(",") if record.reasons else [],
        duplicate_of_id=record.duplicate_of_id,
        created_at=record.created_at,
    )


app.mount("/dashboard", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="dashboard")
