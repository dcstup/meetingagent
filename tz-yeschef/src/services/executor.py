import asyncio
import logging
import uuid

from composio import Composio
from composio_crewai import CrewAIProvider
from crewai import Agent, Task, Crew
from sqlalchemy import select

from src.config import settings
from src.config.constants import EXECUTOR_MODEL

logger = logging.getLogger(__name__)


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
        result = await db.execute(
            select(Utterance)
            .where(Utterance.session_id == uuid.UUID(session_id))
            .order_by(Utterance.created_at)
        )
        utterances = result.scalars().all()

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

        crew = Crew(agents=[agent], tasks=[task], verbose=False)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, crew.kickoff)

        return {
            "status": "success",
            "type": "gmail_draft",
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


async def execute_artifact(
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

        crew = Crew(agents=[agent], tasks=[task], verbose=False)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, crew.kickoff)

        artifact_html = str(result)
        # Strip markdown code fences if present
        if artifact_html.startswith("```"):
            lines = artifact_html.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            artifact_html = "\n".join(lines)

        return {
            "status": "success",
            "type": "html_artifact",
            "artifact_html": artifact_html,
            "title": title,
        }
    except Exception as e:
        logger.error(f"Artifact execution failed: {e}", exc_info=True)
        return {
            "status": "failed",
            "type": "html_artifact",
            "error": str(e),
        }


async def execute_generic_draft(
    title: str,
    body: str,
    session_id: str | None = None,
) -> dict:
    """Generate a polished draft using CrewAI, with RAG context from conversation."""
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
            role="Writing Assistant",
            goal="Create polished, professional drafts informed by meeting context",
            backstory="You are a skilled writer. You use meeting transcript context to create accurate, grounded professional documents.",
            tools=[],
            llm=EXECUTOR_MODEL,
            verbose=False,
        )

        task = Task(
            description=(
                f"Polish and expand this action item into a professional draft:\n"
                f"Title: {title}\n"
                f"Details: {body}"
                f"{context_block}\n\n"
                f"Use the meeting context to make the draft specific and grounded. "
                f"Do not fabricate details not present in the context."
            ),
            expected_output="A polished professional draft document.",
            agent=agent,
        )

        crew = Crew(agents=[agent], tasks=[task], verbose=False)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, crew.kickoff)

        return {
            "status": "success",
            "type": "generic_draft",
            "title": title,
            "result": str(result),
        }
    except Exception as e:
        logger.error(f"Generic draft execution failed: {e}", exc_info=True)
        return {
            "status": "failed",
            "type": "generic_draft",
            "error": str(e),
        }
