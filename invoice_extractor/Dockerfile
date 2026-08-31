# Container image for the invoice-extractor Lambda.
# A container is used (instead of a zip) because pdfplumber pulls in native
# dependencies (pypdfium2, Pillow, cryptography) that must match the Lambda runtime.
FROM public.ecr.aws/lambda/python:3.12

# Install Python dependencies into the Lambda task root.
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Copy the application package.
COPY invoice_extractor ${LAMBDA_TASK_ROOT}/invoice_extractor

# Lambda entry point: module_path.function_name
CMD ["invoice_extractor.lambda_handler.handler"]
