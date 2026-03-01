"""Tests for readiness filtering in filter_proposals."""
from src.services.extractor import filter_proposals


def test_readiness_0_dropped():
    items = [
        {"title": "Send email to Bob", "body": "send it", "confidence": 0.9, "readiness": 0},
    ]
    result, filtered = filter_proposals(items)
    assert len(result) == 0
    assert len(filtered) == 1


def test_readiness_1_kept():
    items = [
        {"title": "Draft proposal", "body": "draft it", "confidence": 0.95, "readiness": 1},
    ]
    result, _ = filter_proposals(items)
    assert len(result) == 1


def test_readiness_2_kept():
    items = [
        {"title": "Send email to Bob", "body": "send it", "confidence": 0.9, "readiness": 2},
    ]
    result, _ = filter_proposals(items)
    assert len(result) == 1


def test_readiness_3_kept():
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


def test_missing_readiness_defaults_kept():
    """Items without readiness field should still pass (backward compat)."""
    items = [
        {"title": "Send email to Bob", "body": "send it", "confidence": 0.9},
    ]
    result, _ = filter_proposals(items)
    assert len(result) == 1
