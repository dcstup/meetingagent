import asyncio
import logging
import uuid

from composio import Composio
from composio_crewai import CrewAIProvider
from crewai import Agent, Task, Crew
from sqlalchemy import select

from src.config import settings
from src.config.constants import EXECUTOR_MODEL
from src.services.web_tools import get_web_tools

logger = logging.getLogger(__name__)


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM output, handling leading whitespace."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)
    return text


async def _get_gmail_tools(entity_id: str) -> list:
    """Get CrewAI-wrapped Gmail tools from Composio for a specific user."""
    def _fetch():
        sdk = Composio(
            provider=CrewAIProvider(),
            api_key=settings.composio_api_key,
        )
        return sdk.tools.get(user_id=entity_id, toolkits=["gmail"])
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch)


async def _get_calendar_tools(entity_id: str) -> list:
    """Get CrewAI-wrapped Google Calendar tools from Composio for a specific user."""
    def _fetch():
        sdk = Composio(
            provider=CrewAIProvider(),
            api_key=settings.composio_api_key,
        )
        return sdk.tools.get(user_id=entity_id, toolkits=["googlecalendar"])
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch)


async def _get_composio_tools(entity_id: str) -> list:
    """Get all CrewAI-wrapped Composio tools for a specific user."""
    def _fetch():
        sdk = Composio(
            provider=CrewAIProvider(),
            api_key=settings.composio_api_key,
        )
        return sdk.tools.get(user_id=entity_id, toolkits=["gmail", "googlecalendar", "linear"])
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch)


async def _get_conversation_context(session_id: str, query_text: str, top_k: int = 5) -> str:
    """RAG: retrieve relevant conversation chunks for execution context.

    Embeds the query, then finds the most semantically relevant utterances
    from the meeting transcript to provide grounded context.
    """
    from src.db.engine import async_session
    from src.models.tables import Utterance
    from src.services.embeddings import get_embedding, cosine_similarity

    try:
        query_embedding = await get_embedding(query_text)
    except Exception as e:
        logger.warning(f"RAG embedding failed, falling back to recent utterances: {e}")
        return await _get_recent_context(session_id)

    async with async_session() as db:
        # Limit to most recent 50 utterances to avoid excessive embedding API calls
        result = await db.execute(
            select(Utterance)
            .where(Utterance.session_id == uuid.UUID(session_id))
            .order_by(Utterance.created_at.desc())
            .limit(50)
        )
        utterances = list(reversed(result.scalars().all()))

    if not utterances:
        return ""

    # Score each utterance by semantic similarity to the action item
    scored = []
    for u in utterances:
        try:
            u_embedding = await get_embedding(u.text)
            sim = cosine_similarity(query_embedding, u_embedding)
            scored.append((sim, u))
        except Exception:
            continue

    if not scored:
        return await _get_recent_context(session_id)

    # Take top_k most relevant, then sort chronologically for coherent context
    scored.sort(key=lambda x: x[0], reverse=True)
    relevant = scored[:top_k]
    relevant.sort(key=lambda x: x[1].created_at)

    lines = []
    for sim, u in relevant:
        lines.append(f"{u.speaker}: {u.text}")

    return "\n".join(lines)


async def _get_recent_context(session_id: str, limit: int = 10) -> str:
    """Fallback: get most recent utterances as context."""
    from src.db.engine import async_session
    from src.models.tables import Utterance

    async with async_session() as db:
        result = await db.execute(
            select(Utterance)
            .where(Utterance.session_id == uuid.UUID(session_id))
            .order_by(Utterance.created_at.desc())
            .limit(limit)
        )
        utterances = list(reversed(result.scalars().all()))

    return "\n".join(f"{u.speaker}: {u.text}" for u in utterances)


async def execute_gmail_draft(
    entity_id: str,
    recipient: str,
    subject: str,
    body: str,
    session_id: str | None = None,
) -> dict:
    """Create a Gmail draft using CrewAI + Composio, with RAG context from conversation."""
    if not entity_id:
        return {"status": "failed", "type": "gmail_draft", "error": "Gmail not connected. Please connect your Google account first."}
    try:
        gmail_tools = await _get_gmail_tools(entity_id)
        if not gmail_tools:
            return {
                "status": "failed",
                "type": "gmail_draft",
                "error": "No Gmail tools available. Check Composio connection.",
            }

        # RAG: retrieve relevant conversation context
        context = ""
        if session_id:
            context = await _get_conversation_context(session_id, f"{subject} {body}")

        context_block = ""
        if context:
            context_block = (
                f"\n\nRelevant meeting context (use to inform tone and details):\n"
                f"---\n{context}\n---"
            )

        agent = Agent(
            role="Email Assistant",
            goal="Create Gmail drafts informed by meeting context",
            backstory="You are a professional email assistant. You use meeting transcript context to write accurate, well-informed email drafts.",
            tools=gmail_tools,
            llm=EXECUTOR_MODEL,
            verbose=False,
        )

        task = Task(
            description=(
                f"Create a Gmail draft with:\n"
                f"To: {recipient}\n"
                f"Subject: {subject}\n"
                f"Body: {body}"
                f"{context_block}\n\n"
                f"Use the meeting context to make the email specific and grounded. "
                f"Do not fabricate details not present in the context."
            ),
            expected_output="Confirmation that the Gmail draft was created successfully.",
            agent=agent,
        )

        crew = Crew(agents=[agent], tasks=[task], verbose=False, tracing=False)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, crew.kickoff)

        return {
            "status": "success",
            "type": "gmail_draft",
            "title": subject,
            "recipient": recipient,
            "subject": subject,
            "result": str(result),
        }
    except Exception as e:
        logger.error(f"Gmail draft execution failed: {e}", exc_info=True)
        return {
            "status": "failed",
            "type": "gmail_draft",
            "error": str(e),
        }


async def execute_design_prototype(
    title: str,
    body: str,
    session_id: str | None = None,
) -> dict:
    """Generate an HTML artifact (page, Mermaid diagram, or SVG) using CrewAI."""
    try:
        context = ""
        if session_id:
            context = await _get_conversation_context(session_id, f"{title} {body}")

        context_block = ""
        if context:
            context_block = (
                f"\n\nRelevant meeting context:\n"
                f"---\n{context}\n---"
            )

        agent = Agent(
            role="Visual Artifact Generator",
            goal="Create self-contained HTML artifacts: pages, Mermaid diagrams, or SVG graphics",
            backstory=(
                "You are an expert frontend developer and data visualization specialist. "
                "You create beautiful, self-contained HTML documents. You decide the best format: "
                "a full HTML page with inline CSS/JS, a Mermaid diagram, or an SVG graphic."
            ),
            tools=[],
            llm=EXECUTOR_MODEL,
            verbose=False,
        )

        task = Task(
            description=(
                f"Create a visual artifact for this request:\n"
                f"Title: {title}\n"
                f"Details: {body}"
                f"{context_block}\n\n"
                f"Choose the best format:\n"
                f"1. Full HTML page — for UI mockups, dashboards, landing pages. Use inline CSS and JS.\n"
                f"2. Mermaid diagram — for flowcharts, sequence diagrams, architecture diagrams. "
                f'Wrap in HTML with <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script> '
                f'and a <pre class="mermaid"> block.\n'
                f"3. SVG — for logos, icons, simple graphics. Wrap in HTML with inline <svg>.\n\n"
                f"Output ONLY a complete, valid HTML document. No explanation, just the HTML."
            ),
            expected_output="A complete, valid HTML document.",
            agent=agent,
        )

        crew = Crew(agents=[agent], tasks=[task], verbose=False, tracing=False)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, crew.kickoff)

        artifact_html = _strip_code_fences(str(result))

        return {
            "status": "success",
            "type": "design_prototype",
            "artifact_html": artifact_html,
            "title": title,
        }
    except Exception as e:
        logger.error(f"Artifact execution failed: {e}", exc_info=True)
        return {
            "status": "failed",
            "type": "design_prototype",
            "error": str(e),
        }


async def execute_general_agent(
    entity_id: str | None,
    title: str,
    body: str,
    recipient: str | None = None,
    session_id: str | None = None,
) -> dict:
    """Run a general-purpose agent with Composio + web tools, with RAG context from conversation."""
    try:
        # Build tool set: Composio session tools (if entity_id) + web tools
        if entity_id:
            composio_tools = await _get_composio_tools(entity_id)
            all_tools = composio_tools + get_web_tools()
        else:
            all_tools = get_web_tools()

        # RAG: retrieve relevant conversation context
        context = ""
        if session_id:
            context = await _get_conversation_context(session_id, f"{title} {body}")

        context_block = ""
        if context:
            context_block = (
                f"\n\nRelevant meeting context:\n"
                f"---\n{context}\n---"
            )

        agent = Agent(
            role="General Assistant",
            goal=(
                "Complete the requested task using all available tools. "
                "Always include links to any resources you create (e.g. Linear ticket URLs, Gmail draft links). "
                "Provide a clear summary of actions taken. "
                "If the task requires building something visual, create a self-contained HTML document."
            ),
            backstory=(
                "You are a capable general-purpose assistant. You use the best available tools "
                "to complete tasks accurately. When building visual outputs, you produce clean, "
                "self-contained HTML documents."
            ),
            tools=all_tools,
            llm=EXECUTOR_MODEL,
            verbose=False,
        )

        task = Task(
            description=(
                f"Complete this task:\n"
                f"Title: {title}\n"
                f"Details: {body}"
                f"{context_block}\n\n"
                f"Use all available tools as needed. "
                f"Always include links to any resources you create (e.g. Linear ticket URLs, Gmail draft links). "
                f"Provide a clear summary of what was done. "
                f"If the result is a visual or structured document, output it as a complete HTML document."
            ),
            expected_output="A clear summary of actions taken, including links to any created resources.",
            agent=agent,
        )

        crew = Crew(agents=[agent], tasks=[task], verbose=False, tracing=False)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, crew.kickoff)

        result_str = str(result)

        # Detect HTML output and return as artifact
        # Strip fences before HTML detection (LLM may wrap HTML in ```)
        result_str = _strip_code_fences(result_str)
        is_html = "<html" in result_str.lower() or "<!doctype" in result_str.lower()
        if is_html:
            return {
                "status": "success",
                "type": "general_agent",
                "artifact_html": result_str,
                "title": title,
            }

        return {
            "status": "success",
            "type": "general_agent",
            "title": title,
            "result": result_str,
        }
    except Exception as e:
        logger.error(f"General agent execution failed: {e}", exc_info=True)
        return {
            "status": "failed",
            "type": "general_agent",
            "error": str(e),
        }


async def execute_research_query(
    title: str,
    body: str,
    session_id: str | None = None,
) -> dict:
    """Research a topic using web tools and produce an HTML report using CrewAI."""
    try:
        # RAG: retrieve relevant conversation context
        context = ""
        if session_id:
            context = await _get_conversation_context(session_id, f"{title} {body}")

        context_block = ""
        if context:
            context_block = (
                f"\n\nRelevant meeting context:\n"
                f"---\n{context}\n---"
            )

        agent = Agent(
            role="Research Analyst",
            goal="Research the given question thoroughly using web search and produce a comprehensive research report as a self-contained HTML document with clean formatting, sections, and citations.",
            backstory=(
                "You are an expert researcher. Search the web, synthesize findings from multiple sources, "
                "and produce a clear, well-structured HTML report. Always cite your sources with links."
            ),
            tools=get_web_tools(),
            llm=EXECUTOR_MODEL,
            verbose=False,
        )

        task = Task(
            description=(
                f"Research this topic and produce a comprehensive HTML report:\n"
                f"Title: {title}\n"
                f"Details: {body}"
                f"{context_block}\n\n"
                f"Search the web for relevant information from multiple sources. "
                f"Synthesize your findings into a well-structured HTML document with:\n"
                f"- A clear title and introduction\n"
                f"- Organized sections with headings\n"
                f"- Key findings and analysis\n"
                f"- Citations and source links\n"
                f"- Clean inline CSS styling\n\n"
                f"Output ONLY a complete, valid HTML document. No explanation, just the HTML."
            ),
            expected_output="A complete, valid HTML research report document.",
            agent=agent,
        )

        crew = Crew(agents=[agent], tasks=[task], verbose=False, tracing=False)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, crew.kickoff)

        artifact_html = _strip_code_fences(str(result))

        return {
            "status": "success",
            "type": "research_query",
            "artifact_html": artifact_html,
            "title": title,
        }
    except Exception as e:
        logger.error(f"Research query execution failed: {e}", exc_info=True)
        return {
            "status": "failed",
            "type": "research_query",
            "error": str(e),
        }


async def execute_calendar_action(
    entity_id: str | None,
    title: str,
    body: str,
    session_id: str | None = None,
) -> dict:
    """Manage Google Calendar events using CrewAI + Composio, with RAG context from conversation."""
    try:
        if not entity_id:
            return {"status": "failed", "type": "calendar_action", "error": "Calendar not connected. Please connect your Google account first."}

        calendar_tools = await _get_calendar_tools(entity_id)
        if not calendar_tools:
            return {
                "status": "failed",
                "type": "calendar_action",
                "error": "No Calendar tools available. Check Composio connection.",
            }

        # RAG: retrieve relevant conversation context
        context = ""
        if session_id:
            context = await _get_conversation_context(session_id, f"{title} {body}")

        context_block = ""
        if context:
            context_block = (
                f"\n\nRelevant meeting context:\n"
                f"---\n{context}\n---"
            )

        agent = Agent(
            role="Calendar Manager",
            goal="Manage the user's Google Calendar: create, update, or cancel events as requested.",
            backstory=(
                "You are a calendar management specialist. You create well-structured calendar events "
                "with proper titles, times, descriptions, and attendees based on meeting context."
            ),
            tools=calendar_tools,
            llm=EXECUTOR_MODEL,
            verbose=False,
        )

        task = Task(
            description=(
                f"Perform this calendar action:\n"
                f"Title: {title}\n"
                f"Details: {body}"
                f"{context_block}\n\n"
                f"Use the meeting context to set accurate event details. "
                f"Do not fabricate details not present in the context."
            ),
            expected_output="Confirmation that the calendar action was completed successfully.",
            agent=agent,
        )

        crew = Crew(agents=[agent], tasks=[task], verbose=False, tracing=False)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, crew.kickoff)

        return {
            "status": "success",
            "type": "calendar_action",
            "title": title,
            "result": str(result),
        }
    except Exception as e:
        logger.error(f"Calendar action execution failed: {e}", exc_info=True)
        return {
            "status": "failed",
            "type": "calendar_action",
            "error": str(e),
        }
