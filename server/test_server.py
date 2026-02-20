from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from server.models import ContentResult, ParsedIntent, StreamingOption, WebhookResponse
from server import config, cache, intent_parser, content_lookup, apple_tv_control


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("TMDB_API_KEY", "test-tmdb-key")
    monkeypatch.setenv("APPLE_TV_ID", "test-apple-tv-id")
    monkeypatch.setenv("STREAMING_AVAILABILITY_API_KEY", "test-sa-key")
    monkeypatch.setenv("WATCHMODE_API_KEY", "test-wm-key")
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("CACHE_DIR", "/tmp")


@pytest.fixture
def client():
    with (
        patch.object(cache, "init", new_callable=AsyncMock),
        patch.object(cache, "close", new_callable=AsyncMock),
        patch.object(intent_parser, "init"),
    ):
        from server.server import app
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intent(title="Severance", app="apple tv+", content_type="tv", action="play"):
    return ParsedIntent(title=title, app=app, content_type=content_type, action=action)


def _make_content(
    tmdb_id=12345,
    title="Severance",
    year=2022,
    content_type="tv",
    options=None,
):
    if options is None:
        options = [
            StreamingOption(
                service="apple",
                bundle_id="com.apple.Prospect",
                deep_link="https://tv.apple.com/show/severance/123",
                type="sub",
            )
        ]
    return ContentResult(
        tmdb_id=tmdb_id,
        title=title,
        year=year,
        overview="A thriller about work-life balance",
        content_type=content_type,
        streaming_options=options,
    )


# ===========================================================================
# Intent Parsing Tests
# ===========================================================================


class TestIntentParsing:
    def test_play_with_app(self):
        intent = _make_intent(title="Severance", app="apple tv+", action="play")
        assert intent.title == "Severance"
        assert intent.app == "apple tv+"
        assert intent.action == "play"
        assert intent.content_type == "tv"

    def test_play_without_app(self):
        intent = _make_intent(title="The Batman", app=None, content_type="movie")
        assert intent.app is None
        assert intent.content_type == "movie"

    def test_search_action(self):
        intent = _make_intent(title="Stranger Things", action="search")
        assert intent.action == "search"

    def test_content_type_detection(self):
        movie = _make_intent(content_type="movie")
        tv = _make_intent(content_type="tv")
        unknown = _make_intent(content_type="unknown")
        assert movie.content_type == "movie"
        assert tv.content_type == "tv"
        assert unknown.content_type == "unknown"

    def test_default_values(self):
        intent = ParsedIntent(title="Test")
        assert intent.app is None
        assert intent.content_type == "unknown"
        assert intent.action == "play"


# ===========================================================================
# Content Lookup Tests
# ===========================================================================


class TestContentLookup:
    def test_pick_best_option_preferred_app(self):
        options = [
            StreamingOption(service="netflix", bundle_id="com.netflix.Netflix", type="sub"),
            StreamingOption(service="apple", bundle_id="com.apple.Prospect", deep_link="https://example.com", type="sub"),
        ]
        best = content_lookup.pick_best_option(options, preferred_app="apple tv+")
        assert best is not None
        assert best.service == "apple"

    def test_pick_best_option_prefer_deep_link(self):
        options = [
            StreamingOption(service="netflix", bundle_id="com.netflix.Netflix", type="sub"),
            StreamingOption(service="hulu", bundle_id="com.hulu.plus", deep_link="https://example.com", type="sub"),
        ]
        best = content_lookup.pick_best_option(options, preferred_app=None)
        assert best is not None
        assert best.service == "hulu"

    def test_pick_best_option_prefer_sub_over_rent(self):
        options = [
            StreamingOption(service="vudu", bundle_id="com.vudu", type="rent", price=3.99),
            StreamingOption(service="netflix", bundle_id="com.netflix.Netflix", type="sub"),
        ]
        best = content_lookup.pick_best_option(options, preferred_app=None)
        assert best is not None
        assert best.service == "netflix"

    def test_pick_best_option_empty_list(self):
        best = content_lookup.pick_best_option([], preferred_app=None)
        assert best is None

    def test_pick_best_option_no_preferred_no_deep_link(self):
        options = [
            StreamingOption(service="rent_service", type="rent", price=4.99),
            StreamingOption(service="sub_service", type="sub"),
        ]
        best = content_lookup.pick_best_option(options, preferred_app=None)
        assert best is not None
        assert best.service == "sub_service"

    @pytest.mark.asyncio
    async def test_tmdb_search_movie(self):
        intent = _make_intent(title="The Batman", content_type="movie", app=None)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [{"id": 414906, "title": "The Batman", "release_date": "2022-03-01", "overview": "A dark knight", "poster_path": "/poster.jpg"}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch.object(cache, "get", new_callable=AsyncMock, return_value=None), \
             patch.object(cache, "store", new_callable=AsyncMock):
            with patch.object(content_lookup, "_query_streaming_availability", new_callable=AsyncMock, return_value=[]):
                result = await content_lookup.lookup(intent, mock_client)

        assert result is not None
        assert result.tmdb_id == 414906
        assert result.title == "The Batman"
        assert result.content_type == "movie"

    @pytest.mark.asyncio
    async def test_tmdb_search_tv(self):
        intent = _make_intent(title="Severance", content_type="tv", app=None)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [{"id": 95396, "name": "Severance", "first_air_date": "2022-02-18", "overview": "A thriller", "poster_path": None}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch.object(cache, "get", new_callable=AsyncMock, return_value=None), \
             patch.object(cache, "store", new_callable=AsyncMock):
            with patch.object(content_lookup, "_query_streaming_availability", new_callable=AsyncMock, return_value=[]):
                result = await content_lookup.lookup(intent, mock_client)

        assert result is not None
        assert result.tmdb_id == 95396
        assert result.content_type == "tv"

    @pytest.mark.asyncio
    async def test_tmdb_not_found(self):
        intent = _make_intent(title="xyznonexistent", content_type="movie", app=None)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        result = await content_lookup.lookup(intent, mock_client)
        assert result is None


# ===========================================================================
# Apple TV Control Tests
# ===========================================================================


class TestAppleTVControl:
    @pytest.mark.asyncio
    async def test_launch_with_deep_link(self):
        mock_atv = AsyncMock()
        mock_atv.apps = AsyncMock()
        mock_atv.apps.launch_app = AsyncMock()
        mock_atv.close = MagicMock()

        with patch.object(apple_tv_control, "connect", new_callable=AsyncMock, return_value=mock_atv):
            method = await apple_tv_control.launch("com.netflix.Netflix", deep_link="https://example.com")

        assert method == "deep_link"
        mock_atv.apps.launch_app.assert_called_once_with("com.netflix.Netflix", url="https://example.com")

    @pytest.mark.asyncio
    async def test_launch_without_deep_link(self):
        mock_atv = AsyncMock()
        mock_atv.apps = AsyncMock()
        mock_atv.apps.launch_app = AsyncMock()
        mock_atv.close = MagicMock()

        with patch.object(apple_tv_control, "connect", new_callable=AsyncMock, return_value=mock_atv):
            method = await apple_tv_control.launch("com.netflix.Netflix")

        assert method == "app_launch"
        mock_atv.apps.launch_app.assert_called_once_with("com.netflix.Netflix")

    @pytest.mark.asyncio
    async def test_device_not_found(self):
        with patch.object(apple_tv_control, "scan_devices", new_callable=AsyncMock, return_value=[]):
            with pytest.raises(ConnectionError, match="Apple TV not found"):
                await apple_tv_control.connect("nonexistent")


# ===========================================================================
# Webhook Integration Tests
# ===========================================================================


class TestWebhookIntegration:
    def test_full_dry_run_flow(self, client):
        mock_intent = _make_intent()
        mock_content = _make_content()

        with patch.object(intent_parser, "parse", new_callable=AsyncMock, return_value=mock_intent), \
             patch.object(content_lookup, "lookup", new_callable=AsyncMock, return_value=mock_content):
            resp = client.post("/webhook", json={"command": "Play Severance on Apple TV"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["title"] == "Severance"
        assert data["service"] == "apple"
        assert data["method_used"] == "dry_run"

    def test_content_not_found(self, client):
        mock_intent = _make_intent(title="xyznonexistent")

        with patch.object(intent_parser, "parse", new_callable=AsyncMock, return_value=mock_intent), \
             patch.object(content_lookup, "lookup", new_callable=AsyncMock, return_value=None):
            resp = client.post("/webhook", json={"command": "Play xyznonexistent"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "Could not find" in data["message"]

    def test_no_streaming_options(self, client):
        mock_intent = _make_intent()
        mock_content = _make_content(options=[])

        with patch.object(intent_parser, "parse", new_callable=AsyncMock, return_value=mock_intent), \
             patch.object(content_lookup, "lookup", new_callable=AsyncMock, return_value=mock_content):
            resp = client.post("/webhook", json={"command": "Play Severance"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "No streaming options" in data["message"]

    def test_health_endpoint(self, client):
        with patch.object(apple_tv_control, "check_connectivity", new_callable=AsyncMock, return_value=False):
            resp = client.get("/health")

        assert resp.status_code == 503
        data = resp.json()
        assert data["healthy"] is False
        assert data["dry_run"] is True

    def test_devices_endpoint(self, client):
        mock_device = MagicMock()
        mock_device.name = "Living Room"
        mock_device.identifier = "AABB-CCDD"
        mock_device.address = "192.168.1.100"

        with patch.object(apple_tv_control, "scan_devices", new_callable=AsyncMock, return_value=[mock_device]):
            resp = client.get("/devices")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Living Room"

    def test_invalid_command_body(self, client):
        resp = client.post("/webhook", json={"wrong_field": "test"})
        assert resp.status_code == 422


# ===========================================================================
# Error Handling Tests
# ===========================================================================


class TestErrorHandling:
    def test_gemini_failure(self, client):
        with patch.object(intent_parser, "parse", new_callable=AsyncMock, side_effect=RuntimeError("Gemini API error")):
            resp = client.post("/webhook", json={"command": "Play something"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "Failed to parse" in data["message"]

    def test_tmdb_failure(self, client):
        mock_intent = _make_intent()

        with patch.object(intent_parser, "parse", new_callable=AsyncMock, return_value=mock_intent), \
             patch.object(content_lookup, "lookup", new_callable=AsyncMock, side_effect=Exception("TMDb down")):
            resp = client.post("/webhook", json={"command": "Play Severance"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "Content lookup failed" in data["message"]

    def test_apple_tv_unreachable(self, client):
        mock_intent = _make_intent()
        mock_content = _make_content()

        config.DRY_RUN = False
        try:
            with patch.object(intent_parser, "parse", new_callable=AsyncMock, return_value=mock_intent), \
                 patch.object(content_lookup, "lookup", new_callable=AsyncMock, return_value=mock_content), \
                 patch.object(apple_tv_control, "launch", new_callable=AsyncMock, side_effect=ConnectionError("Apple TV not found")):
                resp = client.post("/webhook", json={"command": "Play Severance on Apple TV"})
        finally:
            config.DRY_RUN = True

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "Failed to launch" in data["message"]
