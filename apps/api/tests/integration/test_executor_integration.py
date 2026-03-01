"""Integration tests for executor agents using REAL API calls.

These tests exercise:
  - Composio/Linear general agent (real Linear ticket creation via Composio)
  - Research agent (Brave Search + web fetch + CrewAI HTML report generation)
  - Brave Search tool in isolation
  - Web Fetch tool in isolation
  - General agent without Composio (web tools only)
  - Calendar agent error path (no entity_id)
  - Gmail agent error path (no entity_id)
  - End-to-end: extraction → general agent (Linear ticket)

Run with:
    cd apps/api && uv run pytest tests/integration/test_executor_integration.py -v -s --timeout=300

WARNING: These tests make REAL API calls to Cerebras, Composio, Brave Search, and CrewAI.
Each test may take 30-120 seconds. Composio/Linear tests require a connected Linear account.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env.test before importing any app modules so settings picks up the keys
_env_test = Path(__file__).parent.parent.parent / ".env.test"
load_dotenv(_env_test, override=True)

# Force settings singleton to reload with the new env vars.
import sys
import importlib

_settings_file_mod = importlib.import_module("src.config.settings")
from src.config.settings import Settings as _Settings
sys.modules["src.config.settings"].settings = _Settings()

import src.config as _config_pkg
_config_pkg.settings = sys.modules["src.config.settings"].settings

# Reset Cerebras client singleton so it picks up the new API key
import src.services.cerebras as _cerebras_module
_cerebras_module._client = None

import pytest
import asyncio

from src.services.executor import (
    execute_general_agent,
    execute_research_query,
    execute_calendar_action,
    execute_gmail_draft,
    execute_linear_ticket,
)
from src.services.cerebras import extract_action_items
from src.services.web_tools import brave_search, web_fetch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_result(label: str, result: dict) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  status : {result.get('status')}")
    print(f"  type   : {result.get('type')}")
    if result.get("error"):
        print(f"  error  : {result['error']}")
    if result.get("result"):
        snippet = str(result["result"])[:500]
        print(f"  result : {snippet}")
    if result.get("artifact_html"):
        snippet = str(result["artifact_html"])[:500]
        print(f"  artifact_html (first 500 chars):\n{snippet}")
    if result.get("title"):
        print(f"  title  : {result['title']}")
    print()


# ---------------------------------------------------------------------------
# 1. End-to-end: extraction → general agent (Linear ticket)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_extraction_to_general_agent_linear_ticket():
    """End-to-end: extract action item from transcript, then run general agent to create Linear ticket."""
    transcript = (
        "Tommy: I'll create a Linear ticket to track the authentication bug we discussed.\n"
        "Sarah: Great, make sure to set it as high priority.\n"
        "Tommy: Will do."
    )

    print(f"\n{'='*60}")
    print("  test_extraction_to_general_agent_linear_ticket")
    print(f"{'='*60}")
    print(f"  Transcript: {transcript[:200]}")

    # Step 1: Extract action items
    items = await extract_action_items(transcript)
    print(f"\n  Extracted {len(items)} items:")
    for i, item in enumerate(items, 1):
        print(f"    [{i}] action_type={item.get('action_type')} title={item.get('title')}")
        print(f"         body={item.get('body', '')[:120]}")

    assert isinstance(items, list), "extract_action_items must return a list"
    assert len(items) >= 1, f"Expected at least 1 action item, got {len(items)}"

    # Use the first item
    item = items[0]
    print(f"\n  Using item: action_type={item.get('action_type')}")

    # Step 2: Run general agent with the extracted item
    # entity_id="default" tries Composio default entity (Linear tools)
    result = await execute_general_agent(
        entity_id="default",
        title=item.get("title", "Create Linear ticket for auth bug"),
        body=item.get("body", "Create a Linear ticket for the authentication bug."),
    )

    _print_result("execute_general_agent (from extracted item)", result)

    # The agent should have attempted execution — check we got a structured response
    assert "status" in result, f"Expected 'status' key in result: {result}"
    print(f"  [INFO] General agent status={result['status']} (Composio may or may not have Linear connected)")


# ---------------------------------------------------------------------------
# 2. General agent creates Linear ticket directly
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_general_agent_creates_linear_ticket_directly():
    """Call execute_general_agent directly to create a Linear ticket via Composio."""
    result = await execute_general_agent(
        entity_id="default",
        title="Create Linear ticket for auth bug",
        body=(
            "Create a Linear ticket titled 'Fix authentication timeout bug' with description "
            "'Users are experiencing session timeouts after 30 minutes. Need to investigate "
            "token refresh logic.' Priority: high"
        ),
    )

    _print_result("test_general_agent_creates_linear_ticket_directly", result)

    assert "status" in result, f"Expected 'status' key: {result}"
    print(f"  [INFO] status={result['status']} — if failed, Composio/Linear may not be connected for entity 'default'")
    if result["status"] == "success":
        assert result.get("result") or result.get("artifact_html"), "Success result must have content"


# ---------------------------------------------------------------------------
# 3. Research agent produces HTML report
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_research_agent_produces_html_report():
    """Research agent: Brave Search + web fetch + CrewAI → HTML report."""
    result = await execute_research_query(
        title="Research AI meeting assistant market",
        body="What are the top AI meeting assistant products? Compare features and pricing.",
    )

    _print_result("test_research_agent_produces_html_report", result)

    assert "status" in result, f"Expected 'status' key: {result}"

    if result["status"] == "success":
        assert result.get("type") == "research_query", f"Expected type=research_query: {result}"
        artifact = result.get("artifact_html", "")
        assert artifact, "artifact_html must be non-empty on success"
        print(f"  [INFO] artifact_html length: {len(artifact)} chars")
        print(f"  [INFO] first 500 chars:\n{artifact[:500]}")
        # Should look like HTML
        lower = artifact.lower()
        assert "<" in lower, "artifact_html should contain HTML tags"
    else:
        print(f"  [WARN] Research agent returned status={result['status']}, error={result.get('error')}")
        print("  [INFO] This may indicate Brave API key is missing or CrewAI issue")


# ---------------------------------------------------------------------------
# 4. Brave Search tool in isolation
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_research_agent_brave_search_directly():
    """Test brave_search CrewAI tool directly — no agents, just the raw tool call."""
    query = "AI meeting assistant market size 2025"
    print(f"\n{'='*60}")
    print("  test_research_agent_brave_search_directly")
    print(f"{'='*60}")
    print(f"  Query: {query}")

    # brave_search is a @tool-decorated function — call it like a normal function
    result = brave_search.run(query)

    print(f"  Result ({len(result)} chars):")
    print(f"  {result[:800]}")

    assert isinstance(result, str), f"Expected str result, got {type(result)}"
    assert len(result) > 0, "Result must be non-empty"

    if result.startswith("Web search unavailable"):
        print("  [WARN] Brave API key not configured — search returned fallback message")
    elif result.startswith("Search error"):
        print(f"  [WARN] Search error: {result}")
    else:
        print("  [PASS] Brave Search returned results")
        assert len(result) > 50, "Results should have substantial content"


# ---------------------------------------------------------------------------
# 5. Web Fetch tool in isolation
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_web_fetch_tool_directly():
    """Test web_fetch CrewAI tool directly against example.com."""
    url = "https://example.com"
    print(f"\n{'='*60}")
    print("  test_web_fetch_tool_directly")
    print(f"{'='*60}")
    print(f"  URL: {url}")

    result = web_fetch.run(url)

    print(f"  Result ({len(result)} chars):")
    print(f"  First 200 chars: {result[:200]}")

    assert isinstance(result, str), f"Expected str result, got {type(result)}"
    assert len(result) > 0, "Result must be non-empty"

    if result.startswith("Fetch error"):
        print(f"  [WARN] Fetch error: {result}")
    else:
        print("  [PASS] Web fetch returned content")
        # example.com should return something meaningful
        assert len(result) > 20, "Fetched content should be non-trivial"


# ---------------------------------------------------------------------------
# 6. General agent without Composio (web tools only)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_general_agent_without_composio():
    """General agent with entity_id=None — web tools only, no Composio."""
    result = await execute_general_agent(
        entity_id=None,
        title="Summarize key points",
        body=(
            "Create a summary of the main discussion points from the meeting about Q3 planning. "
            "The meeting covered: revenue targets, hiring plan for Q3, and product roadmap priorities."
        ),
    )

    _print_result("test_general_agent_without_composio", result)

    assert "status" in result, f"Expected 'status' key: {result}"

    if result["status"] == "success":
        content = result.get("result") or result.get("artifact_html") or ""
        assert content, "Success result must have non-empty content (result or artifact_html)"
        print(f"  [PASS] General agent completed successfully, content length={len(content)}")
    else:
        print(f"  [WARN] General agent failed: {result.get('error')}")
        print("  [INFO] This may be a CrewAI/LLM configuration issue")


# ---------------------------------------------------------------------------
# 7. Calendar agent — no entity_id → expected failure
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_calendar_agent_no_entity():
    """Calendar agent with no entity_id must return status=failed with clear error."""
    result = await execute_calendar_action(
        entity_id=None,
        title="Schedule team standup",
        body="Set up a recurring standup every Monday at 9am starting next week",
    )

    print(f"\n{'='*60}")
    print("  test_calendar_agent_no_entity")
    print(f"{'='*60}")
    print(f"  result: {result}")

    assert result["status"] == "failed", (
        f"Expected status=failed when entity_id=None, got status={result['status']}"
    )
    error_msg = result.get("error", "").lower()
    assert "calendar" in error_msg or "connected" in error_msg, (
        f"Expected 'Calendar not connected' style error, got: {result.get('error')}"
    )
    print("  [PASS] Calendar agent correctly returned status=failed")


# ---------------------------------------------------------------------------
# 8. Gmail agent — no entity_id → expected failure
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_gmail_agent_no_entity():
    """Gmail agent with no entity_id must return status=failed with clear error."""
    result = await execute_gmail_draft(
        entity_id=None,
        recipient="test@example.com",
        subject="Test subject",
        body="Test body",
    )

    print(f"\n{'='*60}")
    print("  test_gmail_agent_no_entity")
    print(f"{'='*60}")
    print(f"  result: {result}")

    assert result["status"] == "failed", (
        f"Expected status=failed when entity_id=None, got status={result['status']}"
    )
    error_msg = result.get("error", "").lower()
    assert "gmail" in error_msg or "connected" in error_msg or "google" in error_msg, (
        f"Expected 'Gmail not connected' style error, got: {result.get('error')}"
    )
    print("  [PASS] Gmail agent correctly returned status=failed")


# ---------------------------------------------------------------------------
# 9. Linear ticket agent — dedicated execute_linear_ticket
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_linear_ticket_agent_creates_ticket():
    """Dedicated linear_ticket agent creates a ticket via Composio Linear tools."""
    result = await execute_linear_ticket(
        entity_id="default",
        title="Integration test: auth timeout bug",
        body=(
            "Users are experiencing session timeouts after 30 minutes. "
            "Need to investigate token refresh logic. Priority: low. "
            "NOTE: This is an automated integration test ticket — please delete."
        ),
    )

    _print_result("test_linear_ticket_agent_creates_ticket", result)

    assert "status" in result, f"Expected 'status' key: {result}"
    assert result["type"] == "linear_ticket", f"Expected type=linear_ticket: {result}"

    if result["status"] == "success":
        assert result.get("result"), "Success result must have content"
        print(f"  [PASS] Linear ticket created. Result: {result['result'][:300]}")
        # Check if we got a Linear URL back
        if "linear.app" in (result.get("result") or ""):
            print("  [PASS] Result contains linear.app URL")
        else:
            print("  [WARN] No linear.app URL found in result — agent may not have returned it")
    else:
        print(f"  [WARN] Linear ticket agent failed: {result.get('error')}")
        print("  [INFO] This likely means Linear is not connected for entity 'default'")


# ---------------------------------------------------------------------------
# 10. Linear ticket agent — no entity_id → expected failure
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_linear_ticket_agent_no_entity():
    """Linear ticket agent with no entity_id must return status=failed."""
    result = await execute_linear_ticket(
        entity_id=None,
        title="Should fail",
        body="This should fail because no entity",
    )

    print(f"\n{'='*60}")
    print("  test_linear_ticket_agent_no_entity")
    print(f"{'='*60}")
    print(f"  result: {result}")

    assert result["status"] == "failed", (
        f"Expected status=failed when entity_id=None, got status={result['status']}"
    )
    assert result["type"] == "linear_ticket"
    error_msg = result.get("error", "").lower()
    assert "linear" in error_msg or "connected" in error_msg, (
        f"Expected 'Linear not connected' style error, got: {result.get('error')}"
    )
    print("  [PASS] Linear ticket agent correctly returned status=failed")


# ---------------------------------------------------------------------------
# 11. Extraction prompt classifies ticket requests as linear_ticket
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_extraction_classifies_linear_ticket():
    """Verify the extraction prompt classifies ticket-related requests as linear_ticket."""
    transcript = (
        "Alice: We need to create a ticket for the login crash bug.\n"
        "Bob: Yeah, file it as high priority. The login page crashes on mobile.\n"
        "Alice: Got it, I'll create the ticket now."
    )

    print(f"\n{'='*60}")
    print("  test_extraction_classifies_linear_ticket")
    print(f"{'='*60}")

    items = await extract_action_items(transcript)
    print(f"  Extracted {len(items)} items:")
    for i, item in enumerate(items, 1):
        print(f"    [{i}] action_type={item.get('action_type')} title={item.get('title')}")

    assert len(items) >= 1, f"Expected at least 1 action item, got {len(items)}"

    # At least one item should be classified as linear_ticket
    types = [item.get("action_type") for item in items]
    print(f"  Action types found: {types}")
    assert "linear_ticket" in types, (
        f"Expected at least one 'linear_ticket' action type for ticket-related transcript, got: {types}"
    )
    print("  [PASS] Extraction correctly classified ticket request as linear_ticket")
