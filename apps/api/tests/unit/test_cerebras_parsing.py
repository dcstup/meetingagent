"""Unit tests for Cerebras response parsing in extract_action_items."""
import json
from unittest.mock import patch, MagicMock
import pytest


def _mock_cerebras_response(content: str):
    """Create a mock Cerebras API response."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = content
    return mock_response


@pytest.mark.asyncio
class TestCerebrasExtraction:

    async def test_parses_action_items_key(self):
        resp = _mock_cerebras_response(json.dumps({
            "action_items": [
                {"title": "Send email", "body": "Send email to Sarah", "confidence": 0.9,
                 "action_type": "gmail_draft", "recipient": "sarah@example.com", "dedupe_key": "email-sarah"}
            ]
        }))
        with patch("src.services.cerebras.get_client") as mock:
            mock.return_value.chat.completions.create.return_value = resp
            from src.services.cerebras import extract_action_items
            items = await extract_action_items("We need to email Sarah")

        assert len(items) == 1
        assert items[0]["title"] == "Send email"

    async def test_parses_items_key(self):
        resp = _mock_cerebras_response(json.dumps({
            "items": [{"title": "Book room", "confidence": 0.8, "body": "Book conf room",
                        "action_type": "generic_draft", "dedupe_key": "book-room"}]
        }))
        with patch("src.services.cerebras.get_client") as mock:
            mock.return_value.chat.completions.create.return_value = resp
            from src.services.cerebras import extract_action_items
            items = await extract_action_items("Book a conference room")

        assert len(items) == 1

    async def test_parses_arbitrary_key(self):
        """Cerebras might use any key name for the list."""
        resp = _mock_cerebras_response(json.dumps({
            "tasks": [{"title": "Review PR", "confidence": 0.7, "body": "Review the PR",
                        "action_type": "generic_draft", "dedupe_key": "review-pr"}]
        }))
        with patch("src.services.cerebras.get_client") as mock:
            mock.return_value.chat.completions.create.return_value = resp
            from src.services.cerebras import extract_action_items
            items = await extract_action_items("Review the PR")

        assert len(items) == 1

    async def test_parses_bare_list(self):
        resp = _mock_cerebras_response(json.dumps([
            {"title": "Follow up", "confidence": 0.85, "body": "Follow up with client",
             "action_type": "generic_draft", "dedupe_key": "follow-up"}
        ]))
        with patch("src.services.cerebras.get_client") as mock:
            mock.return_value.chat.completions.create.return_value = resp
            from src.services.cerebras import extract_action_items
            items = await extract_action_items("Follow up with client")

        assert len(items) == 1

    async def test_filters_non_dict_items(self):
        """If Cerebras returns strings mixed in, they should be filtered out."""
        resp = _mock_cerebras_response(json.dumps({
            "action_items": [
                "not a dict",
                {"title": "Real item", "confidence": 0.9, "body": "Do something",
                 "action_type": "generic_draft", "dedupe_key": "real"},
                42,
            ]
        }))
        with patch("src.services.cerebras.get_client") as mock:
            mock.return_value.chat.completions.create.return_value = resp
            from src.services.cerebras import extract_action_items
            items = await extract_action_items("Some transcript")

        assert len(items) == 1
        assert items[0]["title"] == "Real item"

    async def test_empty_response(self):
        resp = _mock_cerebras_response(json.dumps({"action_items": []}))
        with patch("src.services.cerebras.get_client") as mock:
            mock.return_value.chat.completions.create.return_value = resp
            from src.services.cerebras import extract_action_items
            items = await extract_action_items("Just chatting")

        assert items == []

    async def test_invalid_json_returns_empty(self):
        resp = _mock_cerebras_response("not valid json at all")
        with patch("src.services.cerebras.get_client") as mock:
            mock.return_value.chat.completions.create.return_value = resp
            from src.services.cerebras import extract_action_items
            items = await extract_action_items("Some transcript")

        assert items == []

    async def test_parses_design_prototype_action_type(self):
        resp = _mock_cerebras_response(json.dumps({
            "action_items": [
                {"title": "Mock up login page", "body": "Create a login page prototype",
                 "confidence": 0.9, "action_type": "design_prototype", "recipient": None,
                 "dedupe_key": "mockup-login"}
            ]
        }))
        with patch("src.services.cerebras.get_client") as mock:
            mock.return_value.chat.completions.create.return_value = resp
            from src.services.cerebras import extract_action_items
            items = await extract_action_items("Let's mock up a login page")

        assert len(items) == 1
        assert items[0]["action_type"] == "design_prototype"

    async def test_dict_with_no_list_values(self):
        resp = _mock_cerebras_response(json.dumps({"message": "No action items found"}))
        with patch("src.services.cerebras.get_client") as mock:
            mock.return_value.chat.completions.create.return_value = resp
            from src.services.cerebras import extract_action_items
            items = await extract_action_items("Just chatting")

        assert items == []
