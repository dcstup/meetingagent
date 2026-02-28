"""Tests for Task 2: readiness filtering in filter_proposals."""
from src.services.extractor import filter_proposals


def test_readiness_below_3_dropped():
    items = [
        {"title": "Send email to Bob", "body": "send it", "confidence": 0.9, "readiness": 2},
    ]
    result, _ = filter_proposals(items)
    assert len(result) == 0


def test_readiness_exactly_3_kept():
    items = [
        {"title": "Send email to Bob", "body": "send it", "confidence": 0.9, "readiness": 3},
    ]
    result, _ = filter_proposals(items)
    assert len(result) == 1


def test_readiness_5_kept():
    items = [
        {"title": "Send email to Bob", "body": "send it", "confidence": 0.9, "readiness": 5},
    ]
    result, _ = filter_proposals(items)
    assert len(result) == 1


def test_readiness_1_dropped():
    items = [
        {"title": "Draft proposal", "body": "draft it", "confidence": 0.95, "readiness": 1},
    ]
    result, _ = filter_proposals(items)
    assert len(result) == 0


def test_missing_readiness_defaults_kept():
    """Items without readiness field should still pass (backward compat)."""
    items = [
        {"title": "Send email to Bob", "body": "send it", "confidence": 0.9},
    ]
    result, _ = filter_proposals(items)
    assert len(result) == 1
