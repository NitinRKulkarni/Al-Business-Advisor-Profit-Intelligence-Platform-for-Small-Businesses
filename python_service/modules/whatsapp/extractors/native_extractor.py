import os
import re
from typing import Any, Dict, List, Optional

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
            key = (sanitized["item_name"], sanitized["quantity"], sanitized["quantity_unit"], sanitized["date"], sanitized["timestamp"])
            if key not in seen_keys:
                seen_keys.add(key)
                valid_items.append(sanitized)
    return valid_items

class NativeExtractor:
    """
    Encapsulated Native Rule-Based & Regex Extractor.
    Executes in 0ms with zero token cost for fast deterministic matching.
    """
    def __init__(self):
        units_pattern = r'(?:kg|kilo|kilogram|packet|packets|pack|packs|litre|litres|liter|bottle|bottles|boxes|box|pcs|pieces|units?|bag|bags)'
        self.item_pattern = re.compile(rf'(\d+(?:\.\d+)?)\s*({units_pattern})\s+([A-Za-z\s]{{2,25}})', re.IGNORECASE)

    def extract(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        enquiries: List[Dict[str, Any]] = []
        
        for msg in messages:
            text = msg.get("message") or msg.get("message_text") or ""
            date_str = msg.get("date") or msg.get("message_date") or ""
            time_str = msg.get("time") or msg.get("message_time") or ""
            sender = msg.get("sender") or msg.get("customer_name") or "Customer"

            # Check if this is an uncarried item / negative refusal
            if is_negative_or_refusal(text):
                enquiries.append({
                    "customer": sender,
                    "enquiry": f"Inquiry noted: {text[:100]}"
                })
                continue

            # Check regex matches
            matches = self.item_pattern.findall(text)
            for qty_str, unit_str, name_str in matches:
                candidate = {
                    "item_name": name_str,
                    "quantity": float(qty_str),
                    "quantity_unit": unit_str.lower(),
                    "date": date_str,
                    "timestamp": time_str,
                    "description": text[:80]
                }
                sanitized = sanitize_and_validate_inventory_item(candidate)
                if sanitized:
                    items.append(sanitized)

            # Check known retail products in text
            for prod_name, default_unit, default_qty in KNOWN_RETAIL_PRODUCTS:
                pattern = rf'\b{re.escape(prod_name)}\b'
                if re.search(pattern, text, re.IGNORECASE):
                    candidate = {
                        "item_name": prod_name,
                        "quantity": default_qty,
                        "quantity_unit": default_unit,
                        "date": date_str,
                        "timestamp": time_str,
                        "description": text[:80]
                    }
                    sanitized = sanitize_and_validate_inventory_item(candidate)
                    if sanitized:
                        items.append(sanitized)

        cleaned_items = filter_valid_inventory_items(items)
        confidence = 0.95 if len(cleaned_items) > 0 else 0.0

        return {
            "engine": "NATIVE",
            "items": cleaned_items,
            "confidence": confidence,
            "customer_enquiries": enquiries,
            "customer_sentiment": [
                {
                    "customer": "Summary",
                    "sentiment": "positive" if len(cleaned_items) > 0 else "neutral",
                    "reason": f"Native extractor parsed {len(cleaned_items)} confirmed items."
                }
            ],
            "status": "SUCCESS"
        }
