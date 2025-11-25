"""
Mali Daftari MCP Server
Simplified with single connection pool for optimal reliability
"""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncpg
import os
import logging
from datetime import datetime
from urllib.parse import urlparse
from typing import Optional, Dict, Set
import time
import json
import uuid

from translation_service import get_translation_service
from performance_logger import PerformanceLogger

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

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Global state - SINGLE CONNECTION POOL
db_pool: Optional[asyncpg.Pool] = None  # Single pool for all operations
admin_pool: Optional[asyncpg.Pool] = None  # Points to same pool as db_pool
translation_service = None
performance_logger = None

# WebSocket connections for admin panel real-time updates
admin_connections: Set[WebSocket] = set()


# ============================================
# MODELS
# ============================================

class QueryRequest(BaseModel):
    sql: str
    business_id: Optional[str] = None
    session_id: Optional[str] = None


class TranslateRequest(BaseModel):
    text: str
    source_lang: str  # "sw" or "en"
    target_lang: str  # "sw" or "en"


class DetectLanguageRequest(BaseModel):
    text: str


class LogInteractionRequest(BaseModel):
    business_id: str
    session_id: str
    original_query: str
    detected_language: str
    translated_query: Optional[str] = None
    query_type: str
    generated_sql: Optional[str] = None
    query_success: bool
    response_text: str
    response_language: str
    total_processing_time_ms: int
    error_message: Optional[str] = None


# ============================================
# STARTUP & SHUTDOWN
# ============================================

@app.on_event("startup")
async def startup():
    """Initialize services with single reliable connection pool"""
    global db_pool, admin_pool, translation_service, performance_logger
    
    logger.info("=" * 60)
    logger.info("🚀 Mali Daftari MCP Server Starting...")
    logger.info("=" * 60)
    
    # Initialize single database pool
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("❌ DATABASE_URL not configured")
        logger.warning("⚠️ Server starting WITHOUT database connection")
        db_pool = None
        admin_pool = None
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
            
            # Use same pool for admin operations
            admin_pool = db_pool
            logger.info("✅ Admin metrics pool: Using main pool (NO cache)")
            
            # Initialize performance logger
            performance_logger = PerformanceLogger(db_pool)
            logger.info("✅ Performance logger initialized")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize database: {e}")
            logger.warning("⚠️ Server starting WITHOUT database connection")
            db_pool = None
            admin_pool = None
            performance_logger = None
    
    # Initialize translation service (independent of database)
    try:
        translation_service = get_translation_service()
        logger.info("✅ Translation service initialized")
    except Exception as e:
        logger.error(f"⚠️ Translation service failed to load: {e}")
        translation_service = None
    
    logger.info("=" * 60)
    logger.info("✅ MCP Server Ready!")
    logger.info(f"   - Database Pool: {'Connected (statement_cache_size=0)' if db_pool else 'Disconnected'}")
    logger.info(f"   - Transaction Pooler Compatible: YES")
    logger.info(f"   - Translation: {'Disabled (using stubs)' if translation_service else 'Disabled'}")
    logger.info(f"   - Performance Logging: {'Enabled' if performance_logger else 'Disabled'}")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    global db_pool, admin_pool
    
    if db_pool:
        await db_pool.close()
        logger.info("Database pool closed")
    
    # admin_pool points to same pool, no need to close twice


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
            "translation": translation_service is not None,
            "monitoring": performance_logger is not None,
            "real_time_admin": True
        }
    }


@app.get("/health")
async def health():
    """Health check"""
    pool_status = "connected" if db_pool else "disconnected"
    translation_status = "disabled" if translation_service else "disabled"
    
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "database_pool": pool_status,
        "translation": translation_status,
        "admin_connections": len(admin_connections)
    }


@app.get("/test")
async def test_endpoint():
    """Simple test endpoint for debugging"""
    return {
        "message": "MCP server is running!",
        "timestamp": datetime.utcnow().isoformat(),
        "pool_connected": db_pool is not None,
        "translation_enabled": translation_service is not None
    }


@app.post("/query")
async def execute_query(request: QueryRequest):
    """
    Execute SQL query with monitoring
    USES SINGLE POOL (NO CACHE) for reliability
    """
    
    if not db_pool:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    start_time = time.time()
    
    # Security: Only allow SELECT queries
    sql = request.sql.strip().upper()
    if not sql.startswith("SELECT"):
        logger.warning(f"Rejected non-SELECT query: {request.sql[:50]}...")
        raise HTTPException(status_code=400, detail="Only SELECT queries are allowed")
    
    try:
        logger.info(f"Executing query: {request.sql[:100]}...")
        
        # Execute query using reliable pool
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(request.sql)
            result = [dict(row) for row in rows]
            
            processing_time = int((time.time() - start_time) * 1000)
            
            logger.info(f"✅ Query successful: {len(result)} rows in {processing_time}ms")
            
            # Broadcast to admin panel
            await broadcast_to_admins({
                "type": "query_executed",
                "business_id": request.business_id,
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
    Log AI agent interaction for monitoring and analytics
    USES SINGLE POOL (NO CACHE) for reliability
    """
    
    if not db_pool:
        logger.warning("⚠️ Database not available - cannot log interaction")
        return {"status": "skipped", "reason": "database_unavailable"}
    
    try:
        interaction_id = str(uuid.uuid4())
        
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO agent_interactions (
                    id,
                    business_id,
                    session_id,
                    original_query,
                    detected_language,
                    translated_query,
                    query_type,
                    generated_sql,
                    query_success,
                    response_text,
                    response_language,
                    total_processing_time_ms,
                    error_message,
                    created_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW()
                )
            """,
                interaction_id,
                request.business_id,
                request.session_id,
                request.original_query,
                request.detected_language,
                request.translated_query,
                request.query_type,
                request.generated_sql,
                request.query_success,
                request.response_text,
                request.response_language,
                request.total_processing_time_ms,
                request.error_message
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
# TRANSLATION ENDPOINTS (Stubs)
# ============================================

@app.post("/translate")
async def translate_text(request: TranslateRequest):
    """Translate text between languages (stub)"""
    
    if not translation_service:
        raise HTTPException(status_code=503, detail="Translation service not available")
    
    try:
        if request.source_lang == request.target_lang:
            return {"translated_text": request.text, "source_lang": request.source_lang}
        
        if request.source_lang == "sw" and request.target_lang == "en":
            result = translation_service.translate_sw_to_en(request.text)
        elif request.source_lang == "en" and request.target_lang == "sw":
            result = translation_service.translate_en_to_sw(request.text)
        else:
            raise HTTPException(status_code=400, detail="Invalid language pair")
        
        return {
            "translated_text": result,
            "source_lang": request.source_lang,
            "target_lang": request.target_lang
        }
        
    except Exception as e:
        logger.error(f"Translation error: {e}")
        raise HTTPException(status_code=500, detail=f"Translation failed: {str(e)}")


@app.post("/detect-language")
async def detect_language(request: DetectLanguageRequest):
    """Detect language of text (stub)"""
    
    if not translation_service:
        raise HTTPException(status_code=503, detail="Translation service not available")
    
    try:
        detected = translation_service.detect_language(request.text)
        
        return {
            "text": request.text,
            "detected_language": detected,
            "language_name": "Kiswahili" if detected == "sw" else "English"
        }
        
    except Exception as e:
        logger.error(f"Language detection error: {e}")
        raise HTTPException(status_code=500, detail=f"Detection failed: {str(e)}")


# ============================================
# ADMIN PANEL - METRICS ENDPOINTS
# ============================================

@app.get("/admin/metrics/live")
async def get_live_metrics():
    """
    Get real-time metrics for admin panel (HTTP polling version)
    USES SINGLE POOL (NO CACHE) for reliability
    """
    
    if not admin_pool:
        return {
            "status": "database_unavailable",
            "timestamp": datetime.utcnow().isoformat(),
            "today": {},
            "last_hour": {},
            "recent_interactions": []
        }
    
    try:
        async with admin_pool.acquire() as conn:
            # Today's stats
            today_stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total_queries,
                    COUNT(*) FILTER (WHERE query_success = true) as successful_queries,
                    ROUND(AVG(total_processing_time_ms)) as avg_response_time,
                    COUNT(DISTINCT business_id) as active_businesses,
                    COUNT(*) FILTER (WHERE detected_language = 'sw') as swahili_queries,
                    COUNT(*) FILTER (WHERE detected_language = 'en') as english_queries
                FROM agent_interactions
                WHERE DATE(created_at) = CURRENT_DATE
            """)
            
            # Last hour stats
            last_hour = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as queries_last_hour,
                    ROUND(AVG(total_processing_time_ms)) as avg_time_last_hour
                FROM agent_interactions
                WHERE created_at >= NOW() - INTERVAL '1 hour'
            """)
            
            # Recent interactions (last 10)
            recent = await conn.fetch("""
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
            """)
            
            return {
                "status": "healthy",
                "timestamp": datetime.utcnow().isoformat(),
                "today": dict(today_stats) if today_stats else {},
                "last_hour": dict(last_hour) if last_hour else {},
                "recent_interactions": [
                    {
                        **dict(r),
                        "created_at": r['created_at'].isoformat() if r['created_at'] else None
                    } for r in recent
                ]
            }
            
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        raise HTTPException(status_code=500, detail=f"Metrics retrieval failed: {str(e)}")


# ============================================
# ADMIN PANEL - REAL-TIME WEBSOCKET
# ============================================

@app.websocket("/ws/admin")
async def admin_websocket(websocket: WebSocket):
    """
    WebSocket for admin panel real-time updates
    Streams live metrics and events
    """
    await websocket.accept()
    admin_connections.add(websocket)
    
    logger.info(f"👨‍💼 Admin connected (total: {len(admin_connections)})")
    
    try:
        # Send initial metrics
        if admin_pool:
            metrics = await get_realtime_metrics()
            await websocket.send_json({
                "type": "initial_metrics",
                "data": metrics,
                "timestamp": datetime.utcnow().isoformat()
            })
        
        # Keep connection alive and handle requests
        while True:
            try:
                data = await websocket.receive_json()
                
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                
                elif data.get("type") == "request_metrics":
                    if admin_pool:
                        metrics = await get_realtime_metrics()
                        await websocket.send_json({
                            "type": "metrics_update",
                            "data": metrics,
                            "timestamp": datetime.utcnow().isoformat()
                        })
                    
            except WebSocketDisconnect:
                break
            
    except Exception as e:
        logger.error(f"Admin WebSocket error: {e}")
    
    finally:
        admin_connections.discard(websocket)
        logger.info(f"👨‍💼 Admin disconnected (remaining: {len(admin_connections)})")


async def broadcast_to_admins(message: dict):
    """Broadcast event to all connected admin panels"""
    if not admin_connections:
        return
    
    disconnected = set()
    
    for websocket in admin_connections:
        try:
            await websocket.send_json(message)
        except Exception:
            disconnected.add(websocket)
    
    # Clean up disconnected websockets
    for websocket in disconnected:
        admin_connections.discard(websocket)


async def get_realtime_metrics() -> dict:
    """
    Get real-time metrics for admin panel
    USES SINGLE POOL (NO CACHE) for reliability
    """
    
    if not admin_pool:
        return {
            "status": "database_unavailable",
            "today": {},
            "last_hour": {},
            "recent_interactions": []
        }
    
    try:
        async with admin_pool.acquire() as conn:
            # Today's stats
            today_stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total_queries,
                    COUNT(*) FILTER (WHERE query_success = true) as successful_queries,
                    ROUND(AVG(total_processing_time_ms)) as avg_response_time,
                    COUNT(DISTINCT business_id) as active_businesses,
                    COUNT(*) FILTER (WHERE detected_language = 'sw') as swahili_queries,
                    COUNT(*) FILTER (WHERE detected_language = 'en') as english_queries
                FROM agent_interactions
                WHERE DATE(created_at) = CURRENT_DATE
            """)
            
            # Last hour stats
            last_hour = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as queries_last_hour,
                    ROUND(AVG(total_processing_time_ms)) as avg_time_last_hour
                FROM agent_interactions
                WHERE created_at >= NOW() - INTERVAL '1 hour'
            """)
            
            # Recent interactions
            recent = await conn.fetch("""
                SELECT 
                    original_query,
                    detected_language,
                    query_success,
                    total_processing_time_ms,
                    created_at
                FROM agent_interactions
                ORDER BY created_at DESC
                LIMIT 10
            """)
            
            return {
                "status": "healthy",
                "today": dict(today_stats) if today_stats else {},
                "last_hour": dict(last_hour) if last_hour else {},
                "recent_interactions": [dict(r) for r in recent]
            }
            
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        return {
            "status": "error",
            "error": str(e),
            "today": {},
            "last_hour": {},
            "recent_interactions": []
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")