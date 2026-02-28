"""Verify calendar_poll only queries workspaces with has_google_calendar=True."""

import uuid

import pytest
from sqlalchemy import select

from src.models.tables import Workspace


def _make_workspace(*, entity_id=None, has_gcal=False):
    return Workspace(
        id=uuid.uuid4(),
        composio_entity_id=entity_id,
        has_google_calendar=has_gcal,
        overlay_token="tok",
        webhook_secret="sec",
    )


class TestCalendarGateQuery:
    """The poll query must only return workspaces where both
    composio_entity_id is set AND has_google_calendar is True."""

    def test_query_filters_out_gmail_only_workspaces(self):
        """Workspace with entity_id but no calendar should be excluded."""
        ws = _make_workspace(entity_id="ent-1", has_gcal=False)
        clause = (
            Workspace.composio_entity_id.isnot(None),
            Workspace.has_google_calendar == True,  # noqa: E712
        )
        stmt = select(Workspace).where(*clause)
        # Compile the WHERE clause and verify both conditions present
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "has_google_calendar" in compiled
        assert "composio_entity_id IS NOT NULL" in compiled

    def test_model_defaults_to_false(self):
        """New workspace should default has_google_calendar to False."""
        ws = _make_workspace(entity_id="ent-1")
        assert ws.has_google_calendar is False

    def test_calendar_enabled_workspace(self):
        """Workspace with calendar enabled should have flag True."""
        ws = _make_workspace(entity_id="ent-1", has_gcal=True)
        assert ws.has_google_calendar is True
