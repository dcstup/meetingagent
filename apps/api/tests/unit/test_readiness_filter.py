"""Tests for readiness filtering in filter_proposals.

Readiness pre-filter has been removed — all items pass through to the gate/review step
regardless of readiness value. These tests verify that readiness no longer blocks items.
"""
from src.services.extractor import filter_proposals


def test_readiness_0_passes_through():
    items = [
        {"title": "Send email to Bob", "body": "send it", "confidence": 0.9, "readiness": 0},
    ]
    result, filtered = filter_proposals(items)
    assert len(result) == 1
    assert len(filtered) == 0


def test_readiness_1_passes_through():
    items = [
        {"title": "Draft proposal", "body": "draft it", "confidence": 0.95, "readiness": 1},
    ]
    result, filtered = filter_proposals(items)
    assert len(result) == 1
    assert len(filtered) == 0


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
    """Items without readiness field should still pass."""
    items = [
        {"title": "Send email to Bob", "body": "send it", "confidence": 0.9},
    ]
    result, _ = filter_proposals(items)
    assert len(result) == 1
