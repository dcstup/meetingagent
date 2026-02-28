from openai import AsyncOpenAI
from src.config import settings
from src.config.constants import EMBEDDING_MODEL, DEEPINFRA_BASE_URL

_client = None

def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.deepinfra_api_key,
            base_url=DEEPINFRA_BASE_URL,
        )
    return _client

async def get_embedding(text: str) -> list[float]:
    """Get embedding vector for text using DeepInfra."""
    client = get_client()
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
