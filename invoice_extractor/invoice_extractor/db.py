"""
Database access for the extraction service.

Responsibilities:
  1. Look up a `documents` row by document_id and return the tenant plus the
     original PDF bytes (from a file path, or from an in-DB bytes column).
  2. Persist extraction results into `invoices` + `invoice_line_items`,
     upserting on document_id so re-extraction is idempotent.

Two backends implement the same interface:
  - PostgresDocumentStore : production, talks to the same DB as the Java app.
  - SqliteDocumentStore   : zero-setup local verification / tests.

Selection: DB_BACKEND=postgres|sqlite (default: postgres if DATABASE_URL is
set, else sqlite). See get_store().
"""
from __future__ import annotations

import abc
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from .models import Invoice


class DocumentNotFoundError(Exception):
    """Raised when no documents row exists for the given id."""


class PdfNotAvailableError(Exception):
    """Row exists but the PDF bytes/path could not be resolved/read."""


@dataclass
class DocumentRow:
    document_id: str
    organization_id: str
    file_name: str
    file_type: str
    pdf_bytes: bytes


class DocumentStore(abc.ABC):
    @abc.abstractmethod
    def get_document(self, document_id: str) -> DocumentRow: ...

    @abc.abstractmethod
    def save_invoice(self, document_id: str, organization_id: str,
                     invoice: Invoice, confidence: Optional[float] = None) -> str:
        """Persist invoice + line items; return the invoice id."""

    @abc.abstractmethod
    def set_document_status(self, document_id: str, status: str) -> None: ...

    def close(self) -> None:  # optional override
        pass


# --------------------------------------------------------------------------- #
# Shared helper: resolve PDF bytes from a row that may carry a path or bytes.
# --------------------------------------------------------------------------- #
def _resolve_pdf(file_path: Optional[str], file_data: Optional[bytes],
                 file_name: str, document_id: str) -> bytes:
    if file_data:
        return bytes(file_data)
    if file_path:
        # Allow an override root for portability (e.g. a shared upload dir).
        root = os.environ.get("UPLOAD_DIR")
        candidate = os.path.join(root, os.path.basename(file_path)) if root else file_path
        for path in (candidate, file_path):
            if path and os.path.exists(path):
                with open(path, "rb") as f:
                    return f.read()
    # Last resort: UPLOAD_DIR + file_name.
    root = os.environ.get("UPLOAD_DIR")
    if root:
        guess = os.path.join(root, file_name)
        if os.path.exists(guess):
            with open(guess, "rb") as f:
                return f.read()
    raise PdfNotAvailableError(
        f"Could not locate PDF for document_id={document_id}. "
        f"Set documents.file_path/file_data, or UPLOAD_DIR to the upload folder."
    )


# --------------------------------------------------------------------------- #
# Postgres backend
# --------------------------------------------------------------------------- #
class PostgresDocumentStore(DocumentStore):
    def __init__(self, dsn: Optional[str] = None):
        import psycopg  # lazy import

        self._psycopg = psycopg
        self._dsn = dsn or _default_pg_dsn()
        self._conn = psycopg.connect(self._dsn, autocommit=False)

    def get_document(self, document_id: str) -> DocumentRow:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT organization_id, file_name, file_type, file_path, file_data
                FROM documents WHERE id = %s
                """,
                (document_id,),
            )
            row = cur.fetchone()
        if not row:
            raise DocumentNotFoundError(document_id)
        organization_id, file_name, file_type, file_path, file_data = row
        pdf = _resolve_pdf(file_path, file_data, file_name, document_id)
        return DocumentRow(document_id, str(organization_id), file_name, file_type, pdf)

    def save_invoice(self, document_id, organization_id, invoice, confidence=None) -> str:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO invoices (
                    document_id, organization_id, invoice_number, invoice_date,
                    due_date, customer_name, gst_number, total_amount, tax,
                    total_amount_with_tax, confidence_score
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (document_id) DO UPDATE SET
                    invoice_number        = EXCLUDED.invoice_number,
                    invoice_date          = EXCLUDED.invoice_date,
                    due_date              = EXCLUDED.due_date,
                    customer_name         = EXCLUDED.customer_name,
                    gst_number            = EXCLUDED.gst_number,
                    total_amount          = EXCLUDED.total_amount,
                    tax                   = EXCLUDED.tax,
                    total_amount_with_tax = EXCLUDED.total_amount_with_tax,
                    confidence_score      = EXCLUDED.confidence_score
                RETURNING id
                """,
                (
                    document_id, organization_id, invoice.invoice_number,
                    invoice.invoice_date, invoice.due_date, invoice.customer_name,
                    invoice.gst_number, invoice.total_amount, invoice.tax,
                    invoice.total_amount_with_tax, confidence,
                ),
            )
            invoice_id = cur.fetchone()[0]
            # Replace line items for idempotent re-extraction.
            cur.execute("DELETE FROM invoice_line_items WHERE invoice_id = %s", (invoice_id,))
            for i, li in enumerate(invoice.line_items, start=1):
                cur.execute(
                    """
                    INSERT INTO invoice_line_items (
                        invoice_id, organization_id, item_description,
                        quantity, rate_per_unit, total_rate, line_no
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (invoice_id, organization_id, li.description, li.quantity,
                     li.rate_per_unit, li.total_rate, i),
                )
        self._conn.commit()
        return str(invoice_id)

    def set_document_status(self, document_id: str, status: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE documents SET processed_status = %s WHERE id = %s",
                (status, document_id),
            )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


# --------------------------------------------------------------------------- #
# SQLite backend (local verification / tests)
# --------------------------------------------------------------------------- #
class SqliteDocumentStore(DocumentStore):
    def __init__(self, path: Optional[str] = None):
        import sqlite3

        self._sqlite3 = sqlite3
        self._path = path or os.environ.get("SQLITE_PATH", "extraction.db")
        self._conn = sqlite3.connect(self._path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema()

    def _ensure_schema(self):
        cur = self._conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY, business_name TEXT
            );
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_hash TEXT,
                processed_status TEXT DEFAULT 'PENDING',
                file_path TEXT,
                file_data BLOB
            );
            CREATE TABLE IF NOT EXISTS invoices (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL UNIQUE,
                organization_id TEXT NOT NULL,
                invoice_number TEXT, invoice_date TEXT, due_date TEXT,
                customer_name TEXT, gst_number TEXT,
                total_amount TEXT, tax TEXT, total_amount_with_tax TEXT,
                confidence_score REAL
            );
            CREATE TABLE IF NOT EXISTS invoice_line_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id TEXT NOT NULL,
                organization_id TEXT NOT NULL,
                item_description TEXT, quantity TEXT, rate_per_unit TEXT,
                total_rate TEXT, line_no INTEGER
            );
            """
        )
        self._conn.commit()

    def get_document(self, document_id: str) -> DocumentRow:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT organization_id, file_name, file_type, file_path, file_data "
            "FROM documents WHERE id = ?",
            (document_id,),
        )
        row = cur.fetchone()
        if not row:
            raise DocumentNotFoundError(document_id)
        organization_id, file_name, file_type, file_path, file_data = row
        pdf = _resolve_pdf(file_path, file_data, file_name, document_id)
        return DocumentRow(document_id, organization_id, file_name, file_type, pdf)

    def save_invoice(self, document_id, organization_id, invoice, confidence=None) -> str:
        import uuid

        cur = self._conn.cursor()
        cur.execute("SELECT id FROM invoices WHERE document_id = ?", (document_id,))
        existing = cur.fetchone()
        invoice_id = existing[0] if existing else str(uuid.uuid4())

        def s(v):
            return None if v is None else str(v)

        if existing:
            cur.execute(
                """UPDATE invoices SET invoice_number=?, invoice_date=?, due_date=?,
                   customer_name=?, gst_number=?, total_amount=?, tax=?,
                   total_amount_with_tax=?, confidence_score=? WHERE id=?""",
                (invoice.invoice_number, s(invoice.invoice_date), s(invoice.due_date),
                 invoice.customer_name, invoice.gst_number, s(invoice.total_amount),
                 s(invoice.tax), s(invoice.total_amount_with_tax), confidence, invoice_id),
            )
            cur.execute("DELETE FROM invoice_line_items WHERE invoice_id = ?", (invoice_id,))
        else:
            cur.execute(
                """INSERT INTO invoices (id, document_id, organization_id, invoice_number,
                   invoice_date, due_date, customer_name, gst_number, total_amount, tax,
                   total_amount_with_tax, confidence_score)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (invoice_id, document_id, organization_id, invoice.invoice_number,
                 s(invoice.invoice_date), s(invoice.due_date), invoice.customer_name,
                 invoice.gst_number, s(invoice.total_amount), s(invoice.tax),
                 s(invoice.total_amount_with_tax), confidence),
            )
        for i, li in enumerate(invoice.line_items, start=1):
            cur.execute(
                """INSERT INTO invoice_line_items (invoice_id, organization_id,
                   item_description, quantity, rate_per_unit, total_rate, line_no)
                   VALUES (?,?,?,?,?,?,?)""",
                (invoice_id, organization_id, li.description, s(li.quantity),
                 s(li.rate_per_unit), s(li.total_rate), i),
            )
        self._conn.commit()
        return invoice_id

    def set_document_status(self, document_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE documents SET processed_status = ? WHERE id = ?",
            (status, document_id),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def _default_pg_dsn() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    db = os.environ.get("PGDATABASE", "omnicfo_db")
    user = os.environ.get("PGUSER", "postgres")
    pwd = os.environ.get("PGPASSWORD", "postgres")
    return f"host={host} port={port} dbname={db} user={user} password={pwd}"


def get_store() -> DocumentStore:
    """Pick a backend from env. Defaults to sqlite when no Postgres is configured."""
    backend = os.environ.get("DB_BACKEND")
    if not backend:
        backend = "postgres" if os.environ.get("DATABASE_URL") else "sqlite"
    if backend == "postgres":
        return PostgresDocumentStore()
    return SqliteDocumentStore()
