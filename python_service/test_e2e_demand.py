import psycopg
import time
import requests
import json

tenant_id = 'a0000000-0000-0000-0000-000000000001'
db_url = 'postgresql://postgres:postgres@localhost:5432/omnicfo_db'

print('Connecting to Postgres...')
with psycopg.connect(db_url, autocommit=True) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT id, processed_status FROM documents WHERE file_type = 'WHATSAPP_CHAT';")
        docs = cur.fetchall()
        print('Existing WhatsApp docs before reset:', docs)
        cur.execute("UPDATE documents SET processed_status = 'PENDING' WHERE file_type = 'WHATSAPP_CHAT';")
        print('Reset documents to PENDING')

print('Waiting 14 seconds for poller and AI execution...')
time.sleep(14)

print('\n--- CHECKING DATABASE DIRECTLY ---')
with psycopg.connect(db_url, autocommit=True) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT id, processed_status FROM documents WHERE file_type = 'WHATSAPP_CHAT';")
        print('Docs status:', cur.fetchall())
        
        cur.execute("SELECT count(*) FROM inventory_items;")
        print('Inventory items count:', cur.fetchone())

        cur.execute("SELECT id, document_id, demand_intelligence IS NOT NULL FROM whatsapp_insights;")
        print('WhatsApp insights:', cur.fetchall())

print('\n--- CHECKING REST APIs ---')
r_demand = requests.get('http://localhost:8080/api/v1/insights/demand', headers={'X-Tenant-ID': tenant_id})
print('Demand status:', r_demand.status_code)
demand_json = r_demand.json()
print('Demand Summary:', json.dumps(demand_json.get('summary'), indent=2))
print('Reorder Recommendations Count:', len(demand_json.get('reorderRecommendations', [])))
print('Stockout Risks Count:', len(demand_json.get('stockoutRisks', [])))
print('Inventory Items in Demand DTO:', len(demand_json.get('inventoryItems', [])))

r_inv = requests.get('http://localhost:8080/api/v1/insights/inventory', headers={'X-Tenant-ID': tenant_id})
print('\nInventory API Status:', r_inv.status_code)
inv_data = r_inv.json()
print('Inventory API items count:', len(inv_data.get('inventoryItems', [])))
if inv_data.get('inventoryItems'):
    print('First 3 inventory items:', json.dumps(inv_data['inventoryItems'][:3], indent=2))
