from __future__ import annotations

import structlog
import httpx

from server import cache, config
from server.models import ContentResult, ParsedIntent, StreamingOption

log = structlog.get_logger()

# User-facing name → Apple TV bundle ID.
# This is the single source of truth for bundle ID resolution.
# Both voice command matching and streaming-API mapping use this table.
BUNDLE_IDS: dict[str, str] = {
    "netflix": "com.netflix.Netflix",
    "hulu": "com.hulu.plus",
    "disney": "com.disney.disneyplus",
    "disney+": "com.disney.disneyplus",
    "disney plus": "com.disney.disneyplus",
    "amazon": "com.amazon.aiv.AIVApp",
    "amazon prime": "com.amazon.aiv.AIVApp",
    "prime": "com.amazon.aiv.AIVApp",
    "prime video": "com.amazon.aiv.AIVApp",
    "apple": "com.apple.Prospect",
    "apple tv+": "com.apple.Prospect",
    "apple tv plus": "com.apple.Prospect",
    "hbo": "com.warnermedia.HBONow",
    "hbo max": "com.warnermedia.HBONow",
    "max": "com.warnermedia.HBONow",
    "peacock": "com.peacocktv.peacocktvtv",
    "paramount": "com.cbs.ott",
    "paramount+": "com.cbs.ott",
    "paramount plus": "com.cbs.ott",
    "showtime": "com.showtime.standalone",
    "crunchyroll": "com.crunchyroll.iphone",
    "tubi": "com.tubitv",
    "plutotv": "com.pluto.tv",
    "pluto tv": "com.pluto.tv",
    "plex": "com.plexapp.plex",
    "youtube": "com.google.ios.youtube",
    "youtube tv": "com.google.ios.youtubeunplugged",
    "starz": "com.starz.starzplay",
    "vudu": "com.vudu.air.DigitalCopyProvider",
    "fandango at home": "com.vudu.air.DigitalCopyProvider",
}


async def lookup(intent: ParsedIntent, http_client: httpx.AsyncClient) -> ContentResult | None:
    tmdb_result = await _search_tmdb(intent, http_client)
    if tmdb_result is None:
        return None

    cached = await cache.get(tmdb_result.tmdb_id)
    if cached is not None:
        log.info("cache_hit", tmdb_id=tmdb_result.tmdb_id)
        return ContentResult.model_validate(cached)

    options = await _query_streaming_availability(tmdb_result, http_client)

    if not options and config.WATCHMODE_API_KEY:
        log.info("falling_back_to_watchmode", tmdb_id=tmdb_result.tmdb_id)
        options = await _query_watchmode(tmdb_result, http_client)

    tmdb_result.streaming_options = options

    await cache.store(tmdb_result.tmdb_id, tmdb_result.model_dump())
    return tmdb_result


def pick_best_option(
    options: list[StreamingOption], preferred_app: str | None = None
) -> StreamingOption | None:
    if not options:
        return None

    if preferred_app:
        preferred_lower = preferred_app.lower()
        preferred_bundle = BUNDLE_IDS.get(preferred_lower)
        for opt in options:
            if opt.bundle_id == preferred_bundle or opt.service.lower() == preferred_lower:
                return opt

    # Rank: subscription with deep link > any deep link > subscription > first available
    def _sort_key(opt: StreamingOption) -> tuple[bool, bool]:
        return (not opt.deep_link, opt.type != "sub")

    ranked = sorted(options, key=_sort_key)
    return ranked[0]


async def _search_tmdb(intent: ParsedIntent, http_client: httpx.AsyncClient) -> ContentResult | None:
    search_types = []
    if intent.content_type in ("movie", "unknown"):
        search_types.append("movie")
    if intent.content_type in ("tv", "unknown"):
        search_types.append("tv")

    for media_type in search_types:
        try:
            resp = await http_client.get(
                f"https://api.themoviedb.org/3/search/{media_type}",
                params={"api_key": config.TMDB_API_KEY, "query": intent.title},
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if results:
                hit = results[0]
                title_key = "title" if media_type == "movie" else "name"
                date_key = "release_date" if media_type == "movie" else "first_air_date"
                year = None
                date_str = hit.get(date_key, "")
                if date_str and len(date_str) >= 4:
                    year = int(date_str[:4])
                poster = None
                if hit.get("poster_path"):
                    poster = f"https://image.tmdb.org/t/p/w500{hit['poster_path']}"
                return ContentResult(
                    tmdb_id=hit["id"],
                    title=hit.get(title_key, intent.title),
                    year=year,
                    overview=hit.get("overview"),
                    poster=poster,
                    content_type=media_type,
                )
        except httpx.HTTPError as e:
            log.error("tmdb_search_failed", error=str(e), media_type=media_type)
            raise

    return None


async def _query_streaming_availability(
    content: ContentResult, http_client: httpx.AsyncClient
) -> list[StreamingOption]:
    if not config.STREAMING_AVAILABILITY_API_KEY:
        return []

    show_type = "movie" if content.content_type == "movie" else "series"
    show_id = f"tmdb:{show_type}/{content.tmdb_id}"

    try:
        resp = await http_client.get(
            f"https://streaming-availability.p.rapidapi.com/shows/{show_id}",
            headers={
                "X-RapidAPI-Key": config.STREAMING_AVAILABILITY_API_KEY,
                "X-RapidAPI-Host": "streaming-availability.p.rapidapi.com",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        log.warning("streaming_availability_failed", error=str(e))
        return []

    options: list[StreamingOption] = []
    streaming_info = data.get("streamingOptions", {}).get("us", [])
    for entry in streaming_info:
        service_id = entry.get("service", {}).get("id", "")
        bundle_id = BUNDLE_IDS.get(service_id)
        opt_type = entry.get("type", "sub")
        price = None
        if entry.get("price"):
            price = entry["price"].get("amount")
        options.append(
            StreamingOption(
                service=service_id,
                bundle_id=bundle_id,
                deep_link=entry.get("link"),
                type=opt_type,
                price=price,
            )
        )

    return options


async def _query_watchmode(
    content: ContentResult, http_client: httpx.AsyncClient
) -> list[StreamingOption]:
    if not config.WATCHMODE_API_KEY:
        return []

    media_type = "movie" if content.content_type == "movie" else "tv"
    search_value = f"{media_type}-{content.tmdb_id}"

    try:
        resp = await http_client.get(
            "https://api.watchmode.com/v1/title/search/",
            params={
                "apiKey": config.WATCHMODE_API_KEY,
                "search_field": "tmdb_id",
                "search_value": search_value,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        titles = data.get("title_results", [])
        if not titles:
            return []
        watchmode_id = titles[0]["id"]
    except httpx.HTTPError as e:
        log.warning("watchmode_search_failed", error=str(e))
        return []

    try:
        resp = await http_client.get(
            f"https://api.watchmode.com/v1/title/{watchmode_id}/sources/",
            params={"apiKey": config.WATCHMODE_API_KEY},
        )
        resp.raise_for_status()
        sources = resp.json()
    except httpx.HTTPError as e:
        log.warning("watchmode_sources_failed", error=str(e))
        return []

    options: list[StreamingOption] = []
    for source in sources:
        service_name = source.get("name", "").lower()
        bundle_id = None
        for key, bid in BUNDLE_IDS.items():
            if key in service_name or service_name in key:
                bundle_id = bid
                break
        opt_type = "sub"
        source_type = source.get("type", "")
        if source_type == "rent":
            opt_type = "rent"
        elif source_type == "buy":
            opt_type = "buy"
        options.append(
            StreamingOption(
                service=source.get("name", "unknown"),
                bundle_id=bundle_id,
                deep_link=source.get("web_url"),
                type=opt_type,
                price=source.get("price"),
            )
        )

    return options
