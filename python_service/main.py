from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from python_service.api.router import router as extraction_router
from python_service.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    description="Unified AI Intelligence Engine for Omni-CFO: PDF Invoices, Image Receipts, and WhatsApp Chat Analytics."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(extraction_router)

@app.get("/health")
def health_check():
    return {
        "status": "UP",
        "service": settings.APP_NAME,
        "active_modules": ["pdf_invoice", "image_invoice", "whatsapp"]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("python_service.main:app", host=settings.HOST, port=settings.PORT, reload=True)
