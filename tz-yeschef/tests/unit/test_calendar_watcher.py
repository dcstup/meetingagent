"""Tests for calendar_watcher meet URL extraction."""
import pytest
from src.services.calendar_watcher import extract_meet_url


class TestExtractMeetUrl:

    def test_hangout_link(self):
        event = {"hangoutLink": "https://meet.google.com/abc-defg-hij"}
        assert extract_meet_url(event) == "https://meet.google.com/abc-defg-hij"

    def test_conference_data(self):
        event = {
            "conferenceData": {
                "entryPoints": [
                    {"entryPointType": "video", "uri": "https://meet.google.com/xyz-abcd-efg"}
                ]
            }
        }
        assert extract_meet_url(event) == "https://meet.google.com/xyz-abcd-efg"

    def test_location_field(self):
        event = {"location": "Room 4B, https://meet.google.com/abc-defg-hij"}
        assert extract_meet_url(event) == "https://meet.google.com/abc-defg-hij"

    def test_description_field(self):
        event = {"description": "Join at https://meet.google.com/abc-defg-hij please"}
        assert extract_meet_url(event) == "https://meet.google.com/abc-defg-hij"

    def test_no_meet_url(self):
        event = {"summary": "Lunch", "location": "Cafeteria"}
        assert extract_meet_url(event) is None

    def test_empty_event(self):
        assert extract_meet_url({}) is None

    def test_non_meet_hangout_link_ignored(self):
        event = {"hangoutLink": "https://zoom.us/j/12345"}
        assert extract_meet_url(event) is None
