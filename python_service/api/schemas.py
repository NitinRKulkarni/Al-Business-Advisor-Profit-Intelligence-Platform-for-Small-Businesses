from typing import Any, Dict, Optional
from pydantic import BaseModel

class ExtractionRequest(BaseModel):
    document_id: str
    source: str  # 'invoice', 'image_invoice', 'whatsapp'

class ExtractionResponse(BaseModel):
    status: str
    document_id: str
    source: str
    confidence_score: Optional[float] = None
    extracted_data: Dict[str, Any]
    message: Optional[str] = None
