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

For each action item, determine:
- action_type: "gmail_draft" if it involves sending an email, "html_artifact" if it involves building/prototyping/mocking up/designing/visualizing something (UI, diagram, flowchart, wireframe, dashboard, landing page, prototype, SVG, etc.), otherwise "generic_draft"
- title: short title (max 80 chars)
- body: the full action item description
- recipient: email recipient if gmail_draft, null otherwise
- confidence: 0.0-1.0 how confident this is a real action item
- readiness: 1-5 scale assessing whether the conversation topic has resolved. 5=fully resolved/moved on, 1=still actively debating. Only mark 4-5 if the group has clearly agreed or moved past the topic.
- dedupe_key: a short canonical key for deduplication (e.g. "email-bob-proposal")

Return a JSON array of action items. If none found, return [].
Only extract items with clear action verbs (send, create, schedule, follow up, draft, review, etc.)."""

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
    return _parse_items(content)
