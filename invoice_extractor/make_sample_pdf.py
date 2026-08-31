"""Write a real sample invoice PDF to disk for Postman uploads."""
from test_real_invoice import build_pdf

out = "sample_invoice.pdf"
with open(out, "wb") as f:
    f.write(build_pdf())
print(f"wrote {out}")
