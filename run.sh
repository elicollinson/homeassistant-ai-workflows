#!/usr/bin/with-bashio

export GEMINI_API_KEY="$(bashio::config 'gemini_api_key')"
export TMDB_API_KEY="$(bashio::config 'tmdb_api_key')"
export APPLE_TV_ID="$(bashio::config 'apple_tv_id')"
export STREAMING_AVAILABILITY_API_KEY="$(bashio::config 'streaming_availability_api_key')"
export WATCHMODE_API_KEY="$(bashio::config 'watchmode_api_key')"
export DRY_RUN="$(bashio::config 'dry_run')"
export LOG_LEVEL="$(bashio::config 'log_level')"
export CACHE_DIR="/config"
export PYATV_CONF="/config/.pyatv.conf"

exec python3 -m uvicorn server.server:app --host 0.0.0.0 --port 8888
