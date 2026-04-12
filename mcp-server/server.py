"""
Mali Daftari MCP Server
Simplified with single connection pool for optimal reliability
"""

from fastapi import FastAPI, HTTPException, Request

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from pydantic import BaseModel
import asyncpg
import os
import logging
from datetime import datetime
from urllib.parse import urlparse
from typing import Optional, List, Any
import time

from performance_logger import PerformanceLogger
import admin
from admin import broadcast_to_admins

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(
    title="Mali Daftari MCP Server",
    version="2.1.0",
    description="MCP server with single reliable connection pool"
)

# Rate limiter — per-tenant limiting keyed on X-Business-ID.
# In a Docker environment every request arrives from the same backend
# container IP, so get_remote_address would create one shared bucket for
# the entire platform. Keying on X-Business-ID gives each tenant its own
# independent quota. Falls back to remote address for requests that arrive
# without the header (e.g. health checks, the admin dashboard).
def key_by_business(request: Request) -> str:
    return request.headers.get("X-Business-ID") or get_remote_address(request)

limiter = Limiter(key_func=key_by_business)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Mount admin dashboard router (metrics + WebSocket)
app.include_router(admin.router)

# Global state - SINGLE CONNECTION POOL
db_pool: Optional[asyncpg.Pool] = None  # Single pool for all operations
performance_logger = None


# ============================================
# MODELS
# ============================================

class QueryRequest(BaseModel):
    sql: str
    business_id: Optional[str] = None
    session_id: Optional[str] = None
    params: List[Any] = []


class LogInteractionRequest(BaseModel):
    business_id: str
    session_id: str
    original_query: str
    detected_language: str
    query_type: str
    generated_sql: Optional[str] = None
    query_success: bool
    response_text: str
    response_language: str
    total_processing_time_ms: int
    error_message: Optional[str] = None


class VerifyOwnerRequest(BaseModel):
    user_id: str
    business_id: str


# ============================================
# STARTUP & SHUTDOWN
# ============================================

@app.on_event("startup")
async def startup():
    """Initialize services with single reliable connection pool"""
    global db_pool, performance_logger
    
    logger.info("=" * 60)
    logger.info("🚀 Mali Daftari MCP Server Starting...")
    logger.info("=" * 60)
    
    # Initialize single database pool
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("❌ DATABASE_URL not configured")
        logger.warning("⚠️ Server starting WITHOUT database connection")
        db_pool = None
    else:
        try:
            parsed = urlparse(database_url)
            
            logger.info(f"🔌 Connecting to database: {parsed.hostname}:{parsed.port}")
            
            # ===== SINGLE POOL: NO CACHE - TRANSACTION POOLER COMPATIBLE =====
            logger.info("📊 Initializing database connection pool (NO statement cache)...")
            db_pool = await asyncpg.create_pool(
                user=parsed.username,
                password=parsed.password,
                database=parsed.path[1:],
                host=parsed.hostname,
                port=parsed.port or 5432,
                ssl='require',
                min_size=3,
                max_size=15,
                timeout=10,
                statement_cache_size=0,  # NO CACHE - Required for Supabase Transaction Pooler
                command_timeout=60
            )
            
            # Test connection
            async with db_pool.acquire() as conn:
                result = await conn.fetchval('SELECT 1')
                logger.info(f"✅ Database pool tested: {result}")
            
            logger.info("✅ Database pool initialized (statement_cache_size=0)")
            
            # Inject pool into admin router
            admin.set_pool(db_pool)
            logger.info("✅ Admin router pool configured")

            # Initialize performance logger
            performance_logger = PerformanceLogger(db_pool)
            logger.info("✅ Performance logger initialized")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize database: {e}")
            logger.warning("⚠️ Server starting WITHOUT database connection")
            db_pool = None
            performance_logger = None
    
    logger.info("=" * 60)
    logger.info("✅ MCP Server Ready!")
    logger.info(f"   - Database Pool: {'Connected (statement_cache_size=0)' if db_pool else 'Disconnected'}")
    logger.info(f"   - Transaction Pooler Compatible: YES")
    logger.info(f"   - Multilingual: Claude native (no local models)")
    logger.info(f"   - Performance Logging: {'Enabled' if performance_logger else 'Disabled'}")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    global db_pool

    if db_pool:
        await db_pool.close()
        logger.info("Database pool closed")


# ============================================
# CORE ENDPOINTS
# ============================================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Mali Daftari MCP Server",
        "version": "2.1.0",
        "status": "running",
        "features": {
            "single_reliable_pool": True,
            "statement_cache_disabled": True,
            "transaction_pooler_compatible": True,
            "translation": "claude_native",
            "monitoring": performance_logger is not None,
            "real_time_admin": True
        }
    }


@app.get("/health")
async def health():
    """Health check"""
    pool_status = "connected" if db_pool else "disconnected"

    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "database_pool": pool_status,
        "translation": "claude_native",
        "admin_connections": len(admin.admin_connections)
    }


@app.get("/test")
async def test_endpoint():
    """Simple test endpoint for debugging"""
    return {
        "message": "MCP server is running!",
        "timestamp": datetime.utcnow().isoformat(),
        "pool_connected": db_pool is not None,
        "translation": "claude_native"
    }


@app.post("/query")
@limiter.limit("60/minute")
async def execute_query(request: Request, payload: QueryRequest):
    """
    Execute SQL query with monitoring
    USES SINGLE POOL (NO CACHE) for reliability
    """

    if not db_pool:
        raise HTTPException(status_code=500, detail="Database not initialized")

    start_time = time.time()

    # Security: Only allow SELECT queries
    sql = payload.sql.strip().upper()
    if not sql.startswith("SELECT"):
        logger.warning(f"Rejected non-SELECT query: {payload.sql[:50]}...")
        raise HTTPException(status_code=400, detail="Only SELECT queries are allowed")

    try:
        logger.info(f"Executing query: {payload.sql[:100]}...")

        # Execute query using reliable pool
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(payload.sql, *payload.params)
            result = [dict(row) for row in rows]

            processing_time = int((time.time() - start_time) * 1000)

            logger.info(f"✅ Query successful: {len(result)} rows in {processing_time}ms")

            # Broadcast to admin panel
            await broadcast_to_admins({
                "type": "query_executed",
                "business_id": payload.business_id,
                "row_count": len(result),
                "processing_time_ms": processing_time,
                "timestamp": datetime.utcnow().isoformat()
            })

            return {
                "rows": result,
                "row_count": len(result),
                "columns": list(result[0].keys()) if result else [],
                "processing_time_ms": processing_time
            }

    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


# ============================================
# INTERACTION LOGGING ENDPOINT
# ============================================

@app.post("/log-interaction")
async def log_interaction(request: LogInteractionRequest):
    """
    Log AI agent interaction for monitoring and analytics.
    Delegates persistence to PerformanceLogger.
    """

    if not performance_logger:
        logger.warning("⚠️ Performance logger not available - cannot log interaction")
        return {"status": "skipped", "reason": "database_unavailable"}

    try:
        interaction_id = await performance_logger.log_interaction(
            business_id=request.business_id,
            session_id=request.session_id,
            original_query=request.original_query,
            detected_language=request.detected_language,
            query_type=request.query_type,
            generated_sql=request.generated_sql,
            query_success=request.query_success,
            response_text=request.response_text,
            response_language=request.response_language,
            total_processing_time_ms=request.total_processing_time_ms,
            error_message=request.error_message,
        )

        logger.info(f"📝 Logged interaction: {interaction_id} (business: {request.business_id[:8]}..., type: {request.query_type}, success: {request.query_success})")

        # Broadcast to admin panel
        await broadcast_to_admins({
            "type": "interaction_logged",
            "interaction_id": interaction_id,
            "business_id": request.business_id,
            "query_type": request.query_type,
            "language": request.detected_language,
            "success": request.query_success,
            "processing_time_ms": request.total_processing_time_ms,
            "timestamp": datetime.utcnow().isoformat()
        })

        return {
            "status": "success",
            "interaction_id": interaction_id,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"❌ Failed to log interaction: {e}")
        raise HTTPException(status_code=500, detail=f"Logging failed: {str(e)}")



# ============================================
# INTERNAL AUTH ENDPOINT
# ============================================

@app.post("/internal/verify-owner")
async def verify_owner(payload: VerifyOwnerRequest):
    """
    Check whether a user holds the 'owner' role for a given business.
    Called only by the backend service — not exposed externally.
    """
    if not db_pool:
        raise HTTPException(status_code=500, detail="Database not initialized")

    try:
        async with db_pool.acquire() as conn:
            role = await conn.fetchval(
                "SELECT role FROM business_members WHERE user_id = $1 AND business_id = $2 LIMIT 1",
                payload.user_id,
                payload.business_id,
            )

        is_owner = role == "owner"
        logger.info(
            f"🔐 verify-owner: user={payload.user_id[:8]}... business={payload.business_id[:8]}... "
            f"role={role!r} is_owner={is_owner}"
        )
        return {"is_owner": is_owner}

    except asyncpg.PostgresError as e:
        logger.error(f"DB error in verify-owner: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    except Exception as e:
        logger.error(f"Unexpected error in verify-owner: {e}")
        raise HTTPException(status_code=500, detail=f"Verification failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")