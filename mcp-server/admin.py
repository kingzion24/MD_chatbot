"""
Admin dashboard router.

Owns:
  - admin_connections  — the set of live WebSocket clients
  - broadcast_to_admins() — called by server.py after /query and /log-interaction
  - GET /admin/metrics/live  — HTTP polling endpoint
  - WS  /ws/admin            — real-time event stream

The database pool is injected at startup by server.py via set_pool().
"""

import asyncpg
import logging
from datetime import datetime
from typing import Optional, Set

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from metrics import get_live_metrics, get_realtime_metrics

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

# All currently connected admin WebSocket clients.
admin_connections: Set[WebSocket] = set()

# Pool reference — injected by server.py after the pool is initialised.
_pool: Optional[asyncpg.Pool] = None


def set_pool(pool: asyncpg.Pool) -> None:
    """Called once by server.py after the database pool is ready."""
    global _pool
    _pool = pool


# ---------------------------------------------------------------------------
# Broadcast helper (called by server.py core endpoints)
# ---------------------------------------------------------------------------

async def broadcast_to_admins(message: dict) -> None:
    """Push an event to every connected admin WebSocket client."""
    if not admin_connections:
        return

    disconnected: Set[WebSocket] = set()
    for ws in admin_connections:
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.add(ws)

    for ws in disconnected:
        admin_connections.discard(ws)


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------

@router.get("/admin/metrics/live")
async def admin_metrics_live():
    """Real-time metrics for the admin panel (HTTP polling)."""
    if not _pool:
        return {
            "status": "database_unavailable",
            "timestamp": datetime.utcnow().isoformat(),
            "today": {},
            "last_hour": {},
            "recent_interactions": [],
        }
    try:
        return await get_live_metrics(_pool)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Metrics retrieval failed: {str(e)}")


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws/admin")
async def admin_websocket(websocket: WebSocket):
    """WebSocket stream for admin panel real-time updates."""
    await websocket.accept()
    admin_connections.add(websocket)
    logger.info(f"👨‍💼 Admin connected (total: {len(admin_connections)})")

    try:
        if _pool:
            metrics = await get_realtime_metrics(_pool)
            await websocket.send_json({
                "type": "initial_metrics",
                "data": metrics,
                "timestamp": datetime.utcnow().isoformat(),
            })

        while True:
            try:
                data = await websocket.receive_json()

                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

                elif data.get("type") == "request_metrics":
                    if _pool:
                        metrics = await get_realtime_metrics(_pool)
                        await websocket.send_json({
                            "type": "metrics_update",
                            "data": metrics,
                            "timestamp": datetime.utcnow().isoformat(),
                        })

            except WebSocketDisconnect:
                break

    except Exception as e:
        logger.error(f"Admin WebSocket error: {e}")

    finally:
        admin_connections.discard(websocket)
        logger.info(f"👨‍💼 Admin disconnected (remaining: {len(admin_connections)})")
