import hashlib
from src.config.constants import COSINE_DEDUPE_THRESHOLD
from src.services.embeddings import get_embedding, cosine_similarity


def compute_dedupe_hash(session_id: str, dedupe_key: str) -> str:
    """Compute exact-match dedup hash."""
    return hashlib.sha256(f"{session_id}:{dedupe_key}".encode()).hexdigest()


async def is_duplicate(
    session_id: str,
    dedupe_key: str,
    text: str,
    existing_proposals: list[dict],
) -> bool:
    """Check if a proposal is a duplicate via exact hash or semantic similarity."""
    new_hash = compute_dedupe_hash(session_id, dedupe_key)

    # Exact match
    for prop in existing_proposals:
        if prop.get("dedupe_hash") == new_hash:
            return True

    # Semantic similarity check
    if not existing_proposals:
        return False

    try:
        new_embedding = await get_embedding(text)
        for prop in existing_proposals:
            if prop.get("embedding"):
                sim = cosine_similarity(new_embedding, prop["embedding"])
                if sim > COSINE_DEDUPE_THRESHOLD:
                    return True
    except Exception:
        pass  # If embeddings fail, rely on exact match only

    return False
