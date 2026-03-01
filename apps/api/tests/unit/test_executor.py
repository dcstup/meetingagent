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
             patch("src.services.executor.get_web_tools", return_value=[]), \
             patch("src.services.executor.Agent"), \
             patch("src.services.executor.Task"), \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.return_value = mock_crew_result

            from src.services.executor import execute_general_agent
            result = await execute_general_agent(
                entity_id=None,
                title="Follow up meeting",
                body="Schedule a follow-up meeting for next Monday",
            )

        assert result["status"] == "success"
        assert result["type"] == "general_agent"

    async def test_crew_exception_returns_failure(self):
        with patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value=""), \
             patch("src.services.executor.get_web_tools", return_value=[]), \
             patch("src.services.executor.Agent"), \
             patch("src.services.executor.Task"), \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.side_effect = RuntimeError("Model unavailable")

            from src.services.executor import execute_general_agent
            result = await execute_general_agent(entity_id=None, title="Test", body="Test body")

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


@pytest.mark.asyncio
class TestExecuteResearchQuery:

    async def test_execute_research_query_success(self):
        mock_web_tool = MagicMock()
        mock_crew_result = MagicMock()
        mock_crew_result.__str__ = lambda _: "<html><body><h1>Research Report</h1></body></html>"

        with patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value=""), \
             patch("src.services.executor.get_web_tools", return_value=[mock_web_tool]), \
             patch("src.services.executor.Agent") as MockAgent, \
             patch("src.services.executor.Task") as MockTask, \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.return_value = mock_crew_result

            from src.services.executor import execute_research_query
            result = await execute_research_query(
                title="AI trends 2025",
                body="What are the biggest AI trends in 2025?",
            )

        assert result["status"] == "success"
        assert result["type"] == "research_query"
        assert "artifact_html" in result
        assert "<html>" in result["artifact_html"]
        assert result["title"] == "AI trends 2025"
        # Verify web tools were passed to the agent
        MockAgent.assert_called_once()
        agent_kwargs = MockAgent.call_args[1]
        assert mock_web_tool in agent_kwargs["tools"]


@pytest.mark.asyncio
class TestExecuteCalendarAction:

    async def test_execute_calendar_action_success(self):
        mock_calendar_tool = MagicMock()
        mock_crew_result = MagicMock()
        mock_crew_result.__str__ = lambda _: "Calendar event created successfully"

        with patch("src.services.executor._get_calendar_tools", new_callable=AsyncMock, return_value=[mock_calendar_tool]), \
             patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value=""), \
             patch("src.services.executor.Agent"), \
             patch("src.services.executor.Task"), \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.return_value = mock_crew_result

            from src.services.executor import execute_calendar_action
            result = await execute_calendar_action(
                entity_id="entity-456",
                title="Q2 planning sync",
                body="Schedule a 1-hour Q2 planning meeting next Monday at 10am",
            )

        assert result["status"] == "success"
        assert result["type"] == "calendar_action"
        assert "result" in result

    async def test_execute_calendar_action_no_entity(self):
        from src.services.executor import execute_calendar_action
        result = await execute_calendar_action(
            entity_id=None,
            title="Team sync",
            body="Schedule a team sync",
        )

        assert result["status"] == "failed"
        assert "Calendar not connected" in result["error"]

    async def test_execute_calendar_action_no_tools_returns_failure(self):
        with patch("src.services.executor._get_calendar_tools", new_callable=AsyncMock, return_value=[]):
            from src.services.executor import execute_calendar_action
            result = await execute_calendar_action(
                entity_id="entity-789",
                title="Meeting",
                body="Create a meeting",
            )

        assert result["status"] == "failed"
        assert "No Calendar tools" in result["error"]


@pytest.mark.asyncio
class TestExecuteGeneralAgent:

    async def test_execute_general_agent_with_entity(self):
        mock_composio_tool = MagicMock()
        mock_web_tool = MagicMock()
        mock_crew_result = MagicMock()
        mock_crew_result.__str__ = lambda _: "Task completed successfully"

        with patch("src.services.executor._get_composio_tools", new_callable=AsyncMock, return_value=[mock_composio_tool]), \
             patch("src.services.executor.get_web_tools", return_value=[mock_web_tool]), \
             patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value=""), \
             patch("src.services.executor.Agent") as MockAgent, \
             patch("src.services.executor.Task"), \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.return_value = mock_crew_result

            from src.services.executor import execute_general_agent
            result = await execute_general_agent(
                entity_id="entity-111",
                title="Send follow-up",
                body="Send a follow-up email and schedule a meeting",
            )

        assert result["status"] == "success"
        assert result["type"] == "general_agent"
        # Verify both composio and web tools were combined and passed to agent
        MockAgent.assert_called_once()
        agent_kwargs = MockAgent.call_args[1]
        assert mock_composio_tool in agent_kwargs["tools"]
        assert mock_web_tool in agent_kwargs["tools"]

    async def test_execute_general_agent_without_entity(self):
        mock_web_tool = MagicMock()
        mock_crew_result = MagicMock()
        mock_crew_result.__str__ = lambda _: "Research complete"

        with patch("src.services.executor.get_web_tools", return_value=[mock_web_tool]), \
             patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value=""), \
             patch("src.services.executor.Agent") as MockAgent, \
             patch("src.services.executor.Task"), \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.return_value = mock_crew_result

            from src.services.executor import execute_general_agent
            result = await execute_general_agent(
                entity_id=None,
                title="Research competitors",
                body="Look up our top 3 competitors",
            )

        assert result["status"] == "success"
        # Verify only web tools were used (no composio tools)
        MockAgent.assert_called_once()
        agent_kwargs = MockAgent.call_args[1]
        assert agent_kwargs["tools"] == [mock_web_tool]

    async def test_execute_general_agent_html_detection(self):
        mock_crew_result = MagicMock()
        mock_crew_result.__str__ = lambda _: "<html><body><h1>Dashboard</h1></body></html>"

        with patch("src.services.executor.get_web_tools", return_value=[]), \
             patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value=""), \
             patch("src.services.executor.Agent"), \
             patch("src.services.executor.Task"), \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.return_value = mock_crew_result

            from src.services.executor import execute_general_agent
            result = await execute_general_agent(
                entity_id=None,
                title="Build dashboard",
                body="Create a simple HTML dashboard",
            )

        assert result["status"] == "success"
        assert result["type"] == "general_agent"
        assert "artifact_html" in result
        assert "<html>" in result["artifact_html"]
        assert result["title"] == "Build dashboard"

    async def test_execute_general_agent_plain_text(self):
        mock_crew_result = MagicMock()
        mock_crew_result.__str__ = lambda _: "The answer is 42. No HTML here."

        with patch("src.services.executor.get_web_tools", return_value=[]), \
             patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value=""), \
             patch("src.services.executor.Agent"), \
             patch("src.services.executor.Task"), \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.return_value = mock_crew_result

            from src.services.executor import execute_general_agent
            result = await execute_general_agent(
                entity_id=None,
                title="Simple question",
                body="What is the answer?",
            )

        assert result["status"] == "success"
        assert result["type"] == "general_agent"
        assert "artifact_html" not in result
        assert result["result"] == "The answer is 42. No HTML here."


@pytest.mark.asyncio
class TestExecuteLinearTicket:

    async def test_success_returns_result(self):
        mock_tools = [MagicMock()]
        mock_crew_result = MagicMock()
        mock_crew_result.__str__ = lambda _: "Created ticket https://linear.app/team/ISS-123"

        with patch("src.services.executor._get_linear_tools", new_callable=AsyncMock, return_value=mock_tools), \
             patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value=""), \
             patch("src.services.executor.Agent") as MockAgent, \
             patch("src.services.executor.Task") as MockTask, \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.return_value = mock_crew_result

            from src.services.executor import execute_linear_ticket
            result = await execute_linear_ticket(
                entity_id="test-entity",
                title="Fix auth timeout bug",
                body="Users experiencing session timeouts after 30 minutes.",
            )

        assert result["status"] == "success"
        assert result["type"] == "linear_ticket"
        assert result["title"] == "Fix auth timeout bug"
        assert "linear.app" in result["result"]

    async def test_no_entity_returns_failure(self):
        from src.services.executor import execute_linear_ticket
        result = await execute_linear_ticket(
            entity_id=None,
            title="Test ticket",
            body="Test body",
        )

        assert result["status"] == "failed"
        assert result["type"] == "linear_ticket"
        assert "not connected" in result["error"].lower()

    async def test_no_tools_returns_failure(self):
        with patch("src.services.executor._get_linear_tools", new_callable=AsyncMock, return_value=[]):
            from src.services.executor import execute_linear_ticket
            result = await execute_linear_ticket(
                entity_id="test-entity",
                title="Test ticket",
                body="Test body",
            )

        assert result["status"] == "failed"
        assert "No Linear tools" in result["error"]

    async def test_crew_exception_returns_failure(self):
        mock_tools = [MagicMock()]

        with patch("src.services.executor._get_linear_tools", new_callable=AsyncMock, return_value=mock_tools), \
             patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value=""), \
             patch("src.services.executor.Agent"), \
             patch("src.services.executor.Task"), \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.side_effect = RuntimeError("Linear API error")

            from src.services.executor import execute_linear_ticket
            result = await execute_linear_ticket(
                entity_id="test-entity",
                title="Test ticket",
                body="Test body",
            )

        assert result["status"] == "failed"
        assert "Linear API error" in result["error"]

    async def test_with_rag_context(self):
        mock_tools = [MagicMock()]
        mock_crew_result = MagicMock()
        mock_crew_result.__str__ = lambda _: "Ticket created with context"

        with patch("src.services.executor._get_linear_tools", new_callable=AsyncMock, return_value=mock_tools), \
             patch("src.services.executor._get_conversation_context", new_callable=AsyncMock, return_value="Tommy: The auth bug causes timeouts") as mock_ctx, \
             patch("src.services.executor.Agent"), \
             patch("src.services.executor.Task") as MockTask, \
             patch("src.services.executor.Crew") as MockCrew:
            MockCrew.return_value.kickoff.return_value = mock_crew_result

            from src.services.executor import execute_linear_ticket
            result = await execute_linear_ticket(
                entity_id="test-entity",
                title="Fix auth bug",
                body="Auth timeout issue",
                session_id="session-xyz",
            )

        assert result["status"] == "success"
        mock_ctx.assert_called_once_with("session-xyz", "Fix auth bug Auth timeout issue")
        task_desc = MockTask.call_args[1]["description"]
        assert "meeting context" in task_desc
        assert "auth bug causes timeouts" in task_desc


@pytest.mark.asyncio
class TestGetLinearTools:

    async def test_calls_composio_with_correct_params(self):
        mock_sdk = MagicMock()
        mock_sdk.tools.get.return_value = [MagicMock()]

        with patch("src.services.executor.Composio", return_value=mock_sdk):
            from src.services.executor import _get_linear_tools
            tools = await _get_linear_tools("entity-abc")

        mock_sdk.tools.get.assert_called_once_with(
            user_id="entity-abc",
            toolkits=["linear"],
        )
        assert len(tools) == 1
