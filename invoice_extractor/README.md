# Invoice Extractor (PDF → structured text → database)

Post-ingestion module that converts a formal PDF invoice into structured data
using `pdfplumber`, then stores it keyed by `file_id` / `invoice_id`.

## Structure

```
invoice_extractor/
├── requirements.txt
├── run_local.py                 # test parsing locally, no AWS needed
├── README.md
└── invoice_extractor/
    ├── __init__.py
    ├── models.py                # Invoice + LineItem schema (Pydantic)
    ├── parser.py                # pdfplumber extraction + field parsing
    ├── repository.py            # DynamoDB / in-memory storage
    └── lambda_handler.py        # S3-triggered AWS Lambda entry point
```

## Fields extracted

- Invoice number, invoice date, due date
- Customer name, GST number
- Line items: description, quantity, rate/unit, total rate
- Total amount, tax, total amount with tax

## Local test

```bash
pip install -r requirements.txt
python run_local.py sample_invoice.pdf
```

## Deploy on AWS (Lambda + S3 + DynamoDB)

1. **DynamoDB table**: create `invoices` with partition key `file_id` (String).
   Optional: add a GSI on `invoice_id` for lookups by invoice number.

2. **Package the Lambda.** `pdfplumber` has native deps, so use a Lambda layer
   or container image. Simplest reliable path is a container image:

   ```dockerfile
   FROM public.ecr.aws/lambda/python:3.12
   COPY requirements.txt .
   RUN pip install -r requirements.txt
   COPY invoice_extractor ./invoice_extractor
   CMD ["invoice_extractor.lambda_handler.handler"]
   ```

3. **Env vars**: set `INVOICE_TABLE=invoices` on the Lambda.

4. **IAM**: grant the Lambda `s3:GetObject` on the source bucket and
   `dynamodb:PutItem`/`GetItem` on the table.

5. **Trigger**: add an S3 `ObjectCreated` notification filtered to `.pdf`.

## Tuning

Invoice layouts differ. The regexes and table-column matching in `parser.py`
are a starting point — refine them against your real templates. If any
invoices are scanned images (not digital PDFs), add an OCR step (AWS Textract)
before parsing, since `pdfplumber` only reads embedded text.
```
