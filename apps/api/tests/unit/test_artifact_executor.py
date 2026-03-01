"""Unit tests for the artifact executor (execute_design_prototype)."""
from unittest.mock import patch, MagicMock, AsyncMock
import pytest


@pytest.mark.asyncio
class TestExecuteDesignPrototype:

    async def test_success_returns_html(self):
        mock_crew_result = MagicMock()
        mock_crew_result.__str__ = lambda _: "<html><body><h1>Login Page</h1></body></html>"

        with patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value=""), \
             patch("src.services.executor.Agent"), \
             patch("src.services.executor.Task"), \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.return_value = mock_crew_result

            from src.services.executor import execute_design_prototype
            result = await execute_design_prototype(
                title="Login page mockup",
                body="Create a login page with email and password fields",
            )

        assert result["status"] == "success"
        assert result["type"] == "design_prototype"
        assert "<html>" in result["artifact_html"]
        assert result["title"] == "Login page mockup"

    async def test_strips_markdown_fences(self):
        mock_crew_result = MagicMock()
        mock_crew_result.__str__ = lambda _: "```html\n<html><body>Hello</body></html>\n```"

        with patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value=""), \
             patch("src.services.executor.Agent"), \
             patch("src.services.executor.Task"), \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.return_value = mock_crew_result

            from src.services.executor import execute_design_prototype
            result = await execute_design_prototype(title="Test", body="Test")

        assert result["status"] == "success"
        assert result["artifact_html"].startswith("<html>")
        assert "```" not in result["artifact_html"]

    async def test_crew_exception_returns_failure(self):
        with patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value=""), \
             patch("src.services.executor.Agent"), \
             patch("src.services.executor.Task"), \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.side_effect = RuntimeError("Model error")

            from src.services.executor import execute_design_prototype
            result = await execute_design_prototype(title="Test", body="Test")

        assert result["status"] == "failed"
        assert "Model error" in result["error"]

    async def test_with_rag_context(self):
        mock_crew_result = MagicMock()
        mock_crew_result.__str__ = lambda _: "<html><body>Dashboard</body></html>"

        with patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value="Alice: Let's add a bar chart for Q1 sales") as mock_ctx, \
             patch("src.services.executor.Agent"), \
             patch("src.services.executor.Task") as MockTask, \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.return_value = mock_crew_result

            from src.services.executor import execute_design_prototype
            result = await execute_design_prototype(
                title="Sales dashboard",
                body="Create a sales dashboard",
                session_id="session-123",
            )

        assert result["status"] == "success"
        mock_ctx.assert_called_once_with("session-123", "Sales dashboard Create a sales dashboard")
        task_desc = MockTask.call_args[1]["description"]
        assert "Q1 sales" in task_desc
