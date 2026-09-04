from typing import Any, Dict, List

class MockExtractor:
    """
    Deterministic Mock Extractor for offline verification, CI/CD testing, and baseline fallbacks.
    """
    def extract(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "engine": "MOCK",
            "items": [
                {
                    "item_name": "Atta (10kg)",
                    "quantity": 30.0,
                    "quantity_unit": "kg",
                    "date": "31/08/2026",
                    "timestamp": "10:15 am",
                    "description": "Baseline retail requirement for 10kg bags"
                },
                {
                    "item_name": "Basmati Rice",
                    "quantity": 25.0,
                    "quantity_unit": "kg",
                    "date": "31/08/2026",
                    "timestamp": "11:30 am",
                    "description": "Restock request from Rahul Enterprises"
                },
                {
                    "item_name": "Mustard Oil",
                    "quantity": 15.0,
                    "quantity_unit": "bottle",
                    "date": "01/09/2026",
                    "timestamp": "02:45 pm",
                    "description": "1L bottle demand"
                },
                {
                    "item_name": "Toor Dal",
                    "quantity": 20.0,
                    "quantity_unit": "kg",
                    "date": "01/09/2026",
                    "timestamp": "04:10 pm",
                    "description": "Weekly grocery order"
                }
            ],
            "confidence": 1.0,
            "customer_enquiries": [
                {
                    "customer": "Demo Customer",
                    "enquiry": "Mock demonstration log initialized."
                }
            ],
            "customer_sentiment": [
                {
                    "customer": "Summary",
                    "sentiment": "positive",
                    "reason": "Deterministic seed inventory loaded."
                }
            ],
            "status": "SUCCESS"
        }
