# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Dashboard API: FastAPI REST endpoints for the optimization dashboard.

Endpoints:
    GET  /api/sessions              → List all sessions
    GET  /api/sessions/{id}         → Get session details
    GET  /api/sessions/{id}/iterations → Get iteration history
    GET  /api/sessions/{id}/config  → Get final config XML
    GET  /api/sessions/{id}/config/{iter} → Get config for specific iteration
    GET  /health                    → Health check
    GET  /                          → Serve dashboard HTML

The dashboard frontend is a single-page HTML file served from the frontend/ directory.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...utils.logger import get_logger
from .data_store import (
    get_config_content,
    get_session,
    get_session_iterations,
    list_sessions,
)

logger = get_logger(__name__)

# Path to the frontend HTML file
_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


def create_app():
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI app instance.
    """
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
        from fastapi.staticfiles import StaticFiles
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError:
        raise ImportError(
            "FastAPI is required for the dashboard. "
            "Install with: pip install fastapi uvicorn"
        )

    app = FastAPI(
        title="ROS2 DDSConfig Optimizer Dashboard",
        description="Monitor and manage FastDDS optimization sessions",
        version="1.0.0",
    )

    # Restrict CORS to local dashboard origins by default. Override with the
    # DDS_OPTIMIZER_CORS_ORIGINS env var (comma-separated) if the dashboard is
    # served from a different host. A wildcard "*" is intentionally avoided.
    default_origins = "http://localhost:5000,http://127.0.0.1:5000"
    allowed_origins = [
        o.strip()
        for o in os.environ.get("DDS_OPTIMIZER_CORS_ORIGINS", default_origins).split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # -----------------------------------------------------------------------
    # Health check
    # -----------------------------------------------------------------------
    @app.get("/health")
    def health_check():
        """Health check endpoint."""
        return {"status": "ok", "service": "dds-optimizer-dashboard"}

    # -----------------------------------------------------------------------
    # Sessions API
    # -----------------------------------------------------------------------
    @app.get("/api/sessions")
    def api_list_sessions() -> List[Dict[str, Any]]:
        """List all optimization sessions with summary information."""
        try:
            return list_sessions()
        except Exception as e:
            logger.error(f"Failed to list sessions: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/sessions/{session_id}")
    def api_get_session(session_id: str) -> Dict[str, Any]:
        """Get full details of a specific optimization session."""
        state = get_session(session_id)
        if state is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{session_id}' not found",
            )
        return state

    @app.get("/api/sessions/{session_id}/iterations")
    def api_get_iterations(session_id: str) -> List[Dict[str, Any]]:
        """Get the iteration history for a session."""
        iterations = get_session_iterations(session_id)
        if not iterations and get_session(session_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{session_id}' not found",
            )
        return iterations

    @app.get("/api/sessions/{session_id}/config")
    def api_get_final_config(session_id: str):
        """Get the final optimized FastDDS XML configuration."""
        content = get_config_content(session_id, iteration=None)
        if content is None:
            raise HTTPException(
                status_code=404,
                detail=f"Final config for session '{session_id}' not found",
            )
        return PlainTextResponse(content=content, media_type="application/xml")

    @app.get("/api/sessions/{session_id}/config/{iteration}")
    def api_get_iteration_config(session_id: str, iteration: int):
        """Get the FastDDS XML configuration for a specific iteration."""
        content = get_config_content(session_id, iteration=iteration)
        if content is None:
            raise HTTPException(
                status_code=404,
                detail=f"Config for session '{session_id}' iteration {iteration} not found",
            )
        return PlainTextResponse(content=content, media_type="application/xml")

    # -----------------------------------------------------------------------
    # Frontend
    # -----------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def serve_dashboard():
        """Serve the dashboard HTML page."""
        index_html = _FRONTEND_DIR / "index.html"
        if index_html.exists():
            return HTMLResponse(content=index_html.read_text())
        else:
            # Fallback: return a minimal HTML page
            return HTMLResponse(content=_get_fallback_html())

    return app


def _get_fallback_html() -> str:
    """Return a minimal fallback HTML page if the frontend file is missing."""
    return """<!DOCTYPE html>
<html>
<head>
    <title>FastDDS Optimizer Dashboard</title>
    <style>
        body { font-family: sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; }
        h1 { color: #333; }
        .error { color: #c00; background: #fee; padding: 10px; border-radius: 4px; }
    </style>
</head>
<body>
    <h1>ROS2 DDSConfig Optimizer Dashboard</h1>
    <div class="error">
        Frontend file not found. Please check the installation.
    </div>
    <p>API endpoints are available at <a href="/api/sessions">/api/sessions</a></p>
    <p>API documentation: <a href="/docs">/docs</a></p>
</body>
</html>"""
