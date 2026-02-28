"""Tests for the adapter registry and RecallAdapter webhook parsing."""

import pytest

from src.adapters import get_adapter, _registry
from src.adapters.base import AdapterStatus, AdapterType, NormalizedUtterance
from src.adapters.recall.adapter import RecallAdapter
from src.adapters.recall.webhook_parser import parse_transcript_payload, parse_status_payload
from src.adapters.deepgram.adapter import DeepgramAdapter


class TestAdapterRegistry:
    def test_recall_registered(self):
        assert "recall" in _registry

    def test_deepgram_registered(self):
        assert "deepgram" in _registry

    def test_get_adapter_recall(self):
        adapter = get_adapter("recall")
        assert isinstance(adapter, RecallAdapter)
        assert adapter.adapter_type == AdapterType.RECALL

    def test_get_adapter_deepgram(self):
        adapter = get_adapter("deepgram")
        assert isinstance(adapter, DeepgramAdapter)
        assert adapter.adapter_type == AdapterType.DEEPGRAM

    def test_get_adapter_unknown_raises(self):
        with pytest.raises(KeyError, match="Unknown adapter"):
            get_adapter("nonexistent")


class TestRecallWebhookParser:
    def test_parse_transcript_with_words(self):
        payload = {
            "bot_id": "bot-123",
            "data": {
                "data": {
                    "words": [
                        {"text": "Hello", "start_timestamp": {"relative": 1.5}},
                        {"text": "world", "start_timestamp": {"relative": 2.0}},
                    ],
                    "participant": {"name": "Alice"},
                }
            },
        }
        bot_id, utterances = parse_transcript_payload(payload)
        assert bot_id == "bot-123"
        assert len(utterances) == 1
        assert utterances[0].speaker == "Alice"
        assert utterances[0].text == "Hello world"
        assert utterances[0].timestamp_ms == 1500

    def test_parse_transcript_fallback_format(self):
        payload = {
            "bot_id": "bot-456",
            "data": {
                "transcript": {
                    "speaker": "Bob",
                    "text": "Testing fallback",
                    "timestamp": 3.0,
                }
            },
        }
        bot_id, utterances = parse_transcript_payload(payload)
        assert bot_id == "bot-456"
        assert len(utterances) == 1
        assert utterances[0].speaker == "Bob"
        assert utterances[0].text == "Testing fallback"
        assert utterances[0].timestamp_ms == 3000

    def test_parse_transcript_empty_text_ignored(self):
        payload = {
            "bot_id": "bot-789",
            "data": {
                "data": {
                    "words": [{"text": "  ", "start_timestamp": {"relative": 0}}],
                    "participant": {"name": "X"},
                }
            },
        }
        bot_id, utterances = parse_transcript_payload(payload)
        assert utterances == []

    def test_parse_transcript_no_data(self):
        payload = {"bot_id": "bot-000", "data": {}}
        bot_id, utterances = parse_transcript_payload(payload)
        assert utterances == []

    def test_parse_transcript_bot_id_nested(self):
        payload = {"data": {"bot_id": "nested-id", "data": {"words": [{"text": "hi", "start_timestamp": {"relative": 0}}], "participant": {"name": "C"}}}}
        bot_id, _ = parse_transcript_payload(payload)
        assert bot_id == "nested-id"

    def test_parse_status_done(self):
        payload = {"bot_id": "bot-1", "data": {"status": {"code": "done"}}}
        bot_id, status = parse_status_payload(payload)
        assert bot_id == "bot-1"
        assert status == AdapterStatus.ENDED

    def test_parse_status_fatal(self):
        payload = {"bot_id": "bot-2", "data": {"status": {"code": "fatal"}}}
        _, status = parse_status_payload(payload)
        assert status == AdapterStatus.ENDED

    def test_parse_status_recording(self):
        payload = {"bot_id": "bot-3", "data": {"status": {"code": "in_call_recording"}}}
        _, status = parse_status_payload(payload)
        assert status == AdapterStatus.ACTIVE

    def test_parse_status_other(self):
        payload = {"bot_id": "bot-4", "data": {"status": {"code": "joining"}}}
        _, status = parse_status_payload(payload)
        assert status == AdapterStatus.CONNECTING


class TestRecallAdapterParseWebhook:
    def test_adapter_delegates_to_parser(self):
        adapter = RecallAdapter()
        payload = {
            "bot_id": "b1",
            "data": {"data": {"words": [{"text": "yo", "start_timestamp": {"relative": 0}}], "participant": {"name": "Z"}}},
        }
        bot_id, utterances = adapter.parse_webhook(payload)
        assert bot_id == "b1"
        assert len(utterances) == 1
        assert utterances[0].speaker == "Z"


class TestDeepgramAdapterStubs:
    @pytest.mark.asyncio
    async def test_start_session_not_implemented(self):
        adapter = DeepgramAdapter()
        with pytest.raises(NotImplementedError):
            await adapter.start_session("ws-1", "")

    @pytest.mark.asyncio
    async def test_stop_session_not_implemented(self):
        adapter = DeepgramAdapter()
        with pytest.raises(NotImplementedError):
            await adapter.stop_session("sess-1")

    def test_parse_webhook_not_implemented(self):
        adapter = DeepgramAdapter()
        with pytest.raises(NotImplementedError):
            adapter.parse_webhook({})
