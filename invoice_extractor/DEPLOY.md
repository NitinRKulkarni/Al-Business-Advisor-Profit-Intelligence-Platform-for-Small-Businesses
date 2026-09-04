# Deploying the Invoice Extractor to AWS

This deploys an S3-triggered Lambda (container image) that parses uploaded PDF
invoices with `pdfplumber` and stores results in DynamoDB.

## Architecture

```
  PDF upload ─▶ S3 bucket ─(ObjectCreated *.pdf)─▶ Lambda (pdfplumber) ─▶ DynamoDB
                                                                            (invoices)
                                                                     key: file_id
                                                                     GSI: invoice_id-index
```

## Prerequisites (install these first — none are on this machine yet)

1. **AWS account + credentials.** Configure once:
   ```powershell
   aws configure
   ```
   (You'll enter Access Key, Secret Key, region e.g. `ap-south-1`.)

2. **AWS CLI** — https://aws.amazon.com/cli/
3. **Docker Desktop** (must be running) — https://www.docker.com/products/docker-desktop/
4. **AWS SAM CLI** — https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html

Verify all three:
```powershell
aws --version
docker --version
sam --version
```

## Deploy (run from the project root: invoice_extractor/)

```powershell
# 1. Build the container image (Docker must be running)
sam build

# 2. Deploy — guided the first time; it prompts for the stack name,
#    region, and the UploadBucketName parameter.
sam deploy --guided
```

During `--guided` you'll set:
- **Stack name**: e.g. `invoice-extractor`
- **Region**: e.g. `ap-south-1`
- **UploadBucketName**: a globally-unique bucket name, e.g. `myco-invoices-2026`
- Accept the IAM capability prompt (SAM creates the Lambda role).

SAM creates an ECR repo, pushes the image, and provisions the S3 bucket,
DynamoDB table, Lambda, and the S3→Lambda trigger.

## Test it

```powershell
# Upload a PDF; the Lambda fires automatically.
aws s3 cp .\some_invoice.pdf s3://<UploadBucketName>/

# Read the stored result (file_id == the S3 object key)
aws dynamodb get-item `
  --table-name invoices `
  --key '{\"file_id\": {\"S\": \"some_invoice.pdf\"}}'
```

Check logs if needed:
```powershell
sam logs --stack-name invoice-extractor --tail
```

## Tear down (avoid ongoing cost)

```powershell
sam delete --stack-name invoice-extractor
```

> Note: the S3 bucket must be empty before the stack can delete it.

## Cost / risk notes

- DynamoDB is `PAY_PER_REQUEST` (no idle cost).
- Lambda + S3 cost only per use; low for typical invoice volumes.
- This creates real, billable resources. Use `sam delete` when done testing.
