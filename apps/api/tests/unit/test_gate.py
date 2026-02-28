import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from src.services.gate import evaluate_action, _parse_gate_response


# --- Fixtures ---

GOOD_SCORES = {
    "explicitness": 5, "value": 4, "specificity": 4, "urgency": 4,
    "feasibility": 4, "evidence_strength": 4, "readiness": 5,
}

GOOD_RESPONSE = {
    "scores": GOOD_SCORES,
    "verbatim_evidence_quote": "I'll send that email to Bob tomorrow",
    "missing_critical_info": [],
}

CANDIDATE = {"title": "Email Bob", "body": "Send proposal to Bob", "action_type": "gmail_draft"}
WINDOW = "Alice: I'll send that email to Bob tomorrow\nBob: Sounds good"
RAG_CHUNKS = [{"speaker": "Alice", "text": "We discussed the proposal earlier"}]
MEETING_CTX = {"meeting_title": "Weekly sync", "participants": ["Alice", "Bob"]}


# --- _parse_gate_response tests ---

def test_parse_valid_json():
    raw = json.dumps(GOOD_RESPONSE)
    result = _parse_gate_response(raw)
    assert result["scores"]["readiness"] == 5


def test_parse_markdown_wrapped_json():
    raw = f"```json\n{json.dumps(GOOD_RESPONSE)}\n```"
    result = _parse_gate_response(raw)
    assert result["scores"]["explicitness"] == 5


def test_parse_invalid_json_returns_none():
    assert _parse_gate_response("not json at all") is None


# --- Threshold logic tests ---

@pytest.mark.asyncio
async def test_both_conditions_met_passes():
    """avg > 3.8 AND readiness >= 4 => passed=True"""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = json.dumps(GOOD_RESPONSE)

    with patch("src.services.gate.get_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value = mock_resp
        result = await evaluate_action(CANDIDATE, WINDOW, RAG_CHUNKS, MEETING_CTX)

    assert result["passed"] is True
    assert result["avg_score"] > 3.8
    assert result["scores"]["readiness"] >= 4


@pytest.mark.asyncio
async def test_high_avg_low_readiness_fails():
    """avg > 3.8 but readiness < 4 => passed=False"""
    scores = {**GOOD_SCORES, "readiness": 2}
    resp_data = {**GOOD_RESPONSE, "scores": scores}

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = json.dumps(resp_data)

    with patch("src.services.gate.get_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value = mock_resp
        result = await evaluate_action(CANDIDATE, WINDOW, RAG_CHUNKS, MEETING_CTX)

    assert result["passed"] is False


@pytest.mark.asyncio
async def test_low_avg_high_readiness_fails():
    """avg <= 3.8 but readiness >= 4 => passed=False"""
    scores = {
        "explicitness": 1, "value": 1, "specificity": 1, "urgency": 1,
        "feasibility": 1, "evidence_strength": 1, "readiness": 5,
    }
    resp_data = {**GOOD_RESPONSE, "scores": scores}

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = json.dumps(resp_data)

    with patch("src.services.gate.get_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value = mock_resp
        result = await evaluate_action(CANDIDATE, WINDOW, RAG_CHUNKS, MEETING_CTX)

    assert result["passed"] is False
    assert result["avg_score"] <= 3.8


@pytest.mark.asyncio
async def test_fail_open_on_api_error():
    """If gate call fails, default to passing."""
    with patch("src.services.gate.get_client") as mock_client:
        mock_client.return_value.chat.completions.create.side_effect = Exception("API down")
        result = await evaluate_action(CANDIDATE, WINDOW, RAG_CHUNKS, MEETING_CTX)

    assert result["passed"] is True
    assert "error" in result


@pytest.mark.asyncio
async def test_fail_open_on_bad_json():
    """If gate returns unparseable response, fail open."""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "totally not json"

    with patch("src.services.gate.get_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value = mock_resp
        result = await evaluate_action(CANDIDATE, WINDOW, RAG_CHUNKS, MEETING_CTX)

    assert result["passed"] is True
    assert "error" in result


@pytest.mark.asyncio
async def test_score_computation():
    """Verify avg_score is mean of all 7 dimensions."""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = json.dumps(GOOD_RESPONSE)

    with patch("src.services.gate.get_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value = mock_resp
        result = await evaluate_action(CANDIDATE, WINDOW, RAG_CHUNKS, MEETING_CTX)

    expected_avg = sum(GOOD_SCORES.values()) / 7
    assert abs(result["avg_score"] - expected_avg) < 0.001
