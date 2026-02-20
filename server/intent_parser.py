from __future__ import annotations

from google import genai
from google.genai import types

from server import config
from server.models import ParsedIntent

MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """You parse voice commands for a TV streaming content launcher.
Extract the title, optional app/service, content type, and action from the command.

Rules:
- title: The name of the show or movie the user wants to watch
- app: The streaming service if explicitly mentioned (e.g., "on Netflix", "on Hulu"). Use lowercase. None if not specified.
- content_type: "movie" if clearly a movie, "tv" if clearly a TV show/series, "unknown" if ambiguous
- action: "play" (default, for watching), "search" (for finding/searching), "browse" (for browsing a service)

Examples:
- "Play Severance on Apple TV" → title="Severance", app="apple tv+", content_type="tv", action="play"
- "Watch The Batman" → title="The Batman", app=null, content_type="movie", action="play"
- "Search for Stranger Things on Netflix" → title="Stranger Things", app="netflix", content_type="tv", action="search"
- "Find me a good comedy movie" → title="comedy movie", app=null, content_type="movie", action="browse"
- "Put on The Office" → title="The Office", app=null, content_type="tv", action="play"
- "Play Dune Part Two" → title="Dune Part Two", app=null, content_type="movie", action="play"
"""

_client: genai.Client | None = None


def init() -> None:
    global _client
    _client = genai.Client(api_key=config.GEMINI_API_KEY)


async def parse(command: str) -> ParsedIntent:
    if _client is None:
        raise RuntimeError("Intent parser not initialized")
    response = await _client.aio.models.generate_content(
        model=MODEL,
        contents=command,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ParsedIntent,
            system_instruction=SYSTEM_PROMPT,
            temperature=0.1,
        ),
    )
    return ParsedIntent.model_validate_json(response.text)
