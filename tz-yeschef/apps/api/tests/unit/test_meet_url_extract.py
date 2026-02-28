import pytest

from src.services.calendar_watcher import extract_meet_url


def test_hangout_link():
    event = {"hangoutLink": "https://meet.google.com/abc-defg-hij"}
    assert extract_meet_url(event) == "https://meet.google.com/abc-defg-hij"


def test_conference_data():
    event = {
        "conferenceData": {
            "entryPoints": [
                {"entryPointType": "video", "uri": "https://meet.google.com/abc-defg-hij"}
            ]
        }
    }
    assert extract_meet_url(event) == "https://meet.google.com/abc-defg-hij"


def test_location():
    event = {"location": "Room 1, https://meet.google.com/abc-defg-hij"}
    assert extract_meet_url(event) == "https://meet.google.com/abc-defg-hij"


def test_description():
    event = {"description": "Join at https://meet.google.com/abc-defg-hij please"}
    assert extract_meet_url(event) == "https://meet.google.com/abc-defg-hij"


def test_no_meet_url():
    assert extract_meet_url({}) is None
    assert extract_meet_url({"location": "Room 5"}) is None


def test_priority_hangout_over_description():
    event = {
        "hangoutLink": "https://meet.google.com/aaa-bbbb-ccc",
        "description": "https://meet.google.com/xxx-yyyy-zzz",
    }
    assert extract_meet_url(event) == "https://meet.google.com/aaa-bbbb-ccc"
