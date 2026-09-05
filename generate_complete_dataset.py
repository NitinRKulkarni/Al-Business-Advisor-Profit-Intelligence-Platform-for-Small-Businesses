
"""
Complete 2-Month Test Dataset Generator for Omni-CFO Platform.
Generates:
  1. test_datasets/1_inventory_stock.csv (25+ items with stock & reorder levels)
  2. test_datasets/invoices_pdf/ (20 matching PDF invoices from July-Aug 2026)
  3. test_datasets/invoice_images/ (Sample image invoices for OCR testing)
  4. test_datasets/3_bank_statement_2months.csv (Cohesive daily cash flow matching invoice remarks)
  5. test_datasets/2_whatsapp_customer_chats.txt & .zip (Realistic customer demand conversations)
  6. test_datasets/seed_2months_data.sql (Direct SQL seed for PostgreSQL vyapaar_db)
"""
import os
import io
import zipfile
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT

# Base Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DATASETS_DIR = os.path.join(BASE_DIR, "test_datasets")
INVOICES_PDF_DIR = os.path.join(TEST_DATASETS_DIR, "invoices_pdf")
INVOICES_IMG_DIR = os.path.join(TEST_DATASETS_DIR, "invoice_images")
os.makedirs(INVOICES_PDF_DIR, exist_ok=True)
os.makedirs(INVOICES_IMG_DIR, exist_ok=True)

# ----------------------------------------------------------------------
# 1. INVENTORY DATA (25 Items)
# ----------------------------------------------------------------------
INVENTORY_ITEMS = [
    {"item_name": "Basmati Rice Royal", "quantity": 45, "quantity_unit": "kg", "unit_price": 95.00, "reorder_level": 50, "category": "Grains"},
    {"item_name": "Sona Masoori Rice", "quantity": 180, "quantity_unit": "kg", "unit_price": 58.00, "reorder_level": 60, "category": "Grains"},
    {"item_name": "Whole Wheat Sharbati Atta", "quantity": 250, "quantity_unit": "kg", "unit_price": 46.00, "reorder_level": 80, "category": "Grains"},
    {"item_name": "Toor Dal Premium", "quantity": 30, "quantity_unit": "kg", "unit_price": 145.00, "reorder_level": 40, "category": "Pulses"},
    {"item_name": "Moong Dal Washed", "quantity": 75, "quantity_unit": "kg", "unit_price": 120.00, "reorder_level": 35, "category": "Pulses"},
    {"item_name": "Chana Dal Super", "quantity": 90, "quantity_unit": "kg", "unit_price": 88.00, "reorder_level": 30, "category": "Pulses"},
    {"item_name": "Urad Dal Gota", "quantity": 40, "quantity_unit": "kg", "unit_price": 135.00, "reorder_level": 30, "category": "Pulses"},
    {"item_name": "Fortune Refined Sunflower Oil", "quantity": 35, "quantity_unit": "litre", "unit_price": 155.00, "reorder_level": 50, "category": "Oils"},
    {"item_name": "Dhara Pure Mustard Oil", "quantity": 60, "quantity_unit": "litre", "unit_price": 165.00, "reorder_level": 30, "category": "Oils"},
    {"item_name": "Amul Pure Cow Ghee", "quantity": 20, "quantity_unit": "litre", "unit_price": 620.00, "reorder_level": 25, "category": "Dairy"},
    {"item_name": "Amul Butter Pasteurized 500g", "quantity": 18, "quantity_unit": "packet", "unit_price": 275.00, "reorder_level": 30, "category": "Dairy"},
    {"item_name": "Amul Processed Cheese Block 1kg", "quantity": 12, "quantity_unit": "packet", "unit_price": 490.00, "reorder_level": 15, "category": "Dairy"},
    {"item_name": "Refined Crystal Sugar", "quantity": 450, "quantity_unit": "kg", "unit_price": 44.00, "reorder_level": 100, "category": "Essentials"},
    {"item_name": "Tata Vacuum Evaporated Salt", "quantity": 300, "quantity_unit": "packet", "unit_price": 24.00, "reorder_level": 80, "category": "Essentials"},
    {"item_name": "Tata Tea Premium 1kg", "quantity": 45, "quantity_unit": "packet", "unit_price": 480.00, "reorder_level": 30, "category": "Beverages"},
    {"item_name": "BRU Instant Coffee 500g", "quantity": 22, "quantity_unit": "packet", "unit_price": 380.00, "reorder_level": 20, "category": "Beverages"},
    {"item_name": "Catch Turmeric Powder 500g", "quantity": 65, "quantity_unit": "packet", "unit_price": 115.00, "reorder_level": 30, "category": "Spices"},
    {"item_name": "Catch Red Chilli Powder 500g", "quantity": 55, "quantity_unit": "packet", "unit_price": 160.00, "reorder_level": 25, "category": "Spices"},
    {"item_name": "Everest Garam Masala 100g", "quantity": 90, "quantity_unit": "packet", "unit_price": 75.00, "reorder_level": 40, "category": "Spices"},
    {"item_name": "Maggi 2-Minute Masala Noodles", "quantity": 85, "quantity_unit": "packet", "unit_price": 14.00, "reorder_level": 150, "category": "Packaged Foods"},
    {"item_name": "Kissan Fresh Tomato Ketchup 1kg", "quantity": 32, "quantity_unit": "bottle", "unit_price": 135.00, "reorder_level": 20, "category": "Packaged Foods"},
    {"item_name": "Aashirvaad Instant Idli Mix 1kg", "quantity": 40, "quantity_unit": "packet", "unit_price": 110.00, "reorder_level": 25, "category": "Packaged Foods"},
    {"item_name": "Dettol Liquid Handwash 1.5L", "quantity": 28, "quantity_unit": "bottle", "unit_price": 245.00, "reorder_level": 20, "category": "Personal Care"},
    {"item_name": "Surf Excel Matic Front Load 2kg", "quantity": 35, "quantity_unit": "packet", "unit_price": 420.00, "reorder_level": 20, "category": "Household"},
    {"item_name": "Vim Dishwash Bar 300g", "quantity": 140, "quantity_unit": "packet", "unit_price": 22.00, "reorder_level": 60, "category": "Household"}
]

# ----------------------------------------------------------------------
# 2. CUSTOMERS
# ----------------------------------------------------------------------
CUSTOMERS = [
    {"name": "Ramesh General Stores", "gstin": "29AABCR1111K1Z1", "address": "14 Commercial Street, Bengaluru - 560001"},
    {"name": "Sharma Supermarket & Traders", "gstin": "29AABCS2222L1Z2", "address": "88 100ft Road, Indiranagar, Bengaluru - 560038"},
    {"name": "Gupta Kirana Store", "gstin": "29AABCG3333M1Z3", "address": "205 7th Block, Jayanagar, Bengaluru - 560082"},
    {"name": "Kavya Provisions & Mart", "gstin": "29AABCK4444N1Z4", "address": "42 27th Main, BTM Layout 1st Stage, Bengaluru - 560068"},
    {"name": "Balaji Hypermarket Wholesale", "gstin": "29AABCB5555P1Z5", "address": "12 Malleshwaram 8th Cross, Bengaluru - 560003"},
    {"name": "Ananya Retail Hub", "gstin": "29AABCA6666Q1Z6", "address": "77 Koramangala 4th Block, Bengaluru - 560034"},
    {"name": "Sri Lakshmi Mart", "gstin": "29AABCL7777R1Z7", "address": "19 Outer Ring Road, Marathahalli, Bengaluru - 560037"}
]

# ----------------------------------------------------------------------
# 3. 20 INVOICES ACROSS JULY & AUGUST 2026
# ----------------------------------------------------------------------
INVOICE_DEFINITIONS = [
    # July 2026 Invoices (All Paid)
    {
        "num": "INV-2026-001",
        "date": "2026-07-02",
        "due": "2026-07-16",
        "customer": CUSTOMERS[0],
        "items": [
            ("Basmati Rice Royal", "100", "95.00", "9500.00"),
            ("Whole Wheat Sharbati Atta", "150", "46.00", "6900.00"),
            ("Refined Crystal Sugar", "200", "44.00", "8800.00"),
            ("Fortune Refined Sunflower Oil", "50", "155.00", "7750.00"),
        ],
        "subtotal": "32950.00",
        "tax_rate": 0.05,
        "tax": "1647.50",
        "total": "34597.50",
        "payment_date": "2026-07-05",
        "payment_method": "NEFT",
        "payment_remark": "NEFT-CR-INV-2026-001-RameshStores",
    },
    {
        "num": "INV-2026-002",
        "date": "2026-07-05",
        "due": "2026-07-19",
        "customer": CUSTOMERS[1],
        "items": [
            ("Toor Dal Premium", "80", "145.00", "11600.00"),
            ("Moong Dal Washed", "60", "120.00", "7200.00"),
            ("Amul Butter Pasteurized 500g", "40", "275.00", "11000.00"),
            ("Maggi 2-Minute Masala Noodles", "300", "14.00", "4200.00"),
        ],
        "subtotal": "34000.00",
        "tax_rate": 0.12,
        "tax": "4080.00",
        "total": "38080.00",
        "payment_date": "2026-07-08",
        "payment_method": "UPI",
        "payment_remark": "UPI/INV-2026-002/SharmaTraders/Full",
    },
    {
        "num": "INV-2026-003",
        "date": "2026-07-09",
        "due": "2026-07-23",
        "customer": CUSTOMERS[2],
        "items": [
            ("Tata Tea Premium 1kg", "50", "480.00", "24000.00"),
            ("BRU Instant Coffee 500g", "25", "380.00", "9500.00"),
            ("Tata Vacuum Evaporated Salt", "200", "24.00", "4800.00"),
        ],
        "subtotal": "38300.00",
        "tax_rate": 0.05,
        "tax": "1915.00",
        "total": "40215.00",
        "payment_date": "2026-07-14",
        "payment_method": "IMPS",
        "payment_remark": "IMPS-INV-2026-003-GuptaKirana-Clr",
    },
    {
        "num": "INV-2026-004",
        "date": "2026-07-12",
        "due": "2026-07-26",
        "customer": CUSTOMERS[3],
        "items": [
            ("Amul Pure Cow Ghee", "30", "620.00", "18600.00"),
            ("Amul Processed Cheese Block 1kg", "20", "490.00", "9800.00"),
            ("Surf Excel Matic Front Load 2kg", "25", "420.00", "10500.00"),
        ],
        "subtotal": "38900.00",
        "tax_rate": 0.18,
        "tax": "7002.00",
        "total": "45902.00",
        "payment_date": "2026-07-16",
        "payment_method": "NEFT",
        "payment_remark": "NEFT-CR-INV-2026-004-KavyaProvisions",
    },
    {
        "num": "INV-2026-005",
        "date": "2026-07-16",
        "due": "2026-07-30",
        "customer": CUSTOMERS[4],
        "items": [
            ("Sona Masoori Rice", "300", "58.00", "17400.00"),
            ("Whole Wheat Sharbati Atta", "200", "46.00", "9200.00"),
            ("Dhara Pure Mustard Oil", "60", "165.00", "9900.00"),
            ("Chana Dal Super", "100", "88.00", "8800.00"),
        ],
        "subtotal": "45300.00",
        "tax_rate": 0.05,
        "tax": "2265.00",
        "total": "47565.00",
        "payment_date": "2026-07-20",
        "payment_method": "RTGS",
        "payment_remark": "RTGS-CR-INV-2026-005-BalajiHyper",
    },
    {
        "num": "INV-2026-006",
        "date": "2026-07-19",
        "due": "2026-08-02",
        "customer": CUSTOMERS[5],
        "items": [
            ("Catch Turmeric Powder 500g", "80", "115.00", "9200.00"),
            ("Catch Red Chilli Powder 500g", "60", "160.00", "9600.00"),
            ("Everest Garam Masala 100g", "100", "75.00", "7500.00"),
            ("Kissan Fresh Tomato Ketchup 1kg", "40", "135.00", "5400.00"),
        ],
        "subtotal": "31700.00",
        "tax_rate": 0.12,
        "tax": "3804.00",
        "total": "35504.00",
        "payment_date": "2026-07-24",
        "payment_method": "UPI",
        "payment_remark": "UPI/INV-2026-006/AnanyaHub/Settled",
    },
    {
        "num": "INV-2026-007",
        "date": "2026-07-22",
        "due": "2026-08-05",
        "customer": CUSTOMERS[6],
        "items": [
            ("Basmati Rice Royal", "120", "95.00", "11400.00"),
            ("Toor Dal Premium", "70", "145.00", "10150.00"),
            ("Refined Crystal Sugar", "150", "44.00", "6600.00"),
        ],
        "subtotal": "28150.00",
        "tax_rate": 0.05,
        "tax": "1407.50",
        "total": "29557.50",
        "payment_date": "2026-07-27",
        "payment_method": "NEFT",
        "payment_remark": "NEFT-CR-INV-2026-007-SriLakshmiMart",
    },
    {
        "num": "INV-2026-008",
        "date": "2026-07-26",
        "due": "2026-08-09",
        "customer": CUSTOMERS[0],
        "items": [
            ("Dettol Liquid Handwash 1.5L", "40", "245.00", "9800.00"),
            ("Surf Excel Matic Front Load 2kg", "30", "420.00", "12600.00"),
            ("Vim Dishwash Bar 300g", "200", "22.00", "4400.00"),
        ],
        "subtotal": "26800.00",
        "tax_rate": 0.18,
        "tax": "4824.00",
        "total": "31624.00",
        "payment_date": "2026-07-31",
        "payment_method": "UPI",
        "payment_remark": "UPI/INV-2026-008/RameshStores/Payment",
    },
    {
        "num": "INV-2026-009",
        "date": "2026-07-29",
        "due": "2026-08-12",
        "customer": CUSTOMERS[1],
        "items": [
            ("Aashirvaad Instant Idli Mix 1kg", "80", "110.00", "8800.00"),
            ("Maggi 2-Minute Masala Noodles", "400", "14.00", "5600.00"),
            ("Fortune Refined Sunflower Oil", "60", "155.00", "9300.00"),
        ],
        "subtotal": "23700.00",
        "tax_rate": 0.12,
        "tax": "2844.00",
        "total": "26544.00",
        "payment_date": "2026-08-03",
        "payment_method": "IMPS",
        "payment_remark": "IMPS-INV-2026-009-SharmaTraders",
    },
    # August 2026 Invoices (Mix of Paid, Partially Paid, and Unpaid)
    {
        "num": "INV-2026-010",
        "date": "2026-08-02",
        "due": "2026-08-16",
        "customer": CUSTOMERS[2],
        "items": [
            ("Basmati Rice Royal", "150", "95.00", "14250.00"),
            ("Whole Wheat Sharbati Atta", "200", "46.00", "9200.00"),
            ("Refined Crystal Sugar", "300", "44.00", "13200.00"),
        ],
        "subtotal": "36650.00",
        "tax_rate": 0.05,
        "tax": "1832.50",
        "total": "38482.50",
        "payment_date": "2026-08-06",
        "payment_method": "NEFT",
        "payment_remark": "NEFT-CR-INV-2026-010-GuptaKirana",
    },
    {
        "num": "INV-2026-011",
        "date": "2026-08-05",
        "due": "2026-08-19",
        "customer": CUSTOMERS[3],
        "items": [
            ("Amul Pure Cow Ghee", "25", "620.00", "15500.00"),
            ("Amul Butter Pasteurized 500g", "35", "275.00", "9625.00"),
            ("Tata Tea Premium 1kg", "40", "480.00", "19200.00"),
        ],
        "subtotal": "44325.00",
        "tax_rate": 0.12,
        "tax": "5319.00",
        "total": "49644.00",
        "payment_date": "2026-08-10",
        "payment_method": "UPI",
        "payment_remark": "UPI/INV-2026-011/KavyaProvisions",
    },
    {
        "num": "INV-2026-012",
        "date": "2026-08-08",
        "due": "2026-08-22",
        "customer": CUSTOMERS[4],
        "items": [
            ("Sona Masoori Rice", "400", "58.00", "23200.00"),
            ("Toor Dal Premium", "100", "145.00", "14500.00"),
            ("Moong Dal Washed", "80", "120.00", "9600.00"),
            ("Fortune Refined Sunflower Oil", "80", "155.00", "12400.00"),
        ],
        "subtotal": "59700.00",
        "tax_rate": 0.05,
        "tax": "2985.00",
        "total": "62685.00",
        "payment_date": "2026-08-14",
        "payment_method": "RTGS",
        "payment_remark": "RTGS-INV-2026-012-BalajiWholesale",
    },
    {
        "num": "INV-2026-013",
        "date": "2026-08-12",
        "due": "2026-08-26",
        "customer": CUSTOMERS[5],
        "items": [
            ("Catch Turmeric Powder 500g", "100", "115.00", "11500.00"),
            ("Catch Red Chilli Powder 500g", "80", "160.00", "12800.00"),
            ("Everest Garam Masala 100g", "120", "75.00", "9000.00"),
        ],
        "subtotal": "33300.00",
        "tax_rate": 0.12,
        "tax": "3996.00",
        "total": "37296.00",
        "payment_date": "2026-08-17",
        "payment_method": "IMPS",
        "payment_remark": "IMPS-INV-2026-013-AnanyaHub",
    },
    {
        "num": "INV-2026-014",
        "date": "2026-08-15",
        "due": "2026-08-29",
        "customer": CUSTOMERS[6],
        "items": [
            ("Dettol Liquid Handwash 1.5L", "50", "245.00", "12250.00"),
            ("Surf Excel Matic Front Load 2kg", "40", "420.00", "16800.00"),
            ("Vim Dishwash Bar 300g", "250", "22.00", "5500.00"),
        ],
        "subtotal": "34550.00",
        "tax_rate": 0.18,
        "tax": "6219.00",
        "total": "40769.00",
        "payment_date": "2026-08-21",
        "payment_method": "NEFT",
        "payment_remark": "NEFT-CR-INV-2026-014-SriLakshmi",
    },
    {
        "num": "INV-2026-015",
        "date": "2026-08-18",
        "due": "2026-09-01",
        "customer": CUSTOMERS[0],
        "items": [
            ("Basmati Rice Royal", "120", "95.00", "11400.00"),
            ("Whole Wheat Sharbati Atta", "150", "46.00", "6900.00"),
            ("Refined Crystal Sugar", "200", "44.00", "8800.00"),
        ],
        "subtotal": "27100.00",
        "tax_rate": 0.05,
        "tax": "1355.00",
        "total": "28455.00",
        "payment_date": "2026-08-24",
        "payment_method": "UPI",
        "payment_remark": "UPI/INV-2026-015/RameshStores",
    },
    {
        "num": "INV-2026-016",
        "date": "2026-08-21",
        "due": "2026-09-04",
        "customer": CUSTOMERS[1],
        "items": [
            ("Amul Processed Cheese Block 1kg", "25", "490.00", "12250.00"),
            ("Amul Butter Pasteurized 500g", "40", "275.00", "11000.00"),
            ("Maggi 2-Minute Masala Noodles", "350", "14.00", "4900.00"),
        ],
        "subtotal": "28150.00",
        "tax_rate": 0.12,
        "tax": "3378.00",
        "total": "31528.00",
        # Partially Paid: Received ₹15,000.00
        "payment_date": "2026-08-26",
        "payment_method": "UPI",
        "partial_amount": "15000.00",
        "payment_remark": "UPI/INV-2026-016/SharmaTraders/Part1",
    },
    {
        "num": "INV-2026-017",
        "date": "2026-08-24",
        "due": "2026-09-07",
        "customer": CUSTOMERS[2],
        "items": [
            ("Tata Tea Premium 1kg", "60", "480.00", "28800.00"),
            ("BRU Instant Coffee 500g", "30", "380.00", "11400.00"),
        ],
        "subtotal": "40200.00",
        "tax_rate": 0.05,
        "tax": "2010.00",
        "total": "42210.00",
        # UNPAID
        "payment_date": None,
    },
    {
        "num": "INV-2026-018",
        "date": "2026-08-26",
        "due": "2026-09-09",
        "customer": CUSTOMERS[3],
        "items": [
            ("Toor Dal Premium", "120", "145.00", "17400.00"),
            ("Chana Dal Super", "100", "88.00", "8800.00"),
            ("Urad Dal Gota", "60", "135.00", "8100.00"),
        ],
        "subtotal": "34300.00",
        "tax_rate": 0.05,
        "tax": "1715.00",
        "total": "36015.00",
        # UNPAID
        "payment_date": None,
    },
    {
        "num": "INV-2026-019",
        "date": "2026-08-28",
        "due": "2026-09-11",
        "customer": CUSTOMERS[4],
        "items": [
            ("Dhara Pure Mustard Oil", "80", "165.00", "13200.00"),
            ("Fortune Refined Sunflower Oil", "70", "155.00", "10850.00"),
            ("Amul Pure Cow Ghee", "20", "620.00", "12400.00"),
        ],
        "subtotal": "36450.00",
        "tax_rate": 0.12,
        "tax": "4374.00",
        "total": "40824.00",
        # UNPAID
        "payment_date": None,
    },
    {
        "num": "INV-2026-020",
        "date": "2026-08-30",
        "due": "2026-09-13",
        "customer": CUSTOMERS[5],
        "items": [
            ("Surf Excel Matic Front Load 2kg", "50", "420.00", "21000.00"),
            ("Dettol Liquid Handwash 1.5L", "30", "245.00", "7350.00"),
            ("Kissan Fresh Tomato Ketchup 1kg", "40", "135.00", "5400.00"),
        ],
        "subtotal": "33750.00",
        "tax_rate": 0.18,
        "tax": "6075.00",
        "total": "39825.00",
        # UNPAID
        "payment_date": None,
    },
    # September 2026 Invoices (Recent past up to 2 days ago)
    {
        "num": "INV-2026-021",
        "date": "2026-09-01",
        "due": "2026-09-15",
        "customer": CUSTOMERS[0],
        "items": [
            ("Basmati Rice Royal", "100", "95.00", "9500.00"),
            ("Whole Wheat Sharbati Atta", "150", "46.00", "6900.00"),
            ("Amul Pure Cow Ghee", "20", "620.00", "12400.00"),
        ],
        "subtotal": "28800.00",
        "tax_rate": 0.08,
        "tax": "2304.00",
        "total": "31104.00",
        # UNPAID
        "payment_date": None,
    },
    {
        "num": "INV-2026-022",
        "date": "2026-09-02",
        "due": "2026-09-16",
        "customer": CUSTOMERS[3],
        "items": [
            ("Toor Dal Premium", "100", "145.00", "14500.00"),
            ("Fortune Refined Sunflower Oil", "60", "155.00", "9300.00"),
            ("Refined Crystal Sugar", "150", "44.00", "6600.00"),
        ],
        "subtotal": "30400.00",
        "tax_rate": 0.05,
        "tax": "1520.00",
        "total": "31920.00",
        # UNPAID
        "payment_date": None,
    },
    {
        "num": "INV-2026-023",
        "date": "2026-09-03",
        "due": "2026-09-17",
        "customer": CUSTOMERS[4],
        "items": [
            ("Amul Processed Cheese Block 1kg", "20", "490.00", "9800.00"),
            ("Amul Butter Pasteurized 500g", "40", "275.00", "11000.00"),
            ("Maggi 2-Minute Masala Noodles", "350", "14.00", "4900.00"),
        ],
        "subtotal": "25700.00",
        "tax_rate": 0.12,
        "tax": "3084.00",
        "total": "28784.00",
        "payment_date": "2026-09-04",
        "payment_method": "UPI",
        "payment_remark": "UPI/INV-2026-023/BalajiHyper",
    }
]


def generate_inventory_csv():
    csv_path = os.path.join(TEST_DATASETS_DIR, "1_inventory_stock.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("item_name,quantity,quantity_unit,unit_price,reorder_level,category\n")
        for item in INVENTORY_ITEMS:
            f.write(f"{item['item_name']},{item['quantity']},{item['quantity_unit']},{item['unit_price']:.2f},{item['reorder_level']},{item['category']}\n")
    print(f"Generated Inventory CSV: {csv_path} ({len(INVENTORY_ITEMS)} items)")


def build_pdf_invoice(inv: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm
    )
    styles = getSampleStyleSheet()
    
    seller_style = ParagraphStyle("Seller", parent=styles["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#334155"))
    header_style = ParagraphStyle("Header", parent=styles["Title"], fontSize=18, leading=22, textColor=colors.HexColor("#1e293b"), alignment=TA_LEFT)
    right_meta = ParagraphStyle("RightMeta", parent=styles["Normal"], fontSize=9, leading=13, alignment=TA_RIGHT, textColor=colors.HexColor("#1e293b"))
    bill_style = ParagraphStyle("Bill", parent=styles["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#1e293b"))

    story = []

    # Header Row: Seller Info on Left, Invoice Title + Meta on Right
    seller_p = Paragraph(
        "<b>VYAPAAR ENTERPRISES PVT LTD</b><br/>"
        "Plot 42, Peenya Industrial Area, Phase 2<br/>"
        "Bengaluru, Karnataka - 560058<br/>"
        "<b>GSTIN:</b> 29ABCDE9999F1Z9<br/>"
        "<b>Email:</b> billing@vyapaar-cfo.in",
        seller_style
    )

    inv_meta_p = Paragraph(
        f"<font size='16'><b>TAX INVOICE</b></font><br/>"
        f"<b>Invoice No:</b> {inv['num']}<br/>"
        f"<b>Invoice Date:</b> {inv['date']}<br/>"
        f"<b>Due Date:</b> {inv['due']}",
        right_meta
    )

    header_table = Table([[seller_p, inv_meta_p]], colWidths=[90 * mm, 90 * mm])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 4 * mm))

    # Bill To Box
    cust = inv["customer"]
    bill_to_content = [
        [Paragraph(f"<b>BILL TO / RECIPIENT:</b><br/>"
                   f"<b>Customer Name:</b> {cust['name']}<br/>"
                   f"<b>Customer GSTIN:</b> {cust['gstin']}<br/>"
                   f"<b>Address:</b> {cust['address']}", bill_style)]
    ]
    bill_table = Table(bill_to_content, colWidths=[180 * mm])
    bill_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#cbd5e1")),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(bill_table)
    story.append(Spacer(1, 5 * mm))

    # Line Items Table
    table_data = [["Sl.", "Item Description", "Qty", "Rate (₹)", "Total Amount (₹)"]]
    for idx, (desc, qty, rate, tot) in enumerate(inv["items"], start=1):
        table_data.append([str(idx), desc, qty, rate, tot])

    items_table = Table(
        table_data,
        colWidths=[12 * mm, 90 * mm, 22 * mm, 26 * mm, 30 * mm]
    )
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 4 * mm))

    # Totals Summary Box
    tax_pct_str = f"{int(inv['tax_rate'] * 100)}%"
    totals_data = [
        ["Subtotal (Taxable Value):", f"INR {inv['subtotal']}"],
        [f"GST / Tax ({tax_pct_str}):", f"INR {inv['tax']}"],
        ["Total Amount With Tax:", f"INR {inv['total']}"]
    ]
    totals_table = Table(totals_data, colWidths=[130 * mm, 50 * mm])
    totals_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#f1f5f9")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 5 * mm))

    # Footer note
    footer_p = Paragraph(
        "<b>Payment Terms:</b> Payment due within 14 days from invoice date. Make payments via NEFT/RTGS/UPI quoting the invoice number.<br/>"
        "<i>This is a computer-generated tax invoice issued by Vyapaar Enterprises.</i>",
        seller_style
    )
    story.append(footer_p)

    doc.build(story)
    return buf.getvalue()


def generate_all_invoices():
    print(f"Generating {len(INVOICE_DEFINITIONS)} PDF Invoices...")
    for inv in INVOICE_DEFINITIONS:
        pdf_bytes = build_pdf_invoice(inv)
        file_name = f"{inv['num']}.pdf"
        file_path = os.path.join(INVOICES_PDF_DIR, file_name)
        with open(file_path, "wb") as f:
            f.write(pdf_bytes)
    print(f"All {len(INVOICE_DEFINITIONS)} PDF invoices generated in: {INVOICES_PDF_DIR}")

    # Generate sample PNG images for image invoice extractor testing
    try:
        import pypdfium2
        sample_imgs = ["INV-2026-004.pdf", "INV-2026-008.pdf", "INV-2026-015.pdf"]
        for s_pdf in sample_imgs:
            p = os.path.join(INVOICES_PDF_DIR, s_pdf)
            out_img = os.path.join(INVOICES_IMG_DIR, s_pdf.replace(".pdf", ".png"))
            doc = pypdfium2.PdfDocument(p)
            doc.get_page(0).render(scale=2).to_pil().save(out_img)
        print(f"Rendered sample PNG images in: {INVOICES_IMG_DIR}")
    except Exception as e:
        print(f"Note: PNG image rendering skipped ({e})")



def generate_bank_statement_csv():
    """
    Generates 2 months (July 1 to Aug 31, 2026) of bank statement entries.
    Includes:
      - Opening Balance
      - Matching Invoice CREDIT payments with exact references
      - Realistic Operating DEBITS (Rent, Wholesale inventory restock, Utilities, Salaries, Logistics)
      - Perfectly calculated balance running column
    """
    transactions = []
    
    # Opening Balance
    balance = Decimal("250000.00")
    transactions.append({
        "date": "2026-07-01",
        "description": "Opening Balance - HDFC Bank Current A/c 50200012345678",
        "type": "CREDIT",
        "amount": Decimal("250000.00"),
        "balance": balance
    })

    # Interleaved transactions for July & August
    events = [
        # --- JULY 2026 ---
        {"date": "2026-07-03", "desc": "Vendor Restock - Agro Flour Mills Pvt Ltd", "type": "DEBIT", "amount": Decimal("48000.00")},
        {"date": "2026-07-05", "desc": "NEFT-CR-INV-2026-001-RameshStores", "type": "CREDIT", "amount": Decimal("34597.50")},
        {"date": "2026-07-07", "desc": "Warehouse Electricity Bill - BESCOM", "type": "DEBIT", "amount": Decimal("11200.00")},
        {"date": "2026-07-08", "desc": "UPI/INV-2026-002/SharmaTraders/Full", "type": "CREDIT", "amount": Decimal("38080.00")},
        {"date": "2026-07-10", "desc": "Office & Warehouse Rent - Peenya Industrial Park", "type": "DEBIT", "amount": Decimal("35000.00")},
        {"date": "2026-07-14", "desc": "IMPS-INV-2026-003-GuptaKirana-Clr", "type": "CREDIT", "amount": Decimal("40215.00")},
        {"date": "2026-07-15", "desc": "Supplier Payment - Fortune Edible Oil Refineries", "type": "DEBIT", "amount": Decimal("52000.00")},
        {"date": "2026-07-16", "desc": "NEFT-CR-INV-2026-004-KavyaProvisions", "type": "CREDIT", "amount": Decimal("45902.00")},
        {"date": "2026-07-18", "desc": "Logistics & Freight Transport - VRL Logistics", "type": "DEBIT", "amount": Decimal("14500.00")},
        {"date": "2026-07-20", "desc": "RTGS-CR-INV-2026-005-BalajiHyper", "type": "CREDIT", "amount": Decimal("47565.00")},
        {"date": "2026-07-22", "desc": "Supplier Restock - Amul Dairy Wholesale Distribution", "type": "DEBIT", "amount": Decimal("65000.00")},
        {"date": "2026-07-24", "desc": "UPI/INV-2026-006/AnanyaHub/Settled", "type": "CREDIT", "amount": Decimal("35504.00")},
        {"date": "2026-07-27", "desc": "NEFT-CR-INV-2026-007-SriLakshmiMart", "type": "CREDIT", "amount": Decimal("29557.50")},
        {"date": "2026-07-28", "desc": "FMCG Wholesale Restock - Nestlé & Unilever Distribution", "type": "DEBIT", "amount": Decimal("42000.00")},
        {"date": "2026-07-31", "desc": "UPI/INV-2026-008/RameshStores/Payment", "type": "CREDIT", "amount": Decimal("31624.00")},
        {"date": "2026-07-31", "desc": "Monthly Staff Payroll & Warehouse Wages", "type": "DEBIT", "amount": Decimal("75000.00")},

        # --- AUGUST 2026 ---
        {"date": "2026-08-01", "desc": "Office & Warehouse Rent - Peenya Industrial Park", "type": "DEBIT", "amount": Decimal("35000.00")},
        {"date": "2026-08-03", "desc": "IMPS-INV-2026-009-SharmaTraders", "type": "CREDIT", "amount": Decimal("26544.00")},
        {"date": "2026-08-04", "desc": "Vendor Restock - Tata Consumer Products Wholesale", "type": "DEBIT", "amount": Decimal("55000.00")},
        {"date": "2026-08-06", "desc": "NEFT-CR-INV-2026-010-GuptaKirana", "type": "CREDIT", "amount": Decimal("38482.50")},
        {"date": "2026-08-08", "desc": "Commercial Electricity Bill - BESCOM", "type": "DEBIT", "amount": Decimal("12800.00")},
        {"date": "2026-08-10", "desc": "UPI/INV-2026-011/KavyaProvisions", "type": "CREDIT", "amount": Decimal("49644.00")},
        {"date": "2026-08-12", "desc": "Packaging Supplies & Corrugated Boxes", "type": "DEBIT", "amount": Decimal("8500.00")},
        {"date": "2026-08-14", "desc": "RTGS-INV-2026-012-BalajiWholesale", "type": "CREDIT", "amount": Decimal("62685.00")},
        {"date": "2026-08-16", "desc": "GST Tax Return Payment - July Period (CBIC)", "type": "DEBIT", "amount": Decimal("28500.00")},
        {"date": "2026-08-17", "desc": "IMPS-INV-2026-013-AnanyaHub", "type": "CREDIT", "amount": Decimal("37296.00")},
        {"date": "2026-08-19", "desc": "Restock - Spice & Condiments Wholesale", "type": "DEBIT", "amount": Decimal("31000.00")},
        {"date": "2026-08-21", "desc": "NEFT-CR-INV-2026-014-SriLakshmi", "type": "CREDIT", "amount": Decimal("40769.00")},
        {"date": "2026-08-23", "desc": "Logistics & Local Delivery Van Maintenance", "type": "DEBIT", "amount": Decimal("16400.00")},
        {"date": "2026-08-24", "desc": "UPI/INV-2026-015/RameshStores", "type": "CREDIT", "amount": Decimal("28455.00")},
        {"date": "2026-08-26", "desc": "UPI/INV-2026-016/SharmaTraders/Part1", "type": "CREDIT", "amount": Decimal("15000.00")},
        {"date": "2026-08-28", "desc": "Supplier Restock - Pulses & Grains Direct Mandi", "type": "DEBIT", "amount": Decimal("68000.00")},
        {"date": "2026-08-31", "desc": "Monthly Staff Payroll & Warehouse Wages", "type": "DEBIT", "amount": Decimal("78000.00")},

        # --- SEPTEMBER 2026 (Recent Past - Up to 2 days ago) ---
        {"date": "2026-09-01", "desc": "Office & Warehouse Rent - Peenya Industrial Park", "type": "DEBIT", "amount": Decimal("35000.00")},
        {"date": "2026-09-02", "desc": "Supplier Restock - Dairy & Edible Oils Direct", "type": "DEBIT", "amount": Decimal("42000.00")},
        {"date": "2026-09-03", "desc": "Warehouse Electricity Bill - BESCOM", "type": "DEBIT", "amount": Decimal("11500.00")},
        {"date": "2026-09-03", "desc": "NEFT-CR-INV-2026-017-GuptaKirana-Part", "type": "CREDIT", "amount": Decimal("20000.00")},
        {"date": "2026-09-04", "desc": "UPI/INV-2026-023/BalajiHyper", "type": "CREDIT", "amount": Decimal("28784.00")},
        {"date": "2026-09-04", "desc": "Local Logistics & Delivery Fleet Fuel", "type": "DEBIT", "amount": Decimal("6200.00")},
    ]

    for ev in events:
        if ev["type"] == "CREDIT":
            balance += ev["amount"]
        else:
            balance -= ev["amount"]
        transactions.append({
            "date": ev["date"],
            "description": ev["desc"],
            "type": ev["type"],
            "amount": ev["amount"],
            "balance": balance
        })

    csv_path = os.path.join(TEST_DATASETS_DIR, "3_bank_statement_2months.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("Date,Description,Type,Amount,Balance\n")
        for t in transactions:
            f.write(f"{t['date']},{t['description']},{t['type']},{t['amount']:.2f},{t['balance']:.2f}\n")
    print(f"Generated 2-Month Bank Statement CSV: {csv_path} ({len(transactions)} rows, Final Balance: INR {balance:,.2f})")

    # Also update test_datasets/3_bank_statement.csv
    fallback_csv = os.path.join(TEST_DATASETS_DIR, "3_bank_statement.csv")
    with open(fallback_csv, "w", encoding="utf-8") as f:
        f.write("Date,Description,Type,Amount,Balance\n")
        for t in transactions:
            f.write(f"{t['date']},{t['description']},{t['type']},{t['amount']:.2f},{t['balance']:.2f}\n")


def generate_whatsapp_chats():
    chat_content = """02/07/2026, 09:30 - Ramesh General Stores: Namaste Vyapaar ji, please dispatch 100kg Basmati Rice Royal and 150kg Sharbati Atta urgent today.
02/07/2026, 09:32 - You: Namaste Ramesh ji. We have plenty in stock. Processing Invoice INV-2026-001 now.
02/07/2026, 09:35 - Ramesh General Stores: Also add 200kg Sugar and 50L Sunflower Oil.
02/07/2026, 09:40 - You: Added to invoice. Total INR 34,597.50. Delivery scheduled for 2 PM.
05/07/2026, 11:15 - Ramesh General Stores: Paid full amount via NEFT. Ref: NEFT-CR-INV-2026-001-RameshStores.

05/07/2026, 14:00 - Sharma Supermarket & Traders: Hello, need urgent delivery of 80kg Toor Dal, 60kg Moong Dal, and 40 packets Amul Butter 500g.
05/07/2026, 14:05 - You: Hello Sharma ji. We also have Maggi Noodles if you need restock.
05/07/2026, 14:08 - Sharma Supermarket & Traders: Yes, add 300 packets Maggi Noodles as well. Please share invoice.
05/07/2026, 14:15 - You: Generated INV-2026-002 for INR 38,080.00. Dispatching tomorrow morning.
08/07/2026, 16:30 - Sharma Supermarket & Traders: Transferred INR 38,080 via UPI. Check UPI/INV-2026-002/SharmaTraders/Full.

09/07/2026, 10:20 - Gupta Kirana Store: Bhaiya, rate of Tata Tea Premium 1kg and BRU Coffee 500g?
09/07/2026, 10:22 - You: Tata Tea INR 480/packet, BRU Coffee INR 380/packet.
09/07/2026, 10:25 - Gupta Kirana Store: Send 50 packets Tata Tea, 25 packets BRU Coffee, and 200 packets Tata Salt.
09/07/2026, 10:30 - You: Order confirmed on INV-2026-003. Total INR 40,215.00.
14/07/2026, 12:45 - Gupta Kirana Store: Paid INR 40,215 via IMPS.

16/07/2026, 11:00 - Balaji Hypermarket Wholesale: Sir, we need bulk order: 300kg Sona Masoori Rice, 200kg Atta, 60L Mustard Oil, 100kg Chana Dal.
16/07/2026, 11:05 - You: Bulk discount applied on INV-2026-005. Total INR 47,565.00.
20/07/2026, 15:20 - Balaji Hypermarket Wholesale: RTGS payment completed for INV-2026-005.

02/08/2026, 09:15 - Gupta Kirana Store: Namaste sir, need 150kg Basmati Rice, 200kg Atta, 300kg Sugar for festival stock.
02/08/2026, 09:20 - You: Processing INV-2026-010. Total INR 38,482.50.
06/08/2026, 17:00 - Gupta Kirana Store: NEFT payment sent for INV-2026-010.

12/08/2026, 10:30 - Ananya Retail Hub: Hello, need 100 packets Turmeric, 80 packets Chilli Powder, 120 packets Garam Masala.
12/08/2026, 10:35 - You: Billed under INV-2026-013. Total INR 37,296.00. Dispatching today.
17/08/2026, 14:10 - Ananya Retail Hub: Cleared via IMPS.

21/08/2026, 11:45 - Sharma Supermarket & Traders: Bhaiya, send 25 blocks Amul Cheese 1kg, 40 packets Amul Butter, 350 packets Maggi.
21/08/2026, 11:50 - You: Billed on INV-2026-016. Total INR 31,528.00.
26/08/2026, 16:30 - Sharma Supermarket & Traders: Transferred partial payment of INR 15,000 via UPI. Will clear remaining 16,528 next week.
26/08/2026, 16:35 - You: Received INR 15,000. Balance due: INR 16,528.00.

24/08/2026, 14:00 - Gupta Kirana Store: Need 60 packets Tata Tea and 30 packets BRU Coffee.
24/08/2026, 14:05 - You: Billed on INV-2026-017 for INR 42,210.00. Payment due by 07-Sep-2026.

26/08/2026, 10:00 - Kavya Provisions & Mart: Send 120kg Toor Dal, 100kg Chana Dal, 60kg Urad Dal urgent.
26/08/2026, 10:05 - You: Invoice INV-2026-018 generated for INR 36,015.00.

28/08/2026, 15:30 - Balaji Hypermarket Wholesale: Need 80L Mustard Oil, 70L Sunflower Oil, 20L Cow Ghee.
28/08/2026, 15:35 - You: INV-2026-019 generated for INR 40,824.00.

30/08/2026, 11:00 - Ananya Retail Hub: Send 50 packets Surf Excel 2kg, 30 bottles Dettol Handwash, 40 bottles Tomato Ketchup.
30/08/2026, 11:05 - You: Generated INV-2026-020 for INR 39,825.00.

01/09/2026, 09:30 - Ramesh General Stores: Namaste, we need 100kg Basmati Rice, 150kg Atta, and 20L Cow Ghee.
01/09/2026, 09:35 - You: Invoice INV-2026-021 issued for INR 31,104.00.

02/09/2026, 10:15 - Kavya Provisions & Mart: Urgent dispatch: 100kg Toor Dal, 60L Sunflower Oil, 150kg Sugar.
02/09/2026, 10:20 - You: Processed on INV-2026-022 for INR 31,920.00.

03/09/2026, 14:00 - Balaji Hypermarket Wholesale: Send 20 blocks Cheese, 40 packets Butter, 350 packets Maggi Noodles.
03/09/2026, 14:05 - You: Invoice INV-2026-023 created for INR 28,784.00.
04/09/2026, 16:30 - Balaji Hypermarket Wholesale: Paid full INR 28,784 via UPI. Ref: UPI/INV-2026-023/BalajiHyper.
"""
    txt_path = os.path.join(TEST_DATASETS_DIR, "2_whatsapp_customer_chats.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(chat_content.strip())
    print(f"Generated WhatsApp Chats TXT: {txt_path}")

    # Also update single chat fallback
    single_chat_path = os.path.join(TEST_DATASETS_DIR, "2_whatsapp_single_chat.txt")
    with open(single_chat_path, "w", encoding="utf-8") as f:
        f.write(chat_content.strip())

    # Create ZIP archive for batch upload
    zip_path = os.path.join(TEST_DATASETS_DIR, "2_whatsapp_customer_chats.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("customer_orders_july_august.txt", chat_content.strip())
    print(f"Generated WhatsApp Chats ZIP: {zip_path}")


def generate_sql_seed():
    """
    Generates an all-in-one SQL seed script to pre-populate 2 months of data in PostgreSQL.
    """
    org_id = "a0000000-0000-0000-0000-000000000001"
    sql_lines = [
        "-- ==============================================================================",
        "-- Omni-CFO Platform: 2-Month Realistic Financial Dataset Seed (July & Aug 2026)",
        "-- Target Organization: a0000000-0000-0000-0000-000000000001 (Vyapaar Enterprises)",
        "-- ==============================================================================",
        "BEGIN;",
        f"INSERT INTO organizations (id, business_name) VALUES ('{org_id}', 'Vyapaar Enterprises Pvt Ltd') ON CONFLICT (id) DO UPDATE SET business_name = EXCLUDED.business_name;",
        "",
        "-- 1. Inventory Items",
        f"DELETE FROM inventory_items WHERE organization_id = '{org_id}';",
        f"INSERT INTO documents (id, organization_id, file_name, file_type, file_hash, processed_status, upload_date) VALUES ('d0000000-0000-0000-0000-000000000001', '{org_id}', '1_inventory_stock.csv', 'CsvInventory', 'inv_seed_hash_001', 'COMPLETED', '2026-07-01 08:00:00+05:30') ON CONFLICT (organization_id, file_hash) DO NOTHING;",
    ]

    for idx, item in enumerate(INVENTORY_ITEMS, start=1):
        item_uuid = f"e0000000-0000-0000-0000-{idx:012d}"
        sql_lines.append(
            f"INSERT INTO inventory_items (id, document_id, organization_id, item_name, quantity, quantity_unit, unit_price, reorder_level, category) "
            f"VALUES ('{item_uuid}', 'd0000000-0000-0000-0000-000000000001', '{org_id}', '{item['item_name']}', {item['quantity']}, '{item['quantity_unit']}', {item['unit_price']:.2f}, {item['reorder_level']}, '{item['category']}');"
        )

    sql_lines.append("")
    sql_lines.append("-- 2. Invoices & Line Items")
    sql_lines.append(f"DELETE FROM invoices WHERE organization_id = '{org_id}';")

    for idx, inv in enumerate(INVOICE_DEFINITIONS, start=1):
        doc_uuid = f"d1000000-0000-0000-0000-{idx:012d}"
        inv_uuid = f"c1000000-0000-0000-0000-{idx:012d}"
        file_hash = f"hash_inv_2026_{idx:03d}"

        # Determine payment status
        if inv.get("payment_date"):
            if "partial_amount" in inv:
                payment_status = "PARTIALLY_PAID"
                paid_amount = inv["partial_amount"]
                paid_at_val = f"'{inv['payment_date']}'"
            else:
                payment_status = "PAID"
                paid_amount = inv["total"]
                paid_at_val = f"'{inv['payment_date']}'"
        else:
            payment_status = "UNPAID"
            paid_amount = "0.00"
            paid_at_val = "NULL"

        sql_lines.append(
            f"INSERT INTO documents (id, organization_id, file_name, file_type, file_hash, processed_status, upload_date) "
            f"VALUES ('{doc_uuid}', '{org_id}', '{inv['num']}.pdf', 'Invoice', '{file_hash}', 'COMPLETED', '{inv['date']} 10:00:00+05:30') "
            f"ON CONFLICT (organization_id, file_hash) DO UPDATE SET processed_status = 'COMPLETED';"
        )

        sql_lines.append(
            f"INSERT INTO invoices (id, document_id, organization_id, invoice_number, invoice_date, due_date, customer_name, gst_number, total_amount, tax, total_amount_with_tax, payment_status, paid_amount, paid_at, source_type, confidence_score) "
            f"VALUES ('{inv_uuid}', '{doc_uuid}', '{org_id}', '{inv['num']}', '{inv['date']}', '{inv['due']}', '{inv['customer']['name']}', '{inv['customer']['gstin']}', {inv['subtotal']}, {inv['tax']}, {inv['total']}, '{payment_status}', {paid_amount}, {paid_at_val}, 'PDF', 0.98);"
        )

        for l_idx, (desc, qty, rate, tot) in enumerate(inv["items"], start=1):
            li_uuid = f"b{idx:03d}0000-0000-0000-0000-{l_idx:012d}"
            sql_lines.append(
                f"INSERT INTO invoice_line_items (id, invoice_id, organization_id, item_description, quantity, rate_per_unit, total_rate, line_no) "
                f"VALUES ('{li_uuid}', '{inv_uuid}', '{org_id}', '{desc}', {qty}, {rate}, {tot}, {l_idx});"
            )

    sql_lines.append("")
    sql_lines.append("-- 3. Bank Statements & Reconciliation Matches")
    sql_lines.append(f"DELETE FROM bank_statements WHERE organization_id = '{org_id}';")
    sql_lines.append(f"INSERT INTO documents (id, organization_id, file_name, file_type, file_hash, processed_status, upload_date) VALUES ('d2000000-0000-0000-0000-000000000001', '{org_id}', '3_bank_statement_2months.csv', 'BankStmt', 'bank_seed_hash_001', 'COMPLETED', '2026-08-31 23:59:00+05:30') ON CONFLICT (organization_id, file_hash) DO NOTHING;")

    # Read the generated CSV to insert bank rows
    csv_path = os.path.join(TEST_DATASETS_DIR, "3_bank_statement_2months.csv")
    with open(csv_path, "r", encoding="utf-8") as f:
        rows = [line.strip().split(",") for line in f if line.strip() and not line.startswith("Date")]

    for b_idx, parts in enumerate(rows, start=1):
        t_date, t_desc, t_type, t_amt, t_bal = parts[0], parts[1], parts[2], parts[3], parts[4]
        bs_uuid = f"a2000000-0000-0000-0000-{b_idx:012d}"

        # Check matching invoice
        matched_inv_id = "NULL"
        reconciled_status = "UNMATCHED"
        for inv_i, inv in enumerate(INVOICE_DEFINITIONS, start=1):
            if inv["num"] in t_desc and t_type == "CREDIT":
                matched_inv_id = f"'c1000000-0000-0000-0000-{inv_i:012d}'"
                reconciled_status = "MATCHED"
                break

        sql_lines.append(
            f"INSERT INTO bank_statements (id, organization_id, document_id, txn_date, description, txn_type, amount, balance, reconciliation_status, matched_invoice_id) "
            f"VALUES ('{bs_uuid}', '{org_id}', 'd2000000-0000-0000-0000-000000000001', '{t_date}', '{t_desc}', '{t_type}', {t_amt}, {t_bal}, '{reconciled_status}', {matched_inv_id});"
        )

    sql_lines.append("COMMIT;")

    sql_path = os.path.join(TEST_DATASETS_DIR, "seed_2months_data.sql")
    with open(sql_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sql_lines))
    print(f"Generated SQL Seed Script: {sql_path}")


if __name__ == "__main__":
    print("=" * 60)
    print("Starting Complete 2-Month Test Dataset Generation")
    print("=" * 60)
    generate_inventory_csv()
    generate_all_invoices()
    generate_bank_statement_csv()
    generate_whatsapp_chats()
    generate_sql_seed()
    print("=" * 60)
    print("Test Dataset Generation Completed Successfully!")
    print("=" * 60)
