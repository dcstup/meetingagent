import re
from typing import Optional


def extract_meet_url(event: dict) -> Optional[str]:
    """Extract Google Meet URL from a calendar event dict.

    Checks in order: hangoutLink, conferenceData, location, description.
    """
    # 1. Direct hangoutLink
    hangout = event.get("hangoutLink")
    if hangout and "meet.google.com" in hangout:
        return hangout

    # 2. conferenceData
    conf = event.get("conferenceData", {})
    for entry in conf.get("entryPoints", []):
        uri = entry.get("uri", "")
        if "meet.google.com" in uri:
            return uri

    # 3. location field
    location = event.get("location", "")
    meet_match = re.search(r'https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}', location)
    if meet_match:
        return meet_match.group(0)

    # 4. description field
    desc = event.get("description", "")
    meet_match = re.search(r'https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}', desc)
    if meet_match:
        return meet_match.group(0)

    return None
