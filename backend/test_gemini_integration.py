"""
Unit and Integration Tests for Gemini LLM Provider with Multi-Key Failover in TruthGuard-Chronos.

Verifies:
  1. Multi-Key configuration collection (GEMINI_API_KEY_1, GEMINI_API_KEY_2, GEMINI_API_KEY_3).
  2. Automatic failover: When Key 1 fails/exceeds quota, Key 2 triggers; when Key 2 fails, Key 3 triggers.
  3. Safe handling of environment variables (no hardcoded secrets).
  4. Graceful fallback to deterministic rule-based output when keys are missing or exhausted.
  5. Synthesizer Agent integration with Gemini and rule-based fallback.
  6. Critic Agent deterministic verification + advisory audit.
  7. Arbitration Agent strict precedence enforcement.
"""

import os
import sys
from unittest.mock import MagicMock
from pathlib import Path

backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from gemini_client import (
    GeminiClient,
    get_gemini_client,
    collect_configured_api_keys,
    mask_key,
    DEFAULT_MODEL,
    GENAI_AVAILABLE,
)
from synthesizer_agent import SynthesizerAgent
from critic_agent import CriticAgent
from arbitration_agent import ArbitrationAgent
from tpcg import TemporalProvenanceConflictGraph


def test_multi_key_collection():
    print("--- 1. Testing Multi-Key Configuration Collection ---")
    # Save original env
    saved = {k: os.environ.get(k) for k in ["GEMINI_API_KEY_1", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_API_KEYS", "GEMINI_API_KEY"]}
    
    try:
        # Clear existing keys for test
        for k in saved:
            if k in os.environ:
                del os.environ[k]

        # Case A: 3 individual keys
        os.environ["GEMINI_API_KEY_1"] = "key-alpha-111111111"
        os.environ["GEMINI_API_KEY_2"] = "key-beta-222222222"
        os.environ["GEMINI_API_KEY_3"] = "key-gamma-333333333"

        keys = collect_configured_api_keys()
        assert len(keys) == 3, f"Expected 3 keys, got {len(keys)}"
        assert keys[0] == "key-alpha-111111111"
        assert keys[1] == "key-beta-222222222"
        assert keys[2] == "key-gamma-333333333"
        print(f"[PASS] 3 individual keys collected in order: {[mask_key(k) for k in keys]}")

        # Case B: Comma-separated keys
        del os.environ["GEMINI_API_KEY_1"]
        del os.environ["GEMINI_API_KEY_2"]
        del os.environ["GEMINI_API_KEY_3"]
        os.environ["GEMINI_API_KEYS"] = "key-a1, key-b2, key-c3"

        keys_csv = collect_configured_api_keys()
        assert keys_csv == ["key-a1", "key-b2", "key-c3"]
        print("[PASS] Comma-separated GEMINI_API_KEYS collected and parsed correctly")

    finally:
        # Restore env
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
            elif k in os.environ:
                del os.environ[k]


def test_automatic_key_failover():
    print("\n--- 2. Testing 3-Key Automatic Failover Rotation ---")
    keys = ["key-fail-1", "key-fail-2", "key-success-3"]
    client = GeminiClient(api_keys=keys)
    assert client.key_count == 3

    # Mock client behavior to simulate:
    # Key 1 throws 429 Quota Exceeded
    # Key 2 throws 429 Rate Limit Exceeded
    # Key 3 succeeds with text output
    calls_recorded = []

    mock_client_1 = MagicMock()
    def raise_429_quota(*args, **kwargs):
        calls_recorded.append("key-fail-1")
        raise RuntimeError("429 ResourceExhausted: Quota exceeded for quota metric 'GenerateContent'")
    mock_client_1.models.generate_content.side_effect = raise_429_quota

    mock_client_2 = MagicMock()
    def raise_429_rate(*args, **kwargs):
        calls_recorded.append("key-fail-2")
        raise RuntimeError("429 RateLimitExceeded: Requests per minute limit exceeded")
    mock_client_2.models.generate_content.side_effect = raise_429_rate

    mock_client_3 = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Answer generated successfully by Key 3"
    def succeed_call(*args, **kwargs):
        calls_recorded.append("key-success-3")
        return mock_response
    mock_client_3.models.generate_content.side_effect = succeed_call

    # Inject mock clients
    client._clients = {
        "key-fail-1": mock_client_1,
        "key-fail-2": mock_client_2,
        "key-success-3": mock_client_3,
    }

    result = client.generate_text("Test prompt with 3 keys")
    assert result == "Answer generated successfully by Key 3"
    assert calls_recorded == ["key-fail-1", "key-fail-2", "key-success-3"], f"Calls were: {calls_recorded}"
    print("[PASS] Verified full failover chain: Key 1 failed (429) -> Key 2 failed (429) -> Key 3 succeeded!")

    # Test when all 3 keys fail: should return None and not crash
    mock_client_3.models.generate_content.side_effect = RuntimeError("All exhausted")
    all_fail_result = client.generate_text("Prompt when all fail")
    assert all_fail_result is None, "When all keys fail, client must safely return None for rule-based fallback"
    print("[PASS] When all keys are exhausted, safely returns None to trigger rule-based fallback")


def test_synthesizer_with_fallback():
    print("\n--- 3. Testing Synthesizer Agent with Fallback ---")
    tpcg = TemporalProvenanceConflictGraph()
    tpcg.add_document_node(
        saved_filename="sample_travel.txt",
        original_filename="sample_travel.txt",
        metadata={
            "document_title": "Official Travel Guidelines",
            "effective_date": "2024-01-01",
            "version_number": "1.0",
            "policy_or_document_identifier": "POL-TRV-2024",
            "geographic_or_organizational_scope": "National",
        },
        raw_text="Official Travel Guidelines\nAll employees are permitted to travel by Vande Bharat Express on official tours in Chair Car tier.",
    )

    synth = SynthesizerAgent(tpcg=tpcg, upload_dir=backend_dir / "uploads")
    res = synth.run("Can employees travel by Vande Bharat Express on official tours?", top_k=3)

    assert res["is_sufficiently_supported"] is True, "Expected evidence to be supported"
    assert "draft_answer" in res and len(res["draft_answer"]) > 0
    assert len(res["citations"]) > 0
    print("[PASS] Synthesizer produced grounded draft answer with citations [1]")


def test_critic_agent_deterministic_checks():
    print("\n--- 4. Testing Critic Agent Deterministic Verification ---")
    tpcg = TemporalProvenanceConflictGraph()
    critic = CriticAgent(tpcg=tpcg, upload_dir=backend_dir / "uploads")

    draft_unsupported = "All employees are entitled to private helicopter transport on every local commute."
    res = critic.run("What are the travel rules?", draft_answer=draft_unsupported, top_k=3)

    assert res["critic_status"] in ("FLAG", "ABSTAIN")
    print(f"[PASS] Critic successfully caught unverifiable draft (Status: {res['critic_status']})")


def test_arbitration_agent_rule_enforcement():
    print("\n--- 5. Testing Arbitration Agent Rule Enforcement ---")
    tpcg = TemporalProvenanceConflictGraph()
    arb = ArbitrationAgent(tpcg=tpcg, upload_dir=backend_dir / "uploads")

    res = arb.run("What is the reimbursement limit for quantum computing hardware?", top_k=3)
    assert res["outcome"] == "ABSTAIN", "Expected ABSTAIN on question with zero supporting evidence"
    print("[PASS] Arbitration Agent strictly enforced deterministic ABSTAIN on missing evidence")


if __name__ == "__main__":
    test_multi_key_collection()
    test_automatic_key_failover()
    test_synthesizer_with_fallback()
    test_critic_agent_deterministic_checks()
    test_arbitration_agent_rule_enforcement()
    print("\n=== ALL GEMINI INTEGRATION & FAILOVER TESTS PASSED SUCCESSFULLY! ===")
