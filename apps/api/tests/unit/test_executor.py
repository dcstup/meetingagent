"""Unit tests for the executor service."""
from unittest.mock import patch, MagicMock, AsyncMock
import pytest


@pytest.mark.asyncio
class TestExecuteGmailDraft:

    async def test_success_returns_result(self):
        mock_tools = [MagicMock()]
        mock_crew_result = MagicMock()
        mock_crew_result.__str__ = lambda _: "Draft created successfully"

        with patch("src.services.executor._get_gmail_tools", new_callable=AsyncMock, return_value=mock_tools), \
             patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value=""), \
             patch("src.services.executor.Agent") as MockAgent, \
             patch("src.services.executor.Task") as MockTask, \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.return_value = mock_crew_result

            from src.services.executor import execute_gmail_draft
            result = await execute_gmail_draft(
                entity_id="test-entity",
                recipient="sarah@example.com",
                subject="Q1 Report",
                body="Please review the Q1 report.",
            )

        assert result["status"] == "success"
        assert result["type"] == "gmail_draft"
        assert result["recipient"] == "sarah@example.com"

    async def test_no_tools_returns_failure(self):
        with patch("src.services.executor._get_gmail_tools", new_callable=AsyncMock, return_value=[]):
            from src.services.executor import execute_gmail_draft
            result = await execute_gmail_draft(
                entity_id="test-entity",
                recipient="bob@example.com",
                subject="Test",
                body="Test body",
            )

        assert result["status"] == "failed"
        assert "No Gmail tools" in result["error"]

    async def test_crew_exception_returns_failure(self):
        mock_tools = [MagicMock()]

        with patch("src.services.executor._get_gmail_tools", new_callable=AsyncMock, return_value=mock_tools), \
             patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value=""), \
             patch("src.services.executor.Agent"), \
             patch("src.services.executor.Task"), \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.side_effect = RuntimeError("API timeout")

            from src.services.executor import execute_gmail_draft
            result = await execute_gmail_draft(
                entity_id="test-entity",
                recipient="bob@example.com",
                subject="Test",
                body="Test body",
            )

        assert result["status"] == "failed"
        assert "API timeout" in result["error"]

    async def test_with_rag_context(self):
        mock_tools = [MagicMock()]
        mock_crew_result = MagicMock()
        mock_crew_result.__str__ = lambda _: "Draft with context"

        with patch("src.services.executor._get_gmail_tools", new_callable=AsyncMock, return_value=mock_tools), \
             patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value="Tommy: We need Q1 numbers by Friday") as mock_ctx, \
             patch("src.services.executor.Agent"), \
             patch("src.services.executor.Task") as MockTask, \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.return_value = mock_crew_result

            from src.services.executor import execute_gmail_draft
            result = await execute_gmail_draft(
                entity_id="test-entity",
                recipient="sarah@example.com",
                subject="Q1 Report",
                body="Send the report",
                session_id="some-session-id",
            )

        assert result["status"] == "success"
        mock_ctx.assert_called_once_with("some-session-id", "Q1 Report Send the report")
        # Verify context was included in task description
        task_desc = MockTask.call_args[1]["description"]
        assert "meeting context" in task_desc
        assert "Q1 numbers by Friday" in task_desc


@pytest.mark.asyncio
class TestExecuteGenericDraft:

    async def test_success_returns_result(self):
        mock_crew_result = MagicMock()
        mock_crew_result.__str__ = lambda _: "Polished draft content"

        with patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value=""), \
             patch("src.services.executor.Agent"), \
             patch("src.services.executor.Task"), \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.return_value = mock_crew_result

            from src.services.executor import execute_generic_draft
            result = await execute_generic_draft(
                title="Follow up meeting",
                body="Schedule a follow-up meeting for next Monday",
            )

        assert result["status"] == "success"
        assert result["type"] == "generic_draft"

    async def test_crew_exception_returns_failure(self):
        with patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value=""), \
             patch("src.services.executor.Agent"), \
             patch("src.services.executor.Task"), \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.side_effect = RuntimeError("Model unavailable")

            from src.services.executor import execute_generic_draft
            result = await execute_generic_draft(title="Test", body="Test body")

        assert result["status"] == "failed"
        assert "Model unavailable" in result["error"]


@pytest.mark.asyncio
class TestGetGmailTools:

    async def test_calls_composio_with_correct_params(self):
        mock_sdk = MagicMock()
        mock_sdk.tools.get.return_value = [MagicMock(), MagicMock()]

        with patch("src.services.executor.Composio", return_value=mock_sdk):
            from src.services.executor import _get_gmail_tools
            tools = await _get_gmail_tools("entity-123")

        mock_sdk.tools.get.assert_called_once_with(
            user_id="entity-123",
            toolkits=["gmail"],
        )
        assert len(tools) == 2
