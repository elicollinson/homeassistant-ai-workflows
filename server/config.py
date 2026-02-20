import os

# Required
GEMINI_API_KEY: str = ""
TMDB_API_KEY: str = ""
APPLE_TV_ID: str = ""

# Optional with defaults
STREAMING_AVAILABILITY_API_KEY: str = ""
WATCHMODE_API_KEY: str = ""
DRY_RUN: bool = False
LOG_LEVEL: str = "INFO"
CACHE_DIR: str = "/config"
PYATV_CONF: str = "/config/.pyatv.conf"
SERVER_PORT: int = 8888


def load() -> None:
    global GEMINI_API_KEY, TMDB_API_KEY, APPLE_TV_ID
    global STREAMING_AVAILABILITY_API_KEY, WATCHMODE_API_KEY
    global DRY_RUN, LOG_LEVEL, CACHE_DIR, PYATV_CONF, SERVER_PORT

    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
    APPLE_TV_ID = os.environ.get("APPLE_TV_ID", "")
    STREAMING_AVAILABILITY_API_KEY = os.environ.get("STREAMING_AVAILABILITY_API_KEY", "")
    WATCHMODE_API_KEY = os.environ.get("WATCHMODE_API_KEY", "")
    DRY_RUN = os.environ.get("DRY_RUN", "false").lower() in ("true", "1", "yes")
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
    CACHE_DIR = os.environ.get("CACHE_DIR", "/config")
    PYATV_CONF = os.environ.get("PYATV_CONF", "/config/.pyatv.conf")
    SERVER_PORT = int(os.environ.get("SERVER_PORT", "8888"))
