import json
import sys
import os
from datetime import datetime
from google import genai

MODEL = "gemini-3.6-flash"
CHUNK_SIZE = 80

SYSTEM_PROMPT = """You are a business analyst assistant. You read WhatsApp conversations between a small
business owner and their customers, and extract structured business intelligence.

Always respond with ONLY valid JSON matching the schema given in the user message. No preamble,
no markdown code fences, no explanation text before or after the JSON.

Rules:
- Only extract what is actually present in the chat. Do not invent data.
- Amounts/prices should be extracted as they appear (e.g. "799 rs", "$50"), plus a normalized number if possible.
- sentiment must be one of: "positive", "neutral", "negative", "mixed"
- If a category has nothing relevant, return an empty array for it.
- Keep each insight item short (1-2 sentences) and specific — cite the customer name when known.
"""

JSON_SCHEMA_INSTRUCTIONS = """
Return a JSON object with exactly this shape:

{
  "customer_enquiries": [ { "customer": "", "enquiry": "" } ],
  "products_services_discussed": [ { "item": "", "context": "" } ],
  "orders_leads": [ { "customer": "", "detail": "", "status": "order" | "lead" } ],
  "prices_amounts": [ { "item": "", "amount_text": "", "amount_numeric": null } ],
  "customer_requirements": [ { "customer": "", "requirement": "" } ],
  "complaints_negative_feedback": [ { "customer": "", "issue": "", "severity": "low" | "medium" | "high" } ],
  "action_items": [ { "action": "", "owner": "shop" | "customer", "priority": "low" | "medium" | "high" } ],
  "customer_sentiment": [ { "customer": "", "sentiment": "positive" | "neutral" | "negative" | "mixed", "reason": "" } ],
  "business_recommendations": [ { "recommendation": "", "why": "" } ]
}
"""


def chunk_messages(messages, chunk_size=CHUNK_SIZE):
    for i in range(0, len(messages), chunk_size):
        yield messages[i:i + chunk_size]


def format_chat_for_prompt(messages):
    lines = []
    for m in messages:
        lines.append(f"[{m['date']} {m['time']}] {m['sender']}: {m['message']}")
    return "\n".join(lines)


def extract_insights(client, chat_chunk):
    chat_text = format_chat_for_prompt(chat_chunk)
    user_prompt = f"""Here is a WhatsApp business chat to analyze:

--- CHAT START ---
{chat_text}
--- CHAT END ---

{JSON_SCHEMA_INSTRUCTIONS}
"""
    response = client.models.generate_content(
        model=MODEL,
        contents=user_prompt,
        config={
            "system_instruction": SYSTEM_PROMPT,
            "response_mime_type": "application/json",
        },
    )
    raw_text = response.text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.lower().startswith("json"):
            raw_text = raw_text[4:].strip()
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        print("WARNING: Could not parse JSON from model output. Raw output was:")
        print(raw_text[:500])
        return empty_result()


def empty_result():
    return {
        "customer_enquiries": [], "products_services_discussed": [], "orders_leads": [],
        "prices_amounts": [], "customer_requirements": [], "complaints_negative_feedback": [],
        "action_items": [], "customer_sentiment": [], "business_recommendations": [],
    }


def merge_results(results):
    merged = empty_result()
    for r in results:
        for key in merged:
            merged[key].extend(r.get(key, []))
    return merged


def run_for_messages(client, messages):
    all_results = []
    chunks = list(chunk_messages(messages))
    for idx, chunk in enumerate(chunks, 1):
        print(f"    chunk {idx}/{len(chunks)} ({len(chunk)} messages)")
        all_results.append(extract_insights(client, chunk))
    return merge_results(all_results)


def run(filepath):
    if "GEMINI_API_KEY" not in os.environ:
        print("ERROR: Set GEMINI_API_KEY environment variable first.")
        sys.exit(1)
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    is_per_customer = isinstance(data, list) and data and "messages" in data[0]

    if is_per_customer:
        total_msgs = sum(len(c["messages"]) for c in data)
        print(f"Processing {total_msgs} messages across {len(data)} customer(s)...")
        final = empty_result()
        for c in data:
            print(f"  -> {c['customer_name']} ({len(c['messages'])} messages)")
            result = run_for_messages(client, c["messages"])
            for key in final:
                final[key].extend(result.get(key, []))
        total_messages_analyzed = total_msgs
    else:
        print(f"Processing {len(data)} messages...")
        final = run_for_messages(client, data)
        total_messages_analyzed = len(data)

    final["_meta"] = {
        "source_file": filepath, "total_messages_analyzed": total_messages_analyzed,
        "generated_at": datetime.utcnow().isoformat() + "Z", "model": MODEL,
    }
    out_path = "insights.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)
    print(f"\nDone. Insights saved to {out_path}")
    return final


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extractor.py <parsed_chat.json>")
        sys.exit(1)
    run(sys.argv[1])