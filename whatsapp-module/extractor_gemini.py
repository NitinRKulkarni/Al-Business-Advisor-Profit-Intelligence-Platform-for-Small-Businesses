import json
import sys
import os
import time
from datetime import datetime
from google import genai
from google.genai import errors as genai_errors

MODEL = "gemini-3.6-flash"
CHUNK_SIZE = 80

SYSTEM_PROMPT = """You are a data-entry assistant. You read WhatsApp conversations between a small
business owner and their customers, and extract every item mentioned in the chat.

Always respond with ONLY valid JSON matching the schema given in the user message. No preamble,
no markdown code fences, no explanation text before or after the JSON.

Rules:
- Only extract what is actually present in the chat. Do not invent data.
- List every distinct item mentioned, one entry per item per mention.
"""

JSON_SCHEMA_INSTRUCTIONS = """
Return a JSON object with exactly this shape:

{
  "items": [ { "item_name": "", "quantity": null, "quantity_unit": "", "date": "", "timestamp": "", "description": "" } ]
}

- item_name: the product name as mentioned (e.g. "atta", "kurta", "Maggi")
- quantity: the numeric quantity if stated (e.g. 5), null if not stated
- quantity_unit: the unit as stated (e.g. "kg", "packet", "litre", "piece"), "" if not stated
- date: the message's date (from the chat line), in the same format as it appears in the chat
- timestamp: the message's time (from the chat line), in the same format as it appears in the chat
- description: any other relevant detail about this item mention (price, condition, context) in 1 short phrase
"""


def chunk_messages(messages, chunk_size=CHUNK_SIZE):
    for i in range(0, len(messages), chunk_size):
        yield messages[i:i + chunk_size]


def format_chat_for_prompt(messages):
    lines = []
    for m in messages:
        lines.append(f"[{m['date']} {m['time']}] {m['sender']}: {m['message']}")
    return "\n".join(lines)


def extract_insights(client, chat_chunk, max_retries=4):
    chat_text = format_chat_for_prompt(chat_chunk)
    user_prompt = f"""Here is a WhatsApp business chat to analyze:

--- CHAT START ---
{chat_text}
--- CHAT END ---

{JSON_SCHEMA_INSTRUCTIONS}
"""
    response = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=user_prompt,
                config={
                    "system_instruction": SYSTEM_PROMPT,
                    "response_mime_type": "application/json",
                },
            )
            break
        except genai_errors.ServerError as e:
            wait = 2 ** attempt  # 2, 4, 8, 16 seconds
            print(f"    Server busy (attempt {attempt}/{max_retries}), retrying in {wait}s...")
            if attempt == max_retries:
                print(f"    Giving up on this chunk after {max_retries} attempts: {e}")
                return empty_result()
            time.sleep(wait)

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
    return {"items": []}


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