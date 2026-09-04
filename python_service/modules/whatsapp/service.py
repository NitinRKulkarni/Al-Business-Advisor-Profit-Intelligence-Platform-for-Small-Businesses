import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_current_dir = Path(__file__).resolve().parent
if str(_current_dir) not in sys.path:
    sys.path.insert(0, str(_current_dir))

from python_service.modules.whatsapp.parser import parse_zip, parse_chat, clean_messages
from python_service.modules.whatsapp.demand_intelligence import compute_native_demand_intelligence, generate_demand_intelligence
from python_service.modules.whatsapp.extractors.query_extractor import NativeWhatsAppQueryExtractor
from python_service.db.document_store import get_document_store

# Non-inventory conversational phrases, time/date markers, and filler words to block
NON_INVENTORY_TERMS = {
    # Time and date words
    "ghante", "ghanta", "hours", "hour", "hr", "hrs", "min", "mins", "minute", "minutes",
    "baje", "din", "day", "days", "kal", "aaj", "parso", "mahine", "months", "month", "am", "pm",
    "today", "tomorrow", "yesterday", "morning", "evening", "afternoon", "night", "week",
    # Conversational verbs, particles & fillers
    "mein", "me", "ho", "jayegi", "jayega", "gaya", "gayi", "hoga", "hogi", "bhi",
    "chahiye", "bhej", "bhejo", "bhej do", "bhej dena", "karo", "kardo", "kar dena",
    "hai", "hain", "tha", "thi", "the", "nahi", "na", "mat", "theek", "theek hai",
    "bhaiya", "bhai", "sir", "madam", "ji", "ok", "okay", "done", "yes", "no", "plz", "please",
    "thanks", "thank you", "dhanyawad", "shukriya", "hello", "hi", "hey",
    "delivery", "deliver", "address", "location", "payment", "paid", "gpay", "phonepe",
    "paytm", "cash", "cod", "rupaye", "rupees", "rs", "inr", "discount", "offer",
    "urgent", "asap", "emergency", "order", "orders", "status", "bill", "invoice", "receipt",
    "and", "the", "for", "with", "from", "you", "your", "send", "sent", "call", "msg"
}

ALLOWED_PHYSICAL_UNITS = {
    "kg", "kilo", "kilogram", "kilograms", "g", "gm", "gram", "grams",
    "litre", "litres", "liter", "liters", "l", "ml", "millilitre",
    "packet", "packets", "pkt", "pkts", "pack", "packs",
    "piece", "pieces", "pc", "pcs",
    "box", "boxes", "bottle", "bottles", "bag", "bags", "tin", "tins", "carton", "cartons",
    "can", "cans", "jar", "jars", "units", "unit"
}

KNOWN_RETAIL_PRODUCTS = [
    ("Atta", "kg", 10.0),
    ("Basmati Rice", "kg", 25.0),
    ("Mustard Oil", "litre", 5.0),
    ("Toor Dal", "kg", 10.0),
    ("Sugar", "kg", 5.0),
    ("Tea Powder", "packet", 2.0),
    ("Maggi Noodles", "packet", 12.0),
    ("Sunflower Oil", "litre", 5.0),
    ("Wheat Flour", "kg", 10.0),
    ("Moong Dal", "kg", 5.0),
    ("Chana Dal", "kg", 5.0),
    ("Fortune Oil", "litre", 5.0),
    ("Amul Butter", "packet", 5.0),
    ("Tata Salt", "packet", 10.0),
]

GENERIC_CONTAINER_NOUNS = {
    "box", "boxes", "packet", "packets", "bottle", "bottles", "item", "items",
    "piece", "pieces", "unit", "units", "bag", "bags", "pack", "packs",
    "carton", "cartons", "tin", "tins", "can", "cans", "jar", "jars",
    "kilo", "kg", "litre", "litres", "gram", "grams", "gm", "product", "products"
}

NEGATIVE_REFUSAL_PATTERNS = [
    r'\bnahi\b', r'\bnot available\b', r'\bno stock\b', r'\bnahi rakhte\b',
    r'\bnahi hai\b', r'\bout of stock\b', r'\bfinished\b', r'\bkhatam\b',
    r'\bband hai\b', r'\bavailable nahi\b', r'\bsirf\b.*\bnahi\b'
]

def is_negative_or_refusal(text: str) -> bool:
    """Checks if a message line expresses product unavailability, refusal, or negation."""
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in NEGATIVE_REFUSAL_PATTERNS)

def sanitize_and_validate_inventory_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Validates that a parsed item represents a genuine physical inventory/retail product
    and not conversational dialogue, time indications, or sentence remnants.
    Returns the sanitized item dictionary or None if invalid.
    """
    if not isinstance(item, dict):
        return None

    raw_name = item.get("item_name") or item.get("name") or ""
    if not isinstance(raw_name, str):
        return None

    # Strip symbols and collapse spaces
    clean_name = re.sub(r'[^a-zA-Z0-9\s\(\)\-\.]', ' ', raw_name).strip()
    words = clean_name.lower().split()
    if not words:
        return None

    # Disallow names that are too short, excessively long, or purely numeric
    if len(clean_name) < 2 or len(clean_name) > 40 or clean_name.isnumeric():
        return None

    # Check if all words are conversational noise/stopwords
    if all(w in NON_INVENTORY_TERMS for w in words):
        return None

    # Strip conversational noise and adjectives from candidate name
    TRAILING_STRIP_WORDS = {
        "bhi", "mein", "me", "ka", "ki", "ke", "ko", "se", "aur", "and", "the", "ek", "do",
        "urgently", "urgent", "fast", "jaldi", "please", "plz", "today", "tomorrow", "asap",
        "bhej", "dena", "bhejo", "chahiye", "send", "needed", "need", "hai", "hain", "rakhte", "ho"
    }
    filtered_words = [w for w in words if w not in TRAILING_STRIP_WORDS]
    if not filtered_words:
        return None

    # Reject if primary words are temporal or conversational markers
    if any(w in {"ghante", "ghanta", "hours", "hour", "baje", "minutes", "mins", "today", "tomorrow", "delivery", "payment", "address", "call", "cold drink"} for w in filtered_words):
        return None

    # Validate unit
    raw_unit = str(item.get("quantity_unit") or item.get("unit") or "units").lower().strip()
    # Reject temporal units
    if raw_unit in {"ghante", "ghanta", "hours", "hour", "baje", "min", "mins", "minutes", "am", "pm", "days", "din", "sec"}:
        return None
    unit = raw_unit if raw_unit in ALLOWED_PHYSICAL_UNITS else "units"

    # Validate quantity
    qty = item.get("quantity")
    try:
        qty_val = float(qty) if qty is not None else 1.0
        if qty_val <= 0 or qty_val > 10000:
            return None
    except (ValueError, TypeError):
        qty_val = 1.0

    final_name = " ".join(filtered_words).title()
    
    # Reject standalone container nouns without a distinguishing product name
    if final_name.lower() in GENERIC_CONTAINER_NOUNS:
        return None

    if len(final_name) < 2 or final_name.lower() in NON_INVENTORY_TERMS:
        return None

    return {
        "item_name": final_name,
        "quantity": qty_val,
        "quantity_unit": unit,
        "date": str(item.get("date") or ""),
        "timestamp": str(item.get("timestamp") or ""),
        "description": str(item.get("description") or "")[:120]
    }

def filter_valid_inventory_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Passes a list of items through strict inventory validation.
    """
    valid_items: List[Dict[str, Any]] = []
    seen_keys = set()
    for it in items:
        sanitized = sanitize_and_validate_inventory_item(it)
        if sanitized:
            # Deduplicate exact same mention in the exact same timestamp if repeated
            key = (sanitized["item_name"], sanitized["quantity"], sanitized["quantity_unit"], sanitized["date"], sanitized["timestamp"])
            if key not in seen_keys:
                seen_keys.add(key)
                valid_items.append(sanitized)
    return valid_items

from extractors import (
    NativeExtractor,
    GeminiExtractor,
    MockExtractor,
    ExtractionEngineRouter,
    sanitize_and_validate_inventory_item,
    filter_valid_inventory_items
)

def _heuristic_extract_items(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Legacy alias preserved for backwards-compatibility; delegates to NativeExtractor."""
    extractor = NativeExtractor()
    result = extractor.extract(messages)
    return result.get("items", [])

async def process_whatsapp_chat(raw_bytes: bytes, document_id: str, organization_id: str) -> Dict[str, Any]:
    """
    Processes WhatsApp chat export (ZIP or TXT) via the Multi-Engine Extraction Strategy
    (CASCADE | NATIVE | GEMINI | MOCK), computes Demand Intelligence, persists into PostgreSQL,
    and returns verified items.
    """
    is_zip = raw_bytes.startswith(b"PK\x03\x04") or raw_bytes.startswith(b"PK\x05\x06")
    suffix = ".zip" if is_zip else ".txt"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
        tmp_file.write(raw_bytes)
        tmp_path = tmp_file.name

    try:
        all_flattened_messages: List[Dict[str, Any]] = []
        if is_zip:
            per_customer = parse_zip(tmp_path)
            for cust in per_customer:
                customer_name = cust.get("customer_name", "Unknown")
                for msg in cust.get("messages", []):
                    msg["customer_name"] = customer_name
                    all_flattened_messages.append(msg)
        else:
            raw_msgs = clean_messages(parse_chat(tmp_path))
            for msg in raw_msgs:
                msg["customer_name"] = msg.get("sender", "Unknown")
                all_flattened_messages.append(msg)

        # 1. Execute 100% Native NLP Query Extractor (Extracts customer queries & demand signals)
        query_extractor = NativeWhatsAppQueryExtractor()
        extracted_queries = query_extractor.extract_queries(all_flattened_messages)
        
        # Fallback: if no explicit questions were tagged, extract conversational order mentions
        if not extracted_queries and all_flattened_messages:
            native_items_res = NativeExtractor().extract(all_flattened_messages)
            for it in native_items_res.get("items", []):
                extracted_queries.append({
                    "customer_name": all_flattened_messages[0].get("customer_name", "Customer"),
                    "sender": all_flattened_messages[0].get("sender", "Unknown"),
                    "raw_message": it.get("description") or f"Order mention: {it.get('item_name')}",
                    "intent": "STOCK_INQUIRY",
                    "item_demanded": it.get("item_name"),
                    "requested_quantity": it.get("quantity", 1.0),
                    "requested_unit": it.get("quantity_unit", "units"),
                    "timeframe": "upcoming",
                    "urgency_level": "NORMAL",
                    "sentiment": "NEUTRAL",
                    "structured_payload": {}
                })

        engine_used = "NATIVE_DETERMINISTIC"

        # 2. Execute Deterministic Mathematical Demand Intelligence Analysis against live PostgreSQL stock
        demand_intelligence = compute_native_demand_intelligence(
            organization_id=organization_id,
            queries=extracted_queries,
            raw_messages=all_flattened_messages
        )

        insights: Dict[str, Any] = {
            "customer_enquiries": extracted_queries,
            "products_services_discussed": [q.get("item_demanded") for q in extracted_queries if q.get("item_demanded")],
            "orders_leads": [],
            "prices_amounts": [],
            "customer_requirements": [],
            "complaints_negative_feedback": [],
            "action_items": [],
            "customer_sentiment": [],
            "business_recommendations": demand_intelligence.get("reorder_recommendations", []),
            "demand_intelligence": demand_intelligence,
            "extraction_engine": engine_used
        }

        # 3. Persist to PostgreSQL (messages, extracted queries in whatsapp_queries, and whatsapp_insights)
        store = get_document_store()
        try:
            store.save_whatsapp_data(
                document_id=document_id,
                organization_id=organization_id,
                parsed_messages=all_flattened_messages,
                insights=insights,
                extracted_queries=extracted_queries,
            )
            store.set_document_status(document_id, "COMPLETED")
        finally:
            store.close()

        return {
            "total_messages": len(all_flattened_messages),
            "total_customer_queries": len(extracted_queries),
            "extraction_engine": engine_used,
            "insights": insights,
            "demand_intelligence": demand_intelligence,
            "data": {
                "message_count": len(all_flattened_messages),
                "customers_found": len(set(m.get("customer_name") for m in all_flattened_messages if m.get("customer_name"))),
                "queries_extracted": len(extracted_queries),
                "demand_intelligence": demand_intelligence,
                "insights": insights,
            }
        }

    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
