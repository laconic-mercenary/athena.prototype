"""FastAPI application factory.

Creates the app, registers middleware, mounts routes, and wires up the
asyncio event loop for the PyPubSub bridge on startup.

In production the React build (src/ui/dist/) is served as static files
from the same process. In development, Vite (port 5173) proxies API
requests to FastAPI (port 8000) — no static serving needed in that mode.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from athena.server import bus
from athena.server.routes import artifacts, chat, engagements, events, gate_decision, loop_gate, plan_review, report_chat, specialist_config
from athena import collaboration


###############
# CONSTS / GLOBALS #
###############

_UI_DIST = Path(__file__).parent.parent.parent.parent / "src" / "ui" / "dist"


###############
# FUNCTIONS #
###############

def create_app() -> FastAPI:
    app = FastAPI(title="Athena", lifespan=_lifespan)

    # Allow the Vite dev server to call the API without CORS errors.
    # In production this origin is not served, so the header is harmless.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(engagements.router)
    app.include_router(events.router)
    app.include_router(chat.router)
    app.include_router(artifacts.router)
    app.include_router(plan_review.router)
    app.include_router(gate_decision.router)
    app.include_router(loop_gate.router)
    app.include_router(report_chat.router)
    app.include_router(specialist_config.router)

    if collaboration.COLLABORATION_ENABLED:
        from athena.server.routes import collaboration as _collab_routes
        app.include_router(_collab_routes.router)

    # Serve the built React app when dist/ exists (production mode).
    if _UI_DIST.is_dir():
        app.mount("/", StaticFiles(directory=_UI_DIST, html=True), name="ui")

    return app


###############
# NON PUBLIC FUNCTIONS #
###############

@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Register the running event loop with the bus before any pipeline starts.
    bus.register_loop(asyncio.get_running_loop())
    yield
