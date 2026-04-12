"""
Admin metrics — data access layer.
All functions accept an asyncpg pool as an argument and return plain dicts.
No global state; callers are responsible for providing an active pool.
"""

import asyncpg
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL constants
# ---------------------------------------------------------------------------

_TODAY_STATS_SQL = """
    SELECT
        COUNT(*) AS total_queries,
        COUNT(*) FILTER (WHERE query_success = true) AS successful_queries,
        ROUND(AVG(total_processing_time_ms)) AS avg_response_time,
        COUNT(DISTINCT business_id) AS active_businesses,
        COUNT(*) FILTER (WHERE detected_language = 'sw') AS swahili_queries,
        COUNT(*) FILTER (WHERE detected_language = 'en') AS english_queries
    FROM agent_interactions
    WHERE created_at >= CURRENT_DATE
      AND created_at <  CURRENT_DATE + INTERVAL '1 day'
"""

_LAST_HOUR_SQL = """
    SELECT
        COUNT(*) AS queries_last_hour,
        ROUND(AVG(total_processing_time_ms)) AS avg_time_last_hour
    FROM agent_interactions
    WHERE created_at >= NOW() - INTERVAL '1 hour'
"""

# Full version — includes query_type; used by the HTTP polling endpoint.
_RECENT_FULL_SQL = """
    SELECT
        original_query,
        detected_language,
        query_type,
        query_success,
        total_processing_time_ms,
        created_at
    FROM agent_interactions
    ORDER BY created_at DESC
    LIMIT 10
"""

# Compact version — omits query_type; used for the lighter WebSocket push.
_RECENT_COMPACT_SQL = """
    SELECT
        original_query,
        detected_language,
        query_success,
        total_processing_time_ms,
        created_at
    FROM agent_interactions
    ORDER BY created_at DESC
    LIMIT 10
"""

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_live_metrics(pool: asyncpg.Pool) -> dict:
    """
    Full metrics payload for the /admin/metrics/live HTTP endpoint.
    Includes query_type in recent_interactions and an ISO timestamp.

    Raises on database error so the caller can return an HTTP 500.
    """
    async with pool.acquire() as conn:
        today_stats = await conn.fetchrow(_TODAY_STATS_SQL)
        last_hour = await conn.fetchrow(_LAST_HOUR_SQL)
        recent = await conn.fetch(_RECENT_FULL_SQL)

    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "today": dict(today_stats) if today_stats else {},
        "last_hour": dict(last_hour) if last_hour else {},
        "recent_interactions": [
            {
                **dict(r),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in recent
        ],
    }


async def get_realtime_metrics(pool: asyncpg.Pool) -> dict:
    """
    Compact metrics payload pushed over the WebSocket connection.
    Returns an error-shape dict on failure so the caller does not crash.
    """
    try:
        async with pool.acquire() as conn:
            today_stats = await conn.fetchrow(_TODAY_STATS_SQL)
            last_hour = await conn.fetchrow(_LAST_HOUR_SQL)
            recent = await conn.fetch(_RECENT_COMPACT_SQL)

        return {
            "status": "healthy",
            "today": dict(today_stats) if today_stats else {},
            "last_hour": dict(last_hour) if last_hour else {},
            "recent_interactions": [dict(r) for r in recent],
        }
    except Exception as e:
        logger.error(f"Failed to get realtime metrics: {e}")
        return {
            "status": "error",
            "error": str(e),
            "today": {},
            "last_hour": {},
            "recent_interactions": [],
        }
