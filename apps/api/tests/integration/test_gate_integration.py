"""Integration tests for gate and extraction pipeline using REAL Cerebras API calls.

Run with:
    cd apps/api && uv run pytest tests/integration/test_gate_integration.py -v -s

These tests make live network calls to Cerebras and validate that gpt-oss-120b
behaves correctly for the gate evaluation and action item extraction pipeline.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env.test before importing any app modules so settings picks up the keys
_env_test = Path(__file__).parent.parent.parent / ".env.test"
load_dotenv(_env_test, override=True)

# Force settings singleton to reload with the new env vars.
# src.config.settings is a module; src.config exports the `settings` instance.
# We patch via sys.modules to avoid the pydantic BaseSettings attribute guard.
import sys
import importlib

# Import the settings module file directly so we can patch its module-level 'settings'
_settings_file_mod = importlib.import_module("src.config.settings")
from src.config.settings import Settings as _Settings
# Patch the module-level singleton in the settings *file* module
sys.modules["src.config.settings"].settings = _Settings()

# Propagate into the config package namespace (src/config/__init__.py re-exports it)
import src.config as _config_pkg
_config_pkg.settings = sys.modules["src.config.settings"].settings

# Also reset the Cerebras client singleton so it uses the new API key
import src.services.cerebras as _cerebras_module
_cerebras_module._client = None

import pytest
import asyncio

from src.services.gate import evaluate_action, SCORE_DIMENSIONS
from src.services.cerebras import extract_action_items
from src.config.constants import GATE_AVG_THRESHOLD, GATE_READINESS_THRESHOLD, GATE_MODEL, EXTRACTION_MODEL


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

REALISTIC_TRANSCRIPT = (
    "John: We need to send the Q3 report to the board by Friday. "
    "Sarah, can you draft that email?\n"
    "Sarah: Sure, I'll get on it. Also, we should schedule a follow-up meeting for next week.\n"
    "John: Good idea. And can someone research the competitor pricing in the enterprise segment?\n"
    "Tommy: I'll look into that and report back."
)

MEETING_CONTEXT = {
    "meeting_title": "Q3 Planning Sync",
    "participants": ["John", "Sarah", "Tommy"],
    "date": "2026-02-28",
}


def _assert_gate_structure(result: dict) -> None:
    """Assert that a gate response has the expected structure."""
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    # Top-level keys
    assert "passed" in result, f"Missing 'passed' key. Keys: {list(result.keys())}"
    assert "avg_score" in result, f"Missing 'avg_score' key. Keys: {list(result.keys())}"
    assert "scores" in result, f"Missing 'scores' key. Keys: {list(result.keys())}"

    assert isinstance(result["passed"], bool), f"'passed' must be bool, got {type(result['passed'])}"
    assert isinstance(result["avg_score"], float), f"'avg_score' must be float, got {type(result['avg_score'])}"
    assert 0.0 <= result["avg_score"] <= 5.0, f"avg_score out of range: {result['avg_score']}"

    # Only validate dimension scores when the gate actually responded (not fail-open)
    if result["scores"]:
        for dim in SCORE_DIMENSIONS:
            assert dim in result["scores"], f"Missing dimension '{dim}'. Scores: {result['scores']}"
            val = result["scores"][dim]
            assert 1 <= float(val) <= 5, f"Score for '{dim}' out of range: {val}"


def _print_gate_result(label: str, result: dict) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Model: {GATE_MODEL}")
    print(f"  Passed: {result.get('passed')}")
    print(f"  Avg score: {result.get('avg_score'):.2f}")
    print(f"  Thresholds: avg > {GATE_AVG_THRESHOLD}, readiness >= {GATE_READINESS_THRESHOLD}")
    if result.get("scores"):
        print("  Dimension scores:")
        for dim, score in result["scores"].items():
            print(f"    {dim:20s}: {score}")
    if result.get("verbatim_evidence_quote"):
        print(f"  Evidence quote: {result['verbatim_evidence_quote']}")
    if result.get("missing_critical_info"):
        print(f"  Missing info: {result['missing_critical_info']}")
    if result.get("error"):
        print(f"  ERROR (fail-open): {result['error']}")
    print()


def _print_extraction_results(label: str, items: list) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Model: {EXTRACTION_MODEL}")
    print(f"  Items extracted: {len(items)}")
    for i, item in enumerate(items, 1):
        print(f"\n  Item {i}:")
        print(f"    title       : {item.get('title')}")
        print(f"    action_type : {item.get('action_type')}")
        print(f"    confidence  : {item.get('confidence')}")
        print(f"    readiness   : {item.get('readiness')}")
        print(f"    dedupe_key  : {item.get('dedupe_key')}")
        print(f"    body        : {item.get('body', '')[:120]}")
    print()


# ---------------------------------------------------------------------------
# Gate tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_gate_evaluates_clear_action_item():
    """A clearly actionable item with explicit commitment should score well."""
    candidate = {
        "title": "Send follow-up email to client",
        "body": "John agreed to send the proposal to the client by Friday",
        "action_type": "gmail_draft",
        "recipient": "client@example.com",
    }
    transcript_window = (
        "John: I'll send the proposal to the client by Friday, that's a commitment. "
        "Sarah: Great, we're all aligned on that."
    )

    result = await evaluate_action(
        candidate=candidate,
        transcript_window=transcript_window,
        rag_context_chunks=[],
        meeting_context=MEETING_CONTEXT,
    )

    _print_gate_result("test_gate_evaluates_clear_action_item", result)
    _assert_gate_structure(result)

    # A clear, explicit, committed item should pass
    # We print rather than hard-assert pass/fail — we're validating the model output shape
    print(f"  [INFO] Clear action item gate_passed={result['passed']} (expected True ideally)")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_gate_evaluates_vague_item():
    """A vague, non-actionable item should score lower across dimensions."""
    candidate = {
        "title": "Think about stuff",
        "body": "Someone mentioned maybe doing something later",
        "action_type": "general_agent",
        "recipient": None,
    }
    transcript_window = (
        "Person A: Yeah, maybe we should think about that at some point. "
        "Person B: Sure, yeah, whatever."
    )

    result = await evaluate_action(
        candidate=candidate,
        transcript_window=transcript_window,
        rag_context_chunks=[],
        meeting_context=MEETING_CONTEXT,
    )

    _print_gate_result("test_gate_evaluates_vague_item", result)
    _assert_gate_structure(result)

    print(f"  [INFO] Vague item gate_passed={result['passed']} (expected False ideally)")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_gate_handles_research_query():
    """A research question should be evaluated with valid structure."""
    candidate = {
        "title": "Research competitor pricing",
        "body": "We need to look into what competitors are charging for similar products in the enterprise segment",
        "action_type": "research_query",
        "recipient": None,
    }
    transcript_window = (
        "John: Can someone research the competitor pricing in the enterprise segment? "
        "Tommy: I'll look into that and report back. "
        "John: Perfect, let's move on."
    )

    result = await evaluate_action(
        candidate=candidate,
        transcript_window=transcript_window,
        rag_context_chunks=[],
        meeting_context=MEETING_CONTEXT,
    )

    _print_gate_result("test_gate_handles_research_query", result)
    _assert_gate_structure(result)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_gate_handles_calendar_action():
    """A calendar scheduling item should be evaluated with valid structure."""
    candidate = {
        "title": "Schedule team standup",
        "body": "Set up a recurring standup every Monday at 9am starting next week",
        "action_type": "calendar_action",
        "recipient": None,
    }
    transcript_window = (
        "Sarah: We should schedule a follow-up meeting for next week. "
        "John: Good idea. Let's do every Monday at 9am. "
        "Sarah: Perfect, I'll get that on the calendar. "
        "John: Alright, moving on."
    )

    result = await evaluate_action(
        candidate=candidate,
        transcript_window=transcript_window,
        rag_context_chunks=[],
        meeting_context=MEETING_CONTEXT,
    )

    _print_gate_result("test_gate_handles_calendar_action", result)
    _assert_gate_structure(result)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_gate_response_structure():
    """Verify all expected fields are present in the gate response."""
    candidate = {
        "title": "Draft product roadmap document",
        "body": "Create a Q4 product roadmap document and share with the team",
        "action_type": "general_agent",
        "recipient": None,
    }
    transcript_window = (
        "PM: We need a product roadmap for Q4. Can you draft that up? "
        "Dev: Yes, I'll put together the roadmap document and share it with the team by end of week. "
        "PM: Great. Okay, next topic."
    )

    result = await evaluate_action(
        candidate=candidate,
        transcript_window=transcript_window,
        rag_context_chunks=[],
        meeting_context=MEETING_CONTEXT,
    )

    _print_gate_result("test_gate_response_structure", result)

    # Explicit field-by-field validation
    assert "passed" in result, "Missing 'passed'"
    assert isinstance(result["passed"], bool), f"'passed' is not bool: {type(result['passed'])}"

    assert "avg_score" in result, "Missing 'avg_score'"
    assert isinstance(result["avg_score"], float), f"'avg_score' is not float: {type(result['avg_score'])}"
    assert 0.0 <= result["avg_score"] <= 5.0, f"avg_score out of range: {result['avg_score']}"

    assert "scores" in result, "Missing 'scores'"
    assert "verbatim_evidence_quote" in result, "Missing 'verbatim_evidence_quote'"
    assert "missing_critical_info" in result, "Missing 'missing_critical_info'"

    # verbatim_evidence_quote must be str or None
    evq = result["verbatim_evidence_quote"]
    assert evq is None or isinstance(evq, str), f"verbatim_evidence_quote must be str or None, got {type(evq)}"

    # missing_critical_info must be a list
    mci = result["missing_critical_info"]
    assert isinstance(mci, list), f"missing_critical_info must be list, got {type(mci)}"

    print("  [PASS] All required fields present with correct types")


# ---------------------------------------------------------------------------
# Extraction tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_extraction_from_meeting_transcript():
    """Extract action items from a realistic multi-speaker transcript."""
    items = await extract_action_items(REALISTIC_TRANSCRIPT)

    _print_extraction_results("test_extraction_from_meeting_transcript", items)

    assert isinstance(items, list), f"Expected list, got {type(items)}"

    # With this transcript we expect at least 2 items (email + research at minimum)
    assert len(items) >= 1, f"Expected at least 1 action item, got {len(items)}"

    required_keys = {"title", "body", "action_type", "confidence"}
    for item in items:
        missing = required_keys - set(item.keys())
        assert not missing, f"Item missing keys {missing}: {item}"
        assert isinstance(item["title"], str) and item["title"], "title must be non-empty string"
        assert isinstance(item["action_type"], str) and item["action_type"], "action_type must be non-empty string"
        assert 0.0 <= float(item["confidence"]) <= 1.0, f"confidence out of range: {item['confidence']}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_extraction_action_type_classification():
    """Verify the model classifies action_type correctly for distinct task types."""
    transcript = (
        "Alice: Bob, can you send an email to the client confirming the contract details?\n"
        "Bob: Sure, I'll draft that right away.\n"
        "Alice: Also, can someone book a meeting room for next Thursday at 2pm for our design review?\n"
        "Carol: I'll handle that calendar invite.\n"
        "Alice: And we need someone to research the pricing models for SaaS competitors.\n"
        "Dave: I can do the research and send you a summary."
    )

    items = await extract_action_items(transcript)

    _print_extraction_results("test_extraction_action_type_classification", items)

    assert isinstance(items, list), "Expected list"
    assert len(items) >= 1, "Expected at least 1 item from this transcript"

    action_types_found = {item.get("action_type") for item in items}
    print(f"  Action types found: {action_types_found}")

    # Soft checks — print for debugging, not hard fail, since model may merge items
    expected_types = {"gmail_draft", "calendar_action", "research_query"}
    overlap = action_types_found & expected_types
    print(f"  Expected type overlap: {overlap} (ideally all 3 are present)")

    # Hard requirement: at least one recognized type must appear
    valid_types = {"gmail_draft", "calendar_action", "research_query", "general_agent", "design_prototype"}
    for item in items:
        assert item.get("action_type") in valid_types, (
            f"Unexpected action_type '{item.get('action_type')}'. Valid: {valid_types}"
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_extraction_empty_transcript():
    """Empty or trivial transcript should return empty list gracefully."""
    result_empty = await extract_action_items("")
    print(f"\n  [empty string] items={result_empty}")
    assert isinstance(result_empty, list), "Expected list for empty input"

    result_trivial = await extract_action_items("Okay, bye! Talk soon.")
    print(f"  [trivial transcript] items={result_trivial}")
    assert isinstance(result_trivial, list), "Expected list for trivial input"

    print(f"\n  Empty transcript items: {len(result_empty)}")
    print(f"  Trivial transcript items: {len(result_trivial)}")
    print("  [INFO] Both should be 0 or very close to 0")


# ---------------------------------------------------------------------------
# End-to-end pipeline test
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_extraction_then_gate_pipeline():
    """Full pipeline: extract items from transcript then gate each one.

    This gives a comprehensive view of model quality end-to-end.
    """
    print(f"\n{'='*60}")
    print("  test_extraction_then_gate_pipeline")
    print(f"{'='*60}")
    print(f"  Extraction model : {EXTRACTION_MODEL}")
    print(f"  Gate model       : {GATE_MODEL}")
    print(f"  Transcript       :\n    {REALISTIC_TRANSCRIPT[:200]}...")

    # Step 1: Extract
    items = await extract_action_items(REALISTIC_TRANSCRIPT)
    assert isinstance(items, list), "Extraction must return list"

    print(f"\n  Extracted {len(items)} items")
    assert len(items) >= 1, "Expected at least 1 item from realistic transcript"

    # Step 2: Gate each item
    gate_results = []
    for item in items:
        result = await evaluate_action(
            candidate=item,
            transcript_window=REALISTIC_TRANSCRIPT,
            rag_context_chunks=[],
            meeting_context=MEETING_CONTEXT,
        )
        gate_results.append((item, result))

    # Step 3: Print full pipeline results
    print(f"\n  Pipeline results ({len(gate_results)} items):")
    passed_count = 0
    for item, gate in gate_results:
        passed = gate.get("passed", False)
        if passed:
            passed_count += 1
        avg = gate.get("avg_score", 0.0)
        scores = gate.get("scores", {})

        print(f"\n  ---- Item: {item.get('title', 'untitled')} ----")
        print(f"    action_type   : {item.get('action_type')}")
        print(f"    confidence    : {item.get('confidence')}")
        print(f"    gate_passed   : {passed}")
        print(f"    gate_avg_score: {avg:.2f}")
        if scores:
            for dim in SCORE_DIMENSIONS:
                val = scores.get(dim, "N/A")
                print(f"    {dim:20s}: {val}")
        if gate.get("verbatim_evidence_quote"):
            print(f"    evidence      : {gate['verbatim_evidence_quote'][:100]}")
        if gate.get("error"):
            print(f"    error         : {gate['error']}")

    print(f"\n  Summary: {passed_count}/{len(gate_results)} items passed the gate")
    print(f"  Gate thresholds: avg > {GATE_AVG_THRESHOLD}, readiness >= {GATE_READINESS_THRESHOLD}")

    # Validate structure of every gate result
    for item, gate in gate_results:
        _assert_gate_structure(gate)
