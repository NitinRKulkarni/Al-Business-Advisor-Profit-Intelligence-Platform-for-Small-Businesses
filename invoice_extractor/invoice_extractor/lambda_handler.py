"""
AWS Lambda entry point (S3-triggered).

Flow (the "post-ingestion" pipeline step):
  1. A PDF is uploaded to S3 (ingestion).
  2. S3 fires an ObjectCreated event -> this Lambda.
  3. We download the PDF, parse it with pdfplumber, and persist the
     structured invoice to DynamoDB keyed by file_id / invoice_id.

Environment variables:
  INVOICE_TABLE   - DynamoDB table name (required for real deploys)
  AWS_REGION      - provided automatically by Lambda

Configure the S3 trigger to only fire on the `.pdf` suffix.
"""
from __future__ import annotations

import logging
import os
import urllib.parse
from typing import Any, Dict

import boto3

from .parser import parse_invoice_pdf
from .repository import DynamoDBInvoiceRepository

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_s3 = boto3.client("s3")


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    table_name = os.environ.get("INVOICE_TABLE")
    if not table_name:
        raise RuntimeError("INVOICE_TABLE environment variable is not set")

    repo = DynamoDBInvoiceRepository(table_name=table_name)
    results = []

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

        # file_id: stable identifier for the uploaded PDF. Using the S3 key
        # keeps it unique and traceable back to the source object.
        file_id = key

        logger.info("Processing s3://%s/%s", bucket, key)

        pdf_bytes = _s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        invoice = parse_invoice_pdf(pdf_bytes, file_id=file_id)
        repo.save(invoice)

        logger.info(
            "Stored invoice file_id=%s invoice_id=%s items=%d",
            invoice.file_id, invoice.invoice_id, len(invoice.line_items),
        )
        results.append({"file_id": invoice.file_id, "invoice_id": invoice.invoice_id})

    return {"statusCode": 200, "processed": results}
