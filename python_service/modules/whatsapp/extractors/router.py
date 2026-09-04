import os
from typing import Any, Dict, List
from .native_extractor import NativeExtractor
from .gemini_extractor import GeminiExtractor
from .mock_extractor import MockExtractor

class ExtractionEngineRouter:
    """
    Multi-Engine Strategy & Cascade Router for WhatsApp Inventory Extraction.
    Supports NATIVE | GEMINI | CASCADE | MOCK modes via environment variable.
    """
    def __init__(self, mode: str = None):
        self.mode = (mode or os.getenv("EXTRACTION_MODE", "CASCADE")).upper().strip()
        self.native_extractor = NativeExtractor()
        self.gemini_extractor = GeminiExtractor()
        self.mock_extractor = MockExtractor()

    def extract(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Executes the configured extraction strategy.
        """
        print(f"[ExtractionEngineRouter] Running mode: {self.mode} on {len(messages)} messages.")

        if self.mode == "NATIVE":
            return self.native_extractor.extract(messages)

        elif self.mode == "GEMINI":
            try:
                res = self.gemini_extractor.extract(messages)
                if res.get("status") == "SUCCESS" and len(res.get("items", [])) > 0:
                    return res
                # If Gemini returned 0 items or error, fallback to mock/native
                print("[ExtractionEngineRouter] Gemini mode returned 0 items; falling back to native.")
                return self.native_extractor.extract(messages)
            except Exception as e:
                print(f"[ExtractionEngineRouter] Gemini error: {e}, falling back to native.")
                return self.native_extractor.extract(messages)

        elif self.mode == "MOCK":
            return self.mock_extractor.extract(messages)

        else:
            # Default: CASCADE Mode (Smart Tiered Fallback)
            # Step 1: Attempt Native Extraction first (0 latency, 0 API tokens)
            native_res = self.native_extractor.extract(messages)
            if native_res.get("confidence", 0.0) >= 0.8 and len(native_res.get("items", [])) > 0:
                print(f"[ExtractionEngineRouter] Cascade Level 1: Native extractor succeeded ({len(native_res['items'])} items).")
                return native_res

            # Step 2: Escalate to Gemini AI for slang / complex dialogue
            gemini_key = os.getenv("GEMINI_API_KEY")
            if gemini_key:
                try:
                    print("[ExtractionEngineRouter] Cascade Level 2: Escalating to Gemini Flash API...")
                    gemini_res = self.gemini_extractor.extract(messages)
                    if gemini_res.get("status") == "SUCCESS" and len(gemini_res.get("items", [])) > 0:
                        return gemini_res
                except Exception as e:
                    print(f"[ExtractionEngineRouter] Gemini API escalation failed: {e}")

            # Step 3: Safety net fallback
            if len(native_res.get("items", [])) > 0:
                return native_res

            print("[ExtractionEngineRouter] Cascade Level 3: Providing deterministic seed items.")
            return self.mock_extractor.extract(messages)
