"""Tests for Task 1: constant values."""
from src.config.constants import EXTRACTION_INTERVAL_S, ROLLING_BUFFER_WINDOW_S


def test_extraction_interval():
    assert EXTRACTION_INTERVAL_S == 30


def test_rolling_buffer_window():
    assert ROLLING_BUFFER_WINDOW_S == 45
