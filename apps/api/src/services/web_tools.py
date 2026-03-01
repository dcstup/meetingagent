"""Web search and fetch tools for CrewAI agents."""

import requests
from crewai.tools import tool

from src.config.settings import settings


@tool("Web Search")
def brave_search(query: str) -> str:
    """Search the web for current information using Brave Search. Returns top results with titles, URLs, and descriptions."""
    if not settings.brave_api_key:
        return "Web search unavailable: no API key configured."
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": 5},
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": settings.brave_api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("web", {}).get("results", [])
        if not results:
            return f"No results found for: {query}"
        output = []
        for r in results:
            output.append(f"**{r.get('title', 'Untitled')}**\n{r.get('url', '')}\n{r.get('description', '')}\n")
        return "\n".join(output)
    except Exception as e:
        return f"Search error: {e}"


@tool("Web Fetch")
def web_fetch(url: str) -> str:
    """Fetch and extract text content from a web page URL. Returns the page text content."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.hostname and parsed.hostname in ("localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254"):
            return "Fetch error: internal URLs are not allowed"
        if parsed.scheme not in ("http", "https"):
            return "Fetch error: only http/https URLs are supported"
        resp = requests.get(
            url,
            headers={"User-Agent": "YesChef-Agent/1.0"},
            timeout=15,
        )
        resp.raise_for_status()
        # Simple HTML to text extraction
        import re
        text = re.sub(r'<script[^>]*>.*?</script>', '', resp.text, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        # Truncate to avoid token explosion
        return text[:8000] if len(text) > 8000 else text
    except Exception as e:
        return f"Fetch error: {e}"


def get_web_tools() -> list:
    """Return list of web research tools for CrewAI agents."""
    return [brave_search, web_fetch]
