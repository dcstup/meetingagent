import time
import pytest
from src.services.extractor import RollingBuffer, filter_proposals


def test_buffer_add_and_get():
    buf = RollingBuffer(window_s=60)
    buf.add("Alice", "Hello", 0)
    buf.add("Bob", "Hi there", 1000)
    text = buf.get_text()
    assert "Alice: Hello" in text
    assert "Bob: Hi there" in text


def test_buffer_prune():
    buf = RollingBuffer(window_s=1)
    buf.add("Alice", "Old message", 0)
    buf._entries[0].added_at = time.time() - 2  # Force old
    buf.add("Bob", "New message", 1000)
    text = buf.get_text()
    assert "Old message" not in text
    assert "New message" in text


def test_buffer_size():
    buf = RollingBuffer()
    assert buf.size == 0
    buf.add("A", "text", 0)
    assert buf.size == 1


def test_filter_drop_low_confidence():
    items = [{"title": "Send email", "body": "test", "confidence": 0.3}]
    assert filter_proposals(items) == []


def test_filter_keep_high_confidence():
    items = [{"title": "Send email to Bob", "body": "test", "confidence": 0.9}]
    result = filter_proposals(items)
    assert len(result) == 1


def test_filter_uncertain_marker():
    items = [{"title": "Send update", "body": "test", "confidence": 0.6}]
    result = filter_proposals(items)
    assert len(result) == 1
    assert result[0]["title"].endswith("??")


def test_filter_no_action_verb_low_confidence():
    items = [
        {
            "title": "Meeting notes",
            "body": "notes about the meeting",
            "confidence": 0.6,
        }
    ]
    result = filter_proposals(items)
    assert len(result) == 0


def test_filter_no_action_verb_high_confidence():
    items = [
        {
            "title": "Quarterly report data",
            "body": "compile the data",
            "confidence": 0.9,
        }
    ]
    result = filter_proposals(items)
    # "compile" is an action verb in body
    assert len(result) == 1
