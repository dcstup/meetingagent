"""Tests for the Google Calendar OAuth endpoint."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from fastapi import HTTPException

from src.api.routes_workspace import oauth_google_calendar


def _make_mock_db(workspace):
    """Create a mock async DB session that returns the given workspace."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = workspace
    mock_session.execute.return_value = mock_result
    return mock_session


@pytest.mark.asyncio
async def test_gcal_oauth_returns_url():
    """oauth_google_calendar returns an OAuth URL when Gmail is connected."""
    ws = MagicMock()
    ws.id = "test-workspace-id"
    ws.composio_entity_id = "test-entity"

    fake_url = "https://accounts.google.com/o/oauth2/auth?scope=calendar"
    db = _make_mock_db(ws)

    with patch("src.services.composio_client.initiate_gcal_oauth", return_value=fake_url):
        result = await oauth_google_calendar(db=db)

    assert result == {"url": fake_url}


@pytest.mark.asyncio
async def test_gcal_oauth_requires_gmail_first():
    """Should raise 400 if Gmail is not connected yet."""
    ws = MagicMock()
    ws.id = "test-workspace-id"
    ws.composio_entity_id = None

    db = _make_mock_db(ws)

    with pytest.raises(HTTPException) as exc_info:
        await oauth_google_calendar(db=db)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_gcal_oauth_no_workspace():
    """Should raise 404 if no workspace exists."""
    db = _make_mock_db(None)

    with pytest.raises(HTTPException) as exc_info:
        await oauth_google_calendar(db=db)
    assert exc_info.value.status_code == 404
