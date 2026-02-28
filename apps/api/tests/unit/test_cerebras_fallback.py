"""Tests for Cerebras response parsing, including fallback for non-JSON responses."""
import pytest
from src.services.cerebras import _parse_items


class TestParseItems:

    def test_valid_json_array(self):
        items = _parse_items('[{"title": "Send email", "confidence": 0.9}]')
        assert len(items) == 1
        assert items[0]["title"] == "Send email"

    def test_valid_json_object_with_list(self):
        items = _parse_items('{"action_items": [{"title": "Draft report"}]}')
        assert len(items) == 1

    def test_empty_array(self):
        assert _parse_items("[]") == []

    def test_markdown_code_block(self):
        content = '```json\n[{"title": "Follow up"}]\n```'
        items = _parse_items(content)
        assert len(items) == 1
        assert items[0]["title"] == "Follow up"

    def test_markdown_code_block_no_lang(self):
        content = '```\n[{"title": "Review PR"}]\n```'
        items = _parse_items(content)
        assert len(items) == 1

    def test_json_embedded_in_text(self):
        content = 'Here are the action items:\n[{"title": "Book room"}]\nDone.'
        items = _parse_items(content)
        assert len(items) == 1

    def test_completely_invalid(self):
        assert _parse_items("No action items found.") == []

    def test_non_dict_items_filtered(self):
        items = _parse_items('[{"title": "ok"}, "not a dict", 42]')
        assert len(items) == 1
        assert items[0]["title"] == "ok"

    def test_empty_string(self):
        assert _parse_items("") == []

    def test_nested_object_no_list(self):
        items = _parse_items('{"note": "nothing found"}')
        assert items == []
