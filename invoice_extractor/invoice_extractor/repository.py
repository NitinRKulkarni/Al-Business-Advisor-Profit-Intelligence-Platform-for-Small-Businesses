"""
Persistence layer for parsed invoices.

Design note (PM/architecture): storage is behind an interface so the
extraction/parse logic never depends on a specific database. Default is
DynamoDB (natural fit for Lambda + S3, serverless). Swap in a relational
repository later without touching the parser or the Lambda handler.

Primary key strategy:
  - Partition key: file_id   (unique per uploaded PDF)
  - Attribute:     invoice_id (business invoice number; also indexed if you
                   add a GSI for lookups by invoice number)
"""
from __future__ import annotations

import abc
from typing import Dict, Optional

from .models import Invoice


class InvoiceRepository(abc.ABC):
    """Storage contract for invoices."""

    @abc.abstractmethod
    def save(self, invoice: Invoice) -> None:
        ...

    @abc.abstractmethod
    def get_by_file_id(self, file_id: str) -> Optional[dict]:
        ...


class DynamoDBInvoiceRepository(InvoiceRepository):
    """
    Stores invoices in a DynamoDB table.

    Expected table:
      - Partition key: file_id (String)
    Optional (recommended) Global Secondary Index:
      - invoice_id-index on invoice_id for lookups by invoice number.
    """

    def __init__(self, table_name: str, region_name: Optional[str] = None, dynamo_resource=None):
        # Imported lazily so local/unit tests don't require boto3/AWS creds.
        if dynamo_resource is None:
            import boto3

            dynamo_resource = boto3.resource("dynamodb", region_name=region_name)
        self._table = dynamo_resource.Table(table_name)

    def save(self, invoice: Invoice) -> None:
        self._table.put_item(Item=invoice.to_dynamo_item())

    def get_by_file_id(self, file_id: str) -> Optional[dict]:
        resp = self._table.get_item(Key={"file_id": file_id})
        return resp.get("Item")


class InMemoryInvoiceRepository(InvoiceRepository):
    """In-memory store for local development and unit tests."""

    def __init__(self):
        self._store: Dict[str, dict] = {}

    def save(self, invoice: Invoice) -> None:
        self._store[invoice.file_id] = invoice.model_dump(mode="json")

    def get_by_file_id(self, file_id: str) -> Optional[dict]:
        return self._store.get(file_id)
