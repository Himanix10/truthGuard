"""
Reusable Gemini API Client Module for TruthGuard-Chronos with Multi-Key Failover.
Re-exports GeminiClient and get_gemini_client for clean top-level imports.
"""

from app.gemini_client import (
    GeminiClient,
    get_gemini_client,
    collect_configured_api_keys,
    mask_key,
    DEFAULT_MODEL,
    GENAI_AVAILABLE,
)

__all__ = [
    "GeminiClient",
    "get_gemini_client",
    "collect_configured_api_keys",
    "mask_key",
    "DEFAULT_MODEL",
    "GENAI_AVAILABLE",
]
