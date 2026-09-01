# WhatsApp Chat → Business Insights Module

**Owner:** Darshan | **Status:** v1 complete and tested

## What this does

Takes a ZIP of exported WhatsApp chats (one `.txt` file per customer) and
produces a single structured JSON file of business insights — customer
enquiries, orders/leads, prices, complaints, action items, sentiment, and
recommendations. Built for informal/unstructured business data, as opposed
to formal invoices or bank statements (separate modules, owned by others).

## Files

| File | Purpose |
|---|---|
| `parser.py` | Unzips per-customer chat exports, cleans and structures raw messages into JSON. No API calls, runs locally, free. |
| `extractor_gemini.py` | Sends parsed messages to Gemini (`gemini-3.6-flash`) and produces `insights.json`. Requires `GEMINI_API_KEY`. |
| `extractor.py` | Same as above but for Claude (`claude-sonnet-4-5-20250929`). Requires `ANTHROPIC_API_KEY`. Use whichever provider has available credits. |
| `dashboard.html` | Standalone viewer — open in any browser, load `insights.json`, no server needed. For demo/QA only, not meant to be the production UI. |

## How to run

```bash
pip install anthropic google-genai      # only need whichever provider you're using
export GEMINI_API_KEY="..."             # or ANTHROPIC_API_KEY

python parser.py your_chat_export.zip           # -> your_chat_export_parsed.json
python extractor_gemini.py your_chat_export_parsed.json   # -> insights.json
```

Input ZIP format: one `.txt` file per customer, filename = customer name,
standard WhatsApp chat export format (both Android `date, time -` and iOS
`[date, time]` timestamp styles supported).

## Output schema (`insights.json`)

```json
{
  "customer_enquiries": [ { "customer": "", "enquiry": "" } ],
  "products_services_discussed": [ { "item": "", "context": "" } ],
  "orders_leads": [ { "customer": "", "detail": "", "status": "order" | "lead" } ],
  "prices_amounts": [ { "item": "", "amount_text": "", "amount_numeric": null } ],
  "customer_requirements": [ { "customer": "", "requirement": "" } ],
  "complaints_negative_feedback": [ { "customer": "", "issue": "", "severity": "low" | "medium" | "high" } ],
  "action_items": [ { "action": "", "owner": "shop" | "customer", "priority": "low" | "medium" | "high" } ],
  "customer_sentiment": [ { "customer": "", "sentiment": "positive" | "neutral" | "negative" | "mixed", "reason": "" } ],
  "business_recommendations": [ { "recommendation": "", "why": "" } ],
  "_meta": { "source_file": "", "total_messages_analyzed": 0, "generated_at": "", "model": "" }
}
```

Empty categories return `[]`, never `null` or omitted keys — safe to iterate
without null-checks downstream.

## Known open item — needs team decision

Two of the shared architecture docs define different destinations for this
output: `design_doc.md`'s `WHATSAPP_CHAT` table (raw messages only, no
insights table) vs `data_specification.md`'s `chat_logs.extracted_intent`
JSONB field (per-message, not per-batch). This module currently just
produces standalone `insights.json` — **whoever picks this up next needs to
confirm which table/field this maps to** before wiring it into the DB layer.

## Tested against

- 8 synthetic customers, 58 messages, Hinglish + English, Android + iOS
  export formats, multi-line messages, price haggling, repeat complaints,
  bulk orders, enquiry-with-no-purchase — all validated correct in manual
  spot-checks (see conversation history / demo for specifics).

## Not yet built

Handwritten bill image extraction (separate input type, vision-based,
planned for next).
