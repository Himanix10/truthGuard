"""
Reusable Gemini API Client Module for TruthGuard-Chronos with Multi-Key Failover.

Features:
  1. Multi-Key Failover Rotation:
     - Supports up to 3+ API keys (GEMINI_API_KEY_1, GEMINI_API_KEY_2, GEMINI_API_KEY_3,
       or comma-separated GEMINI_API_KEYS, or single GEMINI_API_KEY).
     - Automatically falls over from Key 1 → Key 2 → Key 3 when a quota limit (429),
       rate limit, or API failure occurs.
  2. Automatic .env file loading via python-dotenv.
  3. Uses the official Google Gen AI Python SDK (google-genai).
  4. Graceful fallback to deterministic rule-based output when keys are missing or all keys fail.
  5. Never hardcodes secrets.
"""

import os
import re
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Attempt to load .env from backend folder or workspace root
try:
    from dotenv import load_dotenv
    # Look for .env in current working dir and backend directory
    backend_env = Path(__file__).resolve().parent.parent / ".env"
    if backend_env.exists():
        load_dotenv(dotenv_path=backend_env)
    else:
        load_dotenv()
except ImportError:
    pass

# Try importing the official Google Gen AI SDK
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    genai = None
    types = None

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def collect_configured_api_keys() -> List[str]:
    """
    Collects ordered list of Gemini API keys from environment variables:
      1. GEMINI_API_KEY_1, GEMINI_API_KEY_2, GEMINI_API_KEY_3, ...
      2. GEMINI_API_KEYS (comma or semicolon-separated)
      3. GEMINI_API_KEY (single fallback)
    Deduplicates while preserving order and stripping whitespace.
    """
    keys: List[str] = []
    seen = set()

    def add_key(k: Optional[str]):
        if k:
            cleaned = k.strip().strip("'\"")
            if cleaned and cleaned not in seen and not cleaned.startswith("your_"):
                seen.add(cleaned)
                keys.append(cleaned)

    # 1. Check numbered keys: GEMINI_API_KEY_1 .. GEMINI_API_KEY_9
    for i in range(1, 10):
        add_key(os.environ.get(f"GEMINI_API_KEY_{i}"))

    # 2. Check comma-separated GEMINI_API_KEYS
    multi = os.environ.get("GEMINI_API_KEYS")
    if multi:
        for chunk in re.split(r"[,;]\s*", multi):
            add_key(chunk)

    # 3. Check single GEMINI_API_KEY
    add_key(os.environ.get("GEMINI_API_KEY"))

    return keys


def mask_key(key: str) -> str:
    """Masks API key for safe logging (e.g., 'AIzaSy...4xQ')."""
    if not key or len(key) < 10:
        return "***"
    return f"{key[:6]}...{key[-4:]}"


class GeminiClient:
    """
    Client wrapper for Google Gemini API with automatic multi-key failover.
    When an API call fails or hits rate/quota limits (429), it automatically
    retries with the next available key in the rotation pool.
    """

    def __init__(
        self,
        api_keys: Optional[List[str]] = None,
        model_name: Optional[str] = None,
    ):
        if api_keys is not None:
            self.api_keys = [k.strip() for k in api_keys if k and k.strip()]
        else:
            self.api_keys = collect_configured_api_keys()

        self.model_name = model_name or DEFAULT_MODEL
        self._current_key_idx = 0
        self._clients: Dict[str, Any] = {}

    @property
    def key_count(self) -> int:
        """Returns the number of configured API keys."""
        return len(self.api_keys)

    @property
    def is_available(self) -> bool:
        """Returns True if the SDK is installed and at least one API key is configured."""
        return bool(GENAI_AVAILABLE and self.api_keys)

    @property
    def current_key(self) -> Optional[str]:
        if not self.api_keys:
            return None
        return self.api_keys[self._current_key_idx % len(self.api_keys)]

    def _get_client_for_key(self, key: str):
        if not GENAI_AVAILABLE:
            return None
        if key not in self._clients:
            try:
                self._clients[key] = genai.Client(api_key=key)
            except Exception as e:
                logger.warning(f"Failed to create Google Gen AI client for key {mask_key(key)}: {e}")
                return None
        return self._clients.get(key)

    def get_status(self) -> Dict[str, Any]:
        """Returns status of configured keys and current rotation index."""
        return {
            "sdk_available": GENAI_AVAILABLE,
            "configured_keys_count": len(self.api_keys),
            "active_key_index": self._current_key_idx + 1 if self.api_keys else 0,
            "active_key_masked": mask_key(self.current_key) if self.current_key else "None",
            "model_name": self.model_name,
        }

    def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
    ) -> Optional[str]:
        """
        Generates text using the Gemini model with automatic failover rotation.
        If Key 1 fails or hits a quota/rate limit, Key 2 is tried, then Key 3.
        Returns None if all keys fail, allowing callers to fall back to rule-based logic.
        """
        if not self.is_available:
            return None

        total_keys = len(self.api_keys)
        attempts = 0

        # Try up to total_keys times, advancing rotation on failure
        while attempts < total_keys:
            idx = (self._current_key_idx + attempts) % total_keys
            key = self.api_keys[idx]
            client = self._get_client_for_key(key)

            if client is None:
                attempts += 1
                continue

            try:
                config = (
                    types.GenerateContentConfig(
                        temperature=temperature,
                        system_instruction=system_instruction,
                    )
                    if system_instruction
                    else types.GenerateContentConfig(temperature=temperature)
                )

                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )

                if response and response.text:
                    # Successfully completed using key at index idx.
                    # Update current_key_idx to stay on working key.
                    self._current_key_idx = idx
                    return response.text.strip()

                attempts += 1

            except Exception as e:
                err_msg = str(e)
                logger.warning(
                    f"Gemini API call failed on Key {idx + 1}/{total_keys} ({mask_key(key)}): {err_msg}. "
                    f"Rotating to next key..."
                )
                attempts += 1

        logger.warning(
            f"All {total_keys} configured Gemini API key(s) failed or exceeded quota limits. "
            "Gracefully falling back to deterministic rule-based output."
        )
        return None

    def synthesize_grounded_answer(
        self,
        question: str,
        evidence_passages: List[Dict[str, Any]],
        citations: List[Dict[str, Any]],
        temporal_notes: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Synthesizes a grounded answer using Gemini with failover rotation.
        Strictly enforces:
          - Grounding in provided evidence only.
          - Exact citation markers [1], [2].
          - No unearned supersession assumptions.
        """
        if not self.is_available or not evidence_passages:
            return None

        system_instruction = (
            "You are TruthGuard-Chronos, an audit-grade policy intelligence agent.\n"
            "Your task is to synthesize a clear, grounded answer to the user's question based strictly on the provided evidence passages.\n\n"
            "STRICT RULES:\n"
            "1. Grounding: Rely ONLY on the provided evidence. Do NOT extrapolate or assume outside facts.\n"
            "2. Citations: Every factual statement or rule requirement must end with its corresponding citation tag (e.g. [1], [2]).\n"
            "3. Temporal Integrity: Never claim a newer policy automatically supersedes or overrides an older one unless explicit supersession text is present in the evidence.\n"
            "4. Format: State the source policy context, list key provisions cleanly with bullet points, and include any temporal or provenance notes at the end.\n"
        )

        evidence_text_parts = []
        for c in citations:
            c_id = c.get("citation_id")
            fname = c.get("filename", "")
            title = c.get("document_title") or fname
            date = c.get("effective_or_issue_date") or "Date unspecified"
            snippet = c.get("quoted_snippet") or ""
            evidence_text_parts.append(
                f"[Citation {c_id}] Document: '{title}' ({fname}), Date: {date}\nExcerpt: \"{snippet}\""
            )

        prompt = (
            f"Question: {question}\n\n"
            f"Available Evidence Passages:\n"
            + "\n\n".join(evidence_text_parts)
            + "\n\n"
        )

        if temporal_notes:
            prompt += "Temporal / Provenance Graph Notes:\n" + "\n".join(f"- {n}" for n in temporal_notes) + "\n\n"

        prompt += "Draft a professional, grounded answer with exact citation references [N]."

        return self.generate_text(
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=0.1,
        )


# Global singleton instance
_gemini_client_instance: Optional[GeminiClient] = None


def get_gemini_client() -> GeminiClient:
    """
    Returns the singleton GeminiClient instance.
    Refreshes keys if environment variables have changed.
    """
    global _gemini_client_instance
    current_keys = collect_configured_api_keys()

    if _gemini_client_instance is None:
        _gemini_client_instance = GeminiClient()
    elif _gemini_client_instance.api_keys != current_keys:
        _gemini_client_instance = GeminiClient(api_keys=current_keys)

    return _gemini_client_instance
