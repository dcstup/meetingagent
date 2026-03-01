import asyncio
import json
import logging
import re

from cerebras.cloud.sdk import Cerebras
from src.config import settings
from src.config.constants import EXTRACTION_MODEL

logger = logging.getLogger(__name__)

_client = None

def get_client() -> Cerebras:
    global _client
    if _client is None:
        _client = Cerebras(api_key=settings.cerebras_api_key)
    return _client


def _parse_items(content: str) -> list[dict]:
    """Parse action items from LLM response, handling both JSON and markdown-wrapped JSON."""
    # Try direct parse first
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Fallback: extract JSON from markdown code blocks or raw text
        match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
        if match:
            try:
                parsed = json.loads(match.group(1))
            except json.JSONDecodeError:
                return []
        else:
            # Try to find a JSON array or object in the text
            match = re.search(r'(\[[\s\S]*\]|\{[\s\S]*\})', content)
            if match:
                try:
                    parsed = json.loads(match.group(1))
                except json.JSONDecodeError:
                    return []
            else:
                return []

    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        items = []
        for v in parsed.values():
            if isinstance(v, list):
                items = v
                break
    else:
        items = []
    return [i for i in items if isinstance(i, dict)]


async def extract_action_items(transcript_text: str) -> list[dict]:
    """Use Cerebras to extract action items from transcript text.

    Returns list of dicts with: action_type, title, body, recipient, confidence, dedupe_key
    """
    client = get_client()

    system_prompt = """You are an action-item extractor for meeting transcripts.
Extract actionable items that someone needs to do after the meeting.
Bias toward design_prototype — if a task could reasonably involve creating a visual artifact, prototype, or any built thing, classify it as design_prototype.

For each action item, determine:
- action_type: one of:
  "design_prototype" if it involves building, creating, designing, prototyping, mocking up, or visualizing ANYTHING — websites, homepages, landing pages, apps, dashboards, presentations, diagrams, charts, reports with visuals, UI layouts, wireframes, or any creative/visual deliverable. When in doubt about whether something should be built or just described, prefer design_prototype. Examples: "build the homepage", "create a mockup", "make a landing page", "design the dashboard", "put together a presentation", "visualize the data", "confirmed on the homepage" (implies it needs to be built), "Shanghai Cheap Food homepage" (a named deliverable that needs to be built). Trigger words: homepage, landing page, website, app, dashboard, mockup, prototype, design, UI, wireframe, layout, page, screen, visualization, diagram, chart, presentation, deck, report with visuals, interface, component, template, brand kit, style guide, logo, banner, graphic.
  "calendar_action" if it ONLY involves scheduling, creating, modifying, or canceling calendar events or meetings (e.g. "schedule a meeting", "block off time", "move the standup to 3pm"),
  "gmail_draft" if it ONLY involves sending or drafting an email to a specific person,
  "linear_ticket" if it involves creating, updating, or triaging tickets, issues, bugs, or task tracking in a project management tool (e.g. "create a ticket for the auth bug", "file an issue for the login crash", "add a task to track the refactor"),
  "research_query" if someone asks an open question needing research, fact-checking, or external data lookup (e.g. "what's the market size for X?", "look into competitors", "find out about Y"),
  "general_agent" for any other actionable task that doesn't fit the above categories
- title: short title (max 80 chars)
- body: the full action item description
- recipient: email recipient if gmail_draft, null otherwise
- confidence: 0.0-1.0 how confident this is a real action item
- dedupe_key: a short canonical key for deduplication (e.g. "email-bob-proposal")

Return a JSON array of action items. If none found, return [].
Only extract items with clear action verbs (send, create, schedule, follow up, draft, review, research, investigate, find, check, explore, analyze, book, block, cancel, reschedule, move, post, run, execute, trigger, update, build, design, prototype, mock up, visualize, etc.)."""

    def _call_cerebras():
        try:
            return client.chat.completions.create(
                model=EXTRACTION_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Transcript:\n{transcript_text}"},
                ],
                response_format={"type": "json_object"},
                max_tokens=2048,
                temperature=0.1,
            )
        except Exception as e:
            # Fallback: response_format may not be supported
            logger.warning(f"Cerebras response_format failed, retrying without: {e}")
            return client.chat.completions.create(
                model=EXTRACTION_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt + "\n\nIMPORTANT: Return ONLY valid JSON, no other text."},
                    {"role": "user", "content": f"Transcript:\n{transcript_text}"},
                ],
                max_tokens=2048,
                temperature=0.1,
            )

    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(None, _call_cerebras)

    content = response.choices[0].message.content
    if not content:
        logger.warning("Cerebras returned empty/null content for extraction")
        return []
    logger.info(f"Cerebras raw response ({len(content)} chars): {content[:500]}")
    items = _parse_items(content)
    if not items and content:
        logger.warning(f"Cerebras returned content but parsing yielded 0 items. Full content: {content[:1000]}")
    return items
