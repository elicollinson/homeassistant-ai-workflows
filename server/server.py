from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from server import apple_tv_control, cache, config, content_lookup, intent_parser
from server.models import WebhookRequest, WebhookResponse

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
)

log = structlog.get_logger()

resources: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.load()
    log.info("config_loaded", dry_run=config.DRY_RUN)

    resources["http_client"] = httpx.AsyncClient(timeout=30.0)
    await cache.init()
    intent_parser.init()

    yield

    await resources["http_client"].aclose()
    await cache.close()


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: WebhookRequest) -> WebhookResponse:
    log.info("webhook_received", command=request.command)

    try:
        intent = await intent_parser.parse(request.command)
        log.info("intent_parsed", intent=intent.model_dump())
    except Exception as e:
        log.error("intent_parse_failed", error=str(e))
        return WebhookResponse(success=False, message=f"Failed to parse command: {e}")

    try:
        result = await content_lookup.lookup(intent, resources["http_client"])
    except Exception as e:
        log.error("content_lookup_failed", error=str(e))
        return WebhookResponse(success=False, message=f"Content lookup failed: {e}")

    if result is None:
        return WebhookResponse(
            success=False,
            title=intent.title,
            message=f"Could not find '{intent.title}' on TMDb",
        )

    option = content_lookup.pick_best_option(result.streaming_options, intent.app)
    if option is None:
        return WebhookResponse(
            success=False,
            title=result.title,
            message=f"No streaming options found for '{result.title}'",
        )

    if config.DRY_RUN:
        log.info("dry_run", title=result.title, service=option.service, deep_link=option.deep_link)
        return WebhookResponse(
            success=True,
            title=result.title,
            service=option.service,
            deep_link=option.deep_link,
            method_used="dry_run",
            message="Dry run - no launch performed",
        )

    try:
        method = await apple_tv_control.launch(
            bundle_id=option.bundle_id or "",
            deep_link=option.deep_link,
        )
        log.info("launched", title=result.title, service=option.service, method=method)
        return WebhookResponse(
            success=True,
            title=result.title,
            service=option.service,
            deep_link=option.deep_link,
            method_used=method,
        )
    except Exception as e:
        log.error("launch_failed", error=str(e))
        return WebhookResponse(
            success=False,
            title=result.title,
            service=option.service,
            message=f"Failed to launch on Apple TV: {e}",
        )


@app.get("/health")
async def health():
    healthy = await apple_tv_control.check_connectivity()
    return JSONResponse(
        content={"healthy": healthy, "dry_run": config.DRY_RUN},
        status_code=200 if healthy else 503,
    )


@app.get("/devices")
async def devices():
    try:
        found = await apple_tv_control.scan_devices()
        return [
            {
                "name": d.name,
                "identifier": str(d.identifier),
                "address": str(d.address),
            }
            for d in found
        ]
    except Exception as e:
        log.error("device_scan_failed", error=str(e))
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/pair")
async def pair(request: dict):
    identifier = request.get("identifier", "")
    pin = request.get("pin")
    try:
        result = await apple_tv_control.pair_device(identifier, pin)
        return result
    except Exception as e:
        log.error("pairing_failed", error=str(e))
        return JSONResponse(content={"error": str(e)}, status_code=500)
