import asyncio
import json
import logging
import re

from src.config.constants import GATE_MODEL, GATE_AVG_THRESHOLD, GATE_READINESS_THRESHOLD
from src.services.cerebras import get_client

logger = logging.getLogger(__name__)

GATE_SYSTEM_PROMPT = """You are the Action Item Judge for a live meeting assistant. Your sole responsibility is to evaluate a candidate action item against the provided transcript data using a strict 1-5 rubric.

You will receive two types of transcript data:
1. rag_context_chunks: Historical snippets from earlier in the meeting, provided ONLY to resolve ambiguities (e.g., who "he" is, or what "the project" refers to).
2. transcript_window: The recent conversation window. This includes the moment the action was allegedly triggered, plus the immediate trailing conversation to evaluate if the topic has resolved.

CRITICAL RULE: The explicit commitment or request MUST occur within the `transcript_window`. Do not approve actions where the commitment only exists in the `rag_context_chunks`. RAG chunks are strictly for filling in missing details to improve Specificity and Feasibility.

SCORING RUBRIC (1 = Lowest/Worst, 5 = Highest/Best):
1. Explicitness: 1 = Vague suggestion or passing thought. 5 = Clear, explicit verbal commitment or direct request with a designated owner in the live window.
2. Value: 1 = Trivial, administrative, or low-impact task. 5 = High-impact, critical-path action that directly drives the project forward.
3. Specificity: 1 = Too abstract to understand without guessing key facts. 5 = Highly concrete; the "who, what, and how" are perfectly clear (using RAG context if needed).
4. Urgency: 1 = A "someday" or backlog item. 5 = Must be completed immediately or shortly after this meeting.
5. Feasibility: 1 = Impossible to draft a valid artifact (ticket, email) with the current context. 5 = All required fields (recipient, topic, core ask) are present (using RAG context if needed) to generate a perfect draft right now.
6. Evidence Strength: 1 = Based on vibes, assumptions, or implicit context. 5 = Directly supported by a verbatim, unambiguous quote in the `transcript_window`.
7. Readiness: 1 = Active debate ongoing. The participants are still actively discussing, modifying, or debating the specifics of this action. 3 = A commitment was made, but the conversation is lingering on closely related details or minor clarifications. 5 = Fully resolved. The conversation has definitively moved on to a completely different topic, and the original commitment stands unchallenged.

EXTRACTION RULES:
- verbatim_evidence_quote: You must extract the exact, continuous string of text from the `transcript_window` that proves this action was committed to. Do not pull this from RAG chunks. If none exists, output null.
- missing_critical_info: List 1-2 bullet points of what is required to execute this action but remains missing even after reviewing both the window and RAG chunks. If nothing is missing, output an empty array [].

OUTPUT FORMAT:
You must respond ONLY with a valid JSON object with keys: scores (object with explicitness, value, specificity, urgency, feasibility, evidence_strength, readiness), verbatim_evidence_quote (string or null), missing_critical_info (array of strings)."""

SCORE_DIMENSIONS = [
    "explicitness", "value", "specificity", "urgency",
    "feasibility", "evidence_strength", "readiness",
]


def _parse_gate_response(content: str) -> dict | None:
    """Parse gate JSON response, handling markdown-wrapped JSON."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r'(\{[\s\S]*\})', content)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    return None


def _fail_open(reason: str) -> dict:
    """Return a passing result when the gate cannot evaluate."""
    logger.warning(f"Gate fail-open: {reason}")
    return {
        "scores": {},
        "avg_score": 0.0,
        "passed": True,
        "verbatim_evidence_quote": None,
        "missing_critical_info": [],
        "error": reason,
    }


async def evaluate_action(
    candidate: dict,
    transcript_window: str,
    rag_context_chunks: list[dict],
    meeting_context: dict,
) -> dict:
    """Evaluate a candidate action item against the 7-dimension rubric.

    Returns dict with scores, avg_score, passed, verbatim_evidence_quote,
    missing_critical_info. Fails open on any error.
    """
    user_payload = json.dumps({
        "meeting_context": meeting_context,
        "rag_context_chunks": rag_context_chunks,
        "transcript_window": transcript_window,
        "candidate_action": candidate,
    })

    try:
        client = get_client()

        def _call():
            try:
                return client.chat.completions.create(
                    model=GATE_MODEL,
                    messages=[
                        {"role": "system", "content": GATE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_payload},
                    ],
                    response_format={"type": "json_object"},
                    max_tokens=1024,
                    temperature=0.1,
                )
            except Exception as e:
                logger.warning(f"Gate response_format failed, retrying without: {e}")
                return client.chat.completions.create(
                    model=GATE_MODEL,
                    messages=[
                        {"role": "system", "content": GATE_SYSTEM_PROMPT + "\n\nIMPORTANT: Return ONLY valid JSON, no other text."},
                        {"role": "user", "content": user_payload},
                    ],
                    max_tokens=1024,
                    temperature=0.1,
                )

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _call)
        content = response.choices[0].message.content
    except Exception as e:
        return _fail_open(f"API call failed: {e}")

    if not content:
        return _fail_open("Gate model returned empty/null content")

    parsed = _parse_gate_response(content)
    if parsed is None or "scores" not in parsed:
        return _fail_open(f"Unparseable gate response: {content[:200]}")

    scores = parsed["scores"]

    # Validate all dimensions present
    score_values = []
    for dim in SCORE_DIMENSIONS:
        val = scores.get(dim)
        if val is None:
            return _fail_open(f"Missing score dimension: {dim}")
        score_values.append(float(val))

    avg_score = sum(score_values) / len(score_values)
    passed = avg_score > GATE_AVG_THRESHOLD and scores["readiness"] >= GATE_READINESS_THRESHOLD

    return {
        "scores": scores,
        "avg_score": avg_score,
        "passed": passed,
        "verbatim_evidence_quote": parsed.get("verbatim_evidence_quote"),
        "missing_critical_info": parsed.get("missing_critical_info", []),
    }
