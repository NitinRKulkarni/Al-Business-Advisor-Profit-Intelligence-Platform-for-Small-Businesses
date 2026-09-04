import re
from typing import Any, Dict, List

QUERY_TRIGGERS = [
    r"\b(do we have|is there|available|in stock|stock hai|hai kya|milega|chahiye|bhej do)\b",
    r"\b(urgent|deliver|bhejo|kal tak|next week|need|require|order)\b",
    r"\b(price|rate|cost|kitne ka|bhav|quotation|discount)\b"
]

QTY_UNIT_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(kg|kilos?|kilograms?|litres?|liter|l|packets?|pkts?|boxes?|bags?|tins?|pcs|pieces|gm|grams?)?",
    re.IGNORECASE
)

NON_ITEM_TERMS = {
    "do", "we", "have", "enough", "for", "next", "week", "bhaiya", "hai", "kya",
    "chahiye", "sir", "madam", "ji", "urgent", "please", "plz", "thanks", "hello",
    "is", "there", "available", "to", "send", "deliver", "order"
}

class NativeWhatsAppQueryExtractor:
    """
    100% Native NLP Regex & Lexicon Query Extractor.
    Extracts questions and demanded items from chat messages without external LLM APIs.
    """
    def extract_queries(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        extracted_queries = []

        # Comprehensive conversational stopwords & noise patterns
        STOP_WORDS = {
            "namaste", "bhaiya", "bhai", "sir", "madam", "ji", "hello", "hi", "hey",
            "do", "we", "have", "enough", "for", "next", "week", "hai", "kya", "hain",
            "chahiye", "urgent", "urgently", "kal", "aaj", "subah", "shaam", "tomorrow",
            "please", "plz", "thanks", "thank", "you", "is", "there", "in", "stock",
            "available", "to", "send", "deliver", "delivery", "order", "what", "price",
            "rate", "cost", "kitna", "kitne", "ka", "ki", "ke", "ko", "se", "aur", "also",
            "need", "and", "if", "the", "of", "a", "an",
            "tuesday", "monday", "wednesday", "thursday", "friday", "saturday", "sunday"
        }

        # Common known patterns:
        # e.g., "25 packet Amul Butter", "50kg Basmati Rice", "price of Toor Dal 50kg"
        REGEX_PATTERNS = [
            # Pattern 1: Qty + Unit + Product (e.g., 25 packet Amul Butter, 50kg Basmati Rice)
            re.compile(r"(\d+(?:\.\d+)?)\s*(?:kg|kilos?|litres?|liter|l|packets?|pkts?|boxes?|bags?|tins?|pcs|pieces)?\s+([A-Za-z\s]{2,30})", re.IGNORECASE),
            # Pattern 2: Product + Qty + Unit (e.g., Toor Dal 50kg, Sugar 30kg)
            re.compile(r"([A-Za-z\s]{2,30})\s+(\d+(?:\.\d+)?)\s*(kg|kilos?|litres?|liter|l|packets?|pkts?|boxes?|bags?|tins?|pcs|pieces)", re.IGNORECASE),
        ]

        for msg in messages:
            text = str(msg.get("message") or msg.get("message_text") or "").strip()
            if not text:
                continue

            # Don't parse the owner's own replies
            sender_name = str(msg.get("sender") or "")
            if sender_name.lower() in {"you", "admin", "owner", "me"}:
                continue

            text_lower = text.lower()
            is_query = any(re.search(pat, text_lower) for pat in QUERY_TRIGGERS) or "?" in text or any(w in text_lower for w in ["kg", "packet", "litre", "need", "urgent", "price"])

            if is_query:
                # 1. Parse Quantity & Unit
                match = QTY_UNIT_PATTERN.search(text_lower)
                qty = float(match.group(1)) if match else 1.0
                unit = match.group(2) if (match and match.group(2)) else "units"

                # 2. Extract Demanded Item Name
                item_name = ""

                # Try pattern 1: e.g. "25 packet Amul Butter" -> "Amul Butter"
                p1_match = re.search(r"\d+(?:\.\d+)?\s*(?:kg|kilos?|kilograms?|litres?|liter|l|packets?|pkts?|boxes?|bags?|tins?|pcs|pieces)?\s+([A-Za-z\s]{2,30})", text, re.IGNORECASE)
                if p1_match:
                    candidate = p1_match.group(1).strip()
                    cand_words = [w for w in re.sub(r"[?.,!]", "", candidate).split() if w.lower() not in STOP_WORDS]
                    if cand_words:
                        item_name = " ".join(cand_words[:2]).title()

                # Try pattern 2: e.g. "price of Toor Dal 50kg" -> "Toor Dal"
                if not item_name or len(item_name) < 2:
                    p2_match = re.search(r"(?:of|for|need|send|is|is there)?\s+([A-Za-z\s]{2,25})\s+\d+(?:\.\d+)?\s*(?:kg|kilos?|litres?|liter|l|packets?|pkts?|boxes?|bags?|tins?|pcs|pieces)", text, re.IGNORECASE)
                    if p2_match:
                        candidate = p2_match.group(1).strip()
                        cand_words = [w for w in re.sub(r"[?.,!]", "", candidate).split() if w.lower() not in STOP_WORDS]
                        if cand_words:
                            item_name = " ".join(cand_words[:2]).title()

                # Fallback extraction from cleaned sentence
                if not item_name:
                    cleaned = re.sub(r"[?.,!0-9]", " ", text)
                    cand_words = [w for w in cleaned.split() if w.lower() not in STOP_WORDS]
                    item_name = " ".join(cand_words[:2]).title() if cand_words else "Inquired Item"

                # 3. Classify Intent
                intent = "PRICE_INQUIRY" if any(w in text_lower for w in ["price", "rate", "cost", "kitne", "bhav"]) else "STOCK_INQUIRY"
                
                # 4. Classify Timeframe
                timeframe = "next week" if "next week" in text_lower else ("tomorrow" if ("kal" in text_lower or "tomorrow" in text_lower) else "immediate")

                extracted_queries.append({
                    "customer_name": msg.get("customer_name") or msg.get("sender", "Customer"),
                    "sender": msg.get("sender", "Unknown"),
                    "raw_message": text,
                    "intent": intent,
                    "item_demanded": item_name,
                    "requested_quantity": qty,
                    "requested_unit": unit,
                    "timeframe": timeframe,
                    "urgency_level": "HIGH" if any(w in text_lower for w in ["urgent", "asap", "emergency"]) else "NORMAL",
                    "sentiment": "NEUTRAL",
                    "structured_payload": {"timeframe": timeframe, "source": "native_regex"}
                })

        return extracted_queries
