# WhatsApp Chat → Item Extraction Module

**Owner:** Darshan | **Status:** v1 complete and tested

## What this does

Takes a ZIP of exported WhatsApp chats (one `.txt` file per customer) and
produces a structured JSON list of every item mentioned across the chats —
item name, quantity, unit, date, timestamp, and a short description.

## Files

| File | Purpose |
|---|---|
| `parser.py` | Unzips per-customer chat exports, cleans and structures raw messages into JSON. No API calls, runs locally, free. |
| `extractor_gemini.py` | Sends parsed messages to Gemini (`gemini-3.6-flash`) and produces `insights.json`. Requires `GEMINI_API_KEY`. Includes automatic retry (up to 4 attempts, exponential backoff) on transient server errors. |
| `extractor.py` | Same idea but for Claude (`claude-sonnet-4-5-20250929`). Requires `ANTHROPIC_API_KEY`. Use whichever provider has available credits. |

## How to run

```bash
pip install google-genai      # or anthropic, depending on provider
export GEMINI_API_KEY="..."   # or ANTHROPIC_API_KEY

python parser.py your_chat_export.zip                      # -> your_chat_export_parsed.json
python extractor_gemini.py your_chat_export_parsed.json    # -> insights.json
```

Input ZIP format: one `.txt` file per customer, filename = customer name,
standard WhatsApp chat export format (both Android `date, time -` and iOS
`[date, time]` timestamp styles supported).

## Output schema (`insights.json`)

```json
{
  "items": [
    {
      "item_name": "",
      "quantity": null,
      "quantity_unit": "",
      "date": "",
      "timestamp": "",
      "description": ""
    }
  ],
  "_meta": { "source_file": "", "total_messages_analyzed": 0, "generated_at": "", "model": "" }
}
```

- `item_name` — product/item as mentioned in the chat
- `quantity` — number if stated, else `null`
- `quantity_unit` — unit as stated (kg, packet, litre, etc.), else `""`
- `date` / `timestamp` — taken directly from the chat message's own date/time, kept in the same format as the original export
- `description` — short free-text context (price, condition, notes)

One entry per item per mention — a single order/message can produce multiple
entries (e.g. a mixed dry-fruit box gets broken into its individual
components).

## Known open item — needs team decision

Two of the shared architecture docs define different destinations for chat
data: `design_doc.md`'s `WHATSAPP_CHAT` table (raw messages only) vs
`data_specification.md`'s `chat_logs.extracted_intent` JSONB field
(per-message). This module produces standalone `insights.json` —
**whoever picks this up next needs to confirm which table/field this maps
to** before wiring it into the DB layer.

## Tested against

8 synthetic customers, 58 messages, Hinglish + English, Android + iOS export
formats, multi-line messages, price haggling, bulk orders — output manually
spot-checked correct (see `insights_sample_output.json` for a real example).

## Scope note

Handwritten bill image extraction is **not** part of this module — confirmed
with mentor that this module covers WhatsApp chats only; handwritten bills
are being handled by another teammate.
