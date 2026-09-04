import os
import json
import re
from typing import Any, Dict, List, Optional
from .native_extractor import filter_valid_inventory_items

GEMINI_SYSTEM_PROMPT = """You are an expert Kirana & Retail Inventory Assistant.
You read WhatsApp conversations between a retail store owner and customers, and extract genuine inventory items, customer inquiries, and sentiment.

CRITICAL EXTRACTION RULES:
1. Only extract genuine physical retail products actually ordered or held in stock (e.g., Atta, Rice, Oil, Dal, Sugar, Biscuits, Maggi).
2. Do NOT extract items that the store does NOT have, items that are refused or unavailable ("nahi rakhte", "cold drink nahi", "out of stock"). Put these in 'customer_enquiries'.
3. Standalone packaging container words ("box", "packet", "bottle", "piece", "bag") must NOT be extracted as item names unless qualified by a real product name (e.g., "Dry Fruit Mix Box").
4. Output strictly valid JSON matching the schema given. No markdown code fences, no preamble.
"""

GEMINI_SCHEMA_INSTRUCTIONS = """
Return ONLY a JSON object with this shape:
{
  "items": [
    {
      "item_name": "Mustard Oil",
      "quantity": 5.0,
      "quantity_unit": "litre",
      "date": "21/06/24",
      "timestamp": "14:00",
      "description": "5L mustard oil bottle request"
    }
  ],
  "customer_enquiries": [
    {
      "customer": "Customer Name",
      "enquiry": "Brief summary of inquiry or unmet demand"
    }
  ],
  "customer_sentiment": [
    {
      "customer": "Summary",
      "sentiment": "positive",
      "reason": "Brief summary reason"
    }
  ]
}
"""

class GeminiExtractor:
    """
    Token-Optimized Gemini Extractor using Google GenAI SDK.
    """
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    def extract(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is missing or unconfigured.")

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ImportError("google-genai package is not installed.")

        client = genai.Client(api_key=self.api_key)
        
        chat_lines = []
        for m in messages:
            d = m.get("date") or m.get("message_date") or ""
            t = m.get("time") or m.get("message_time") or ""
            s = m.get("sender") or m.get("customer_name") or "User"
            msg = m.get("message") or m.get("message_text") or ""
            chat_lines.append(f"[{d} {t}] {s}: {msg}")

        chat_text = "\n".join(chat_lines[:150]) # Truncate to save tokens

        prompt = f"{GEMINI_SYSTEM_PROMPT}\n\n{GEMINI_SCHEMA_INSTRUCTIONS}\n\n--- CHAT LOG START ---\n{chat_text}\n--- CHAT LOG END ---"

        try:
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            raw_text = response.text.strip()
            # Clean possible markdown wrap
            raw_text = re.sub(r'^```json\s*', '', raw_text)
            raw_text = re.sub(r'\s*```$', '', raw_text)
            
            data = json.loads(raw_text)
            raw_items = data.get("items", [])
            valid_items = filter_valid_inventory_items(raw_items)

            return {
                "engine": "GEMINI",
                "items": valid_items,
                "confidence": 0.98 if len(valid_items) > 0 else 0.5,
                "customer_enquiries": data.get("customer_enquiries", []),
                "customer_sentiment": data.get("customer_sentiment", []),
                "status": "SUCCESS"
            }
        except Exception as e:
            return {
                "engine": "GEMINI",
                "items": [],
                "confidence": 0.0,
                "customer_enquiries": [],
                "customer_sentiment": [],
                "status": f"ERROR: {str(e)}"
            }
