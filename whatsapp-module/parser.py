import re
import json
import sys
import os
import zipfile
import tempfile
from datetime import datetime

LINE_PATTERN = re.compile(
    r"^\[?(\d{1,2}/\d{1,2}/\d{2,4}),?\s(\d{1,2}:\d{2}(?::\d{2})?\s?[APap]?[Mm]?)\]?\s?-?\s?([^:]+):\s(.*)$"
)

SYSTEM_MSG_KEYWORDS = [
    "Messages and calls are end-to-end encrypted",
    "changed the subject",
    "changed this group's icon",
    "added",
    "left",
    "removed",
    "created group",
    "changed the group description",
    "You deleted this message",
    "<Media omitted>",
]


def is_system_message(sender: str, message: str) -> bool:
    for kw in SYSTEM_MSG_KEYWORDS:
        if kw.lower() in message.lower():
            return True
    return False


def parse_chat(filepath: str):
    messages = []
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    for raw_line in lines:
        line = raw_line.strip("\n").strip()
        if not line:
            continue
        match = LINE_PATTERN.match(line)
        if match:
            date, time, sender, message = match.groups()
            sender = sender.strip()
            message = message.strip()
            if is_system_message(sender, message):
                continue
            messages.append({"date": date, "time": time, "sender": sender, "message": message})
        else:
            if messages:
                messages[-1]["message"] += " " + line
    return messages


def clean_messages(messages):
    cleaned = []
    for m in messages:
        text = re.sub(r"\s+", " ", m["message"]).strip()
        if not text or text.lower() in ("<media omitted>", "this message was deleted"):
            continue
        m["message"] = text
        cleaned.append(m)
    return cleaned


def parse_zip(zip_path: str):
    """
    Matches the real workflow: a ZIP containing one chat export .txt per
    customer, filename = customer identity. Returns messages tagged with
    customer_name, ready to align with the WHATSAPP_CHAT table (customer_name,
    message_timestamp, message_text) once a document_id/tenant_id is attached
    upstream by the ingestion API.
    """
    all_messages = []
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        for fname in sorted(os.listdir(tmp)):
            if not fname.lower().endswith(".txt"):
                continue
            customer_name = os.path.splitext(fname)[0]
            fpath = os.path.join(tmp, fname)
            msgs = clean_messages(parse_chat(fpath))
            for m in msgs:
                m["customer_name"] = customer_name
            all_messages.append({"customer_name": customer_name, "messages": msgs})
    return all_messages


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python parser.py <chat_export.txt|chat_export.zip>")
        sys.exit(1)
    filepath = sys.argv[1]

    if filepath.lower().endswith(".zip"):
        per_customer = parse_zip(filepath)
        out_path = filepath.rsplit(".", 1)[0] + "_parsed.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(per_customer, f, indent=2, ensure_ascii=False)
        total = sum(len(c["messages"]) for c in per_customer)
        print(f"Parsed {total} messages across {len(per_customer)} customer(s) -> {out_path}")
        for c in per_customer:
            print(f"  {c['customer_name']}: {len(c['messages'])} messages")
    else:
        parsed = parse_chat(filepath)
        parsed = clean_messages(parsed)
        out_path = filepath.rsplit(".", 1)[0] + "_parsed.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(parsed, f, indent=2, ensure_ascii=False)
        print(f"Parsed {len(parsed)} messages -> {out_path}")
        if parsed:
            print("Sample message:", parsed[0])