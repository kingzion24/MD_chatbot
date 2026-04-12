"""
Mali Daftari Backend - FastAPI WebSocket Server
Uses Claude's native multilingual capabilities for bilingual support
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

import asyncio
import json
import jwt
import os
from datetime import datetime
from anthropic import AsyncAnthropic
from typing import Dict, Literal
import logging
import time
import uuid

from config import Config
from utils.greetings import get_time_aware_greeting
from utils.sql_validator import validate_query_complete
from utils.mcp_client import MCPClient
from prompts.system_prompt import get_system_prompt
from query_router import get_query_router

# Logging setup
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO').upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(
    title="Mali Daftari Business Assistant API",
    version="2.0.0",
    description="AI-powered bilingual business assistant for MSME owners (using Claude's native multilingual capabilities)"
)

# Validate config on startup
try:
    Config.validate()
    logger.info("✅ Configuration validated successfully")
except ValueError as e:
    logger.error(f"❌ Configuration error: {str(e)}")
    raise

# Initialize clients
config = Config()

# Initialize Anthropic Claude
anthropic_client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
logger.info(f"✅ Using Anthropic Claude: {config.ANTHROPIC_MODEL}")

# Initialize MCP Client
mcp_client = MCPClient(config.MCP_SERVER_URL)
logger.info(f"✅ MCP Server configured: {config.MCP_SERVER_URL}")

# Initialize Query Router
query_router = get_query_router()
logger.info("✅ Query router initialized")
logger.info("✅ Using Claude's native multilingual capabilities (no translation models needed)")

# MCP Tools Definition
MCP_TOOLS = [{
    "name": "query_business_data",
    "description": """Query business data from PostgreSQL database. 
    Available tables: inventories, products, sales, expenses.
    Use this tool when the user asks about their specific business data (sales, inventory, expenses).
    Do NOT use this for general business advice questions.
    
    CRITICAL: Execute this tool silently - users should NEVER see the SQL query, only the results.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "SQL SELECT query to execute (read-only). Always use proper JOINs. Include business_id filter."
            },
            "explanation": {
                "type": "string",
                "description": "Brief explanation of what this query does (for logging purposes only, NOT shown to user)"
            }
        },
        "required": ["query"]
    }
}]


def detect_language(text: str) -> Literal["sw", "en"]:
    """
    Simple keyword-based language detection
    No ML models needed - just pattern matching
    
    Args:
        text: Input text to analyze
        
    Returns:
        "sw" for Kiswahili, "en" for English
    """
    swahili_indicators = [
        # Greetings
        'habari', 'mambo', 'hujambo', 'shikamoo', 'vipi', 'poa',
        
        # Common verbs
        'nionyeshe', 'nina', 'niko', 'nataka', 'ninahitaji',
        'tafadhali', 'nitumie', 'nipatie', 'naweza', 'unaweza',
        
        # Business terms
        'mauzo', 'bidhaa', 'bei', 'gharama', 'faida',
        'hifadhi', 'duka', 'mteja', 'wateja',
        
        # Time expressions
        'leo', 'jana', 'kesho', 'wiki', 'mwezi', 'mwaka',
        
        # Question words
        'je', 'nini', 'ngapi', 'vipi', 'lini', 'wapi', 'nani',
        
        # Common words
        'ya', 'za', 'wa', 'na', 'kwa', 'au', 'ni',
        'jumla', 'kiasi', 'pesa', 'shilingi',
        
        # Possessives
        'yangu', 'yako', 'yake', 'zako', 'zangu',
        
        # Other common
        'inaendeleaje', 'namna', 'siku', 'kila'
    ]
    
    text_lower = text.lower()
    
    # Count Kiswahili indicators
    sw_count = sum(1 for indicator in swahili_indicators if indicator in text_lower)
    
    # If 2 or more Kiswahili words found, classify as Kiswahili
    if sw_count >= 2:
        logger.debug(f"Detected Kiswahili ({sw_count} indicators found)")
        return "sw"
    else:
        logger.debug(f"Detected English ({sw_count} Kiswahili indicators)")
        return "en"


async def execute_mcp_tool(sql_query: str, business_id: str) -> Dict:
    """Execute SQL query via MCP server with security validation"""
    try:
        # Validate and secure the query — raises ValueError if rejected.
        # business_id is NOT passed to the validator; instead the validator
        # injects the $1 placeholder and the value is bound here as a parameter.
        secured_query = validate_query_complete(sql_query)

        logger.info(f"🔍 Executing secured query for business {business_id[:8]}...")
        logger.debug(f"SQL: {secured_query}")

        # Execute via MCP — business_id is bound as the first positional
        # parameter ($1) by asyncpg, never interpolated into the SQL string.
        # It is also forwarded in the X-Business-ID header so the MCP server's
        # rate limiter applies a per-tenant quota rather than a shared one.
        result = await mcp_client.execute_query(
            secured_query, params=[business_id], business_id=business_id
        )

        row_count = len(result.get('rows', []))
        logger.info(f"✅ Query returned {row_count} rows")

        return {
            "success": True,
            "results": result.get('rows', []),
            "row_count": row_count,
            "columns": result.get('columns', [])
        }

    except ValueError as exc:
        logger.warning(f"⚠️ Invalid SQL query rejected: {exc}")
        return {
            "success": False,
            "error": "Invalid SQL query - security validation failed",
            "results": [],
            "row_count": 0
        }

    except Exception as e:
        logger.error(f"❌ MCP execution error: {str(e)}")
        return {
            "success": False,
            "error": f"Database query failed: {str(e)}",
            "results": [],
            "row_count": 0
        }


async def log_interaction(
    business_id: str,
    session_id: str,
    original_query: str,
    language: str,
    query_type: str,
    generated_sql: str,
    query_success: bool,
    response_text: str,
    processing_time_ms: int,
    error_message: str = None
):
    """Log interaction to MCP server for admin monitoring.

    Runs as a fire-and-forget background task via asyncio.create_task(), so
    exceptions must be caught here — an unhandled exception in a Task silently
    drops the result and can log spurious 'Task exception was never retrieved'
    warnings to the event loop.
    """
    try:
        await mcp_client.log_interaction({
            "business_id": business_id,
            "session_id": session_id,
            "original_query": original_query,
            "detected_language": language,
            "query_type": query_type,
            "generated_sql": generated_sql,
            "query_success": query_success,
            "response_text": response_text,
            "response_language": language,
            "total_processing_time_ms": processing_time_ms,
            "error_message": error_message
        })
        logger.debug("📝 Interaction logged to MCP server")
    except Exception as e:
        logger.warning(f"Background logging failed: {e}")


def classify_query_intent(message: str, language: str) -> tuple[bool, str]:
    """Route a message to either the data or conversational pipeline.

    Returns:
        (is_data_query, query_type)
    """
    is_data_query = query_router.is_data_query(message, language)
    query_type = "data_query" if is_data_query else "conversational"
    if is_data_query:
        logger.info("📊 Classified as DATA QUERY - will use database if needed")
    else:
        logger.info("💬 Classified as CONVERSATIONAL - general advice")
    return is_data_query, query_type


async def handle_conversational_query(message: str, business_id: str, language: str) -> str:
    """Call Claude without tools for a general/advice response.

    Returns:
        Natural language response text.
    """
    response = await anthropic_client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=4096,
        system=get_system_prompt(language=language, business_id=business_id),
        messages=[{"role": "user", "content": message}],
        tools=[],
    )
    return next(
        (block.text for block in response.content if hasattr(block, "text")),
        "I couldn't generate a response."
    )


async def generate_sql_with_llm(message: str, business_id: str, language: str) -> tuple:
    """First Claude call for data queries: let Claude decide if it needs to query the DB.

    Returns:
        (response, tool_use_block, generated_sql)
        tool_use_block and generated_sql are None if Claude answered directly.
    """
    response = await anthropic_client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=4096,
        system=get_system_prompt(language=language, business_id=business_id),
        messages=[{"role": "user", "content": message}],
        tools=MCP_TOOLS,
    )
    logger.info(f"🤖 Claude responded with stop_reason: {response.stop_reason}")

    if response.stop_reason != "tool_use":
        return response, None, None

    tool_use = next(block for block in response.content if block.type == "tool_use")
    generated_sql = tool_use.input.get("query", "")
    logger.info(f"🔧 Tool requested: {tool_use.name}")
    if "explanation" in tool_use.input:
        logger.info(f"📝 Query explanation: {tool_use.input['explanation']}")

    return response, tool_use, generated_sql


async def execute_business_query(sql_query: str, business_id: str) -> tuple[Dict, bool, str]:
    """Validate and run a SQL query via the MCP client.

    Returns:
        (tool_result, success, error_message)
        Never raises — surfaces errors as data so the orchestrator can continue.
    """
    tool_result = await execute_mcp_tool(sql_query, business_id)
    success = tool_result.get("success", False)
    error_message = None

    if not success:
        error_message = tool_result.get("error", "Unknown error")
        logger.warning(f"⚠️ Query failed: {error_message}")
    else:
        logger.info(f"✅ Query successful: {tool_result.get('row_count', 0)} rows")

    return tool_result, success, error_message


async def format_data_response(
    message: str,
    business_id: str,
    language: str,
    first_response,
    tool_use,
    tool_result: Dict,
) -> str:
    """Second Claude call: turn raw DB rows into a natural language answer.

    Returns:
        Formatted response text in the user's language.
    """
    final_response = await anthropic_client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=4096,
        system=get_system_prompt(language=language, business_id=business_id),
        messages=[
            {"role": "user", "content": message},
            {"role": "assistant", "content": first_response.content},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": json.dumps(tool_result),
                    }
                ],
            },
        ],
        tools=MCP_TOOLS,
    )
    return next(
        (block.text for block in final_response.content if hasattr(block, "text")),
        "I couldn't generate a response."
    )


async def process_message(
    message: str,
    business_id: str,
    user_id: str,
    session_id: str,
) -> tuple[str, str]:
    """High-level orchestrator: detect → route → query → format → log.

    Returns:
        (response_text, detected_language)
    """
    start_time = time.time()
    generated_sql = None
    query_type = "conversational"
    query_success = False
    error_message = None

    try:
        logger.info(f"💬 Processing message from user {user_id[:8]}...: {message[:50]}...")

        language = detect_language(message)
        logger.info(f"🌍 Detected language: {language.upper()}")

        is_data_query, query_type = classify_query_intent(message, language)

        if is_data_query:
            first_response, tool_use, generated_sql = await generate_sql_with_llm(
                message, business_id, language
            )
            if tool_use is not None:
                tool_result, query_success, error_message = await execute_business_query(
                    generated_sql, business_id
                )
                response_text = await format_data_response(
                    message, business_id, language, first_response, tool_use, tool_result
                )
            else:
                query_success = True
                response_text = next(
                    (block.text for block in first_response.content if hasattr(block, "text")),
                    "I couldn't generate a response."
                )
        else:
            query_success = True
            response_text = await handle_conversational_query(message, business_id, language)

        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.info(f"✅ Response in {language.upper()}: {len(response_text)} chars in {processing_time_ms}ms")

        asyncio.create_task(log_interaction(
            business_id=business_id,
            session_id=session_id,
            original_query=message,
            language=language,
            query_type=query_type,
            generated_sql=generated_sql,
            query_success=query_success,
            response_text=response_text,
            processing_time_ms=processing_time_ms,
        ))

        return response_text, language

    except Exception as e:
        logger.error(f"❌ Error processing message: {str(e)}", exc_info=True)
        processing_time_ms = int((time.time() - start_time) * 1000)
        language = detect_language(message)

        asyncio.create_task(log_interaction(
            business_id=business_id,
            session_id=session_id,
            original_query=message,
            language=language,
            query_type=query_type,
            generated_sql=generated_sql,
            query_success=False,
            response_text="Error occurred",
            processing_time_ms=processing_time_ms,
            error_message=str(e),
        ))

        error_msg = (
            "Samahani, nimekutana na hitilafu. Tafadhali jaribu tena."
            if language == "sw"
            else "I apologize, but I encountered an error. Please try again."
        )
        return error_msg, language


@app.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    """WebSocket endpoint for chat — requires JWT + owner verification on handshake."""
    await websocket.accept()

    user_id = None
    business_id = None
    session_id = None

    try:
        # ── Phase 1: read handshake payload ──────────────────────────────────
        init_data = await websocket.receive_json()
        token = init_data.get("token")
        business_id = init_data.get("business_id")

        if not token or not business_id:
            logger.warning("WebSocket rejected: missing token or business_id")
            await websocket.close(code=1008)
            return

        # ── Phase 2: decode & verify JWT ─────────────────────────────────────
        try:
            claims = jwt.decode(
                token,
                config.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
            user_id = claims.get("sub")
            if not user_id:
                raise jwt.InvalidTokenError("Missing 'sub' claim")
        except jwt.PyJWTError as exc:
            logger.warning(f"WebSocket rejected: invalid JWT — {exc}")
            await websocket.close(code=1008)
            return

        # ── Phase 3: check business ownership ────────────────────────────────
        is_owner = await mcp_client.verify_business_owner(user_id, business_id)
        if not is_owner:
            logger.warning(
                f"WebSocket rejected: user={user_id[:8]}... is not owner of "
                f"business={business_id[:8]}..."
            )
            await websocket.close(code=1008)
            return

        # ── Auth passed — start session ───────────────────────────────────────
        session_id = str(uuid.uuid4())
        logger.info(
            f"🔌 WebSocket connected: user={user_id[:8]}..., "
            f"business={business_id[:8]}..., session={session_id[:8]}..."
        )

        # ── Frame 1: silent session handshake (not shown to user) ───────────
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat(),
        })

        # ── Frame 2: personalised greeting ────────────────────────────────────
        # Kick off the business-name DB lookup and the typing delay in parallel
        # so the greeting arrives exactly 1.2 s after the connected frame
        # regardless of how fast the database responds.
        business_name_task = asyncio.create_task(
            mcp_client.get_business_name(business_id)
        )
        await asyncio.sleep(1.2)
        business_name = await business_name_task

        greeting = get_time_aware_greeting(business_name)
        await websocket.send_json({
            "type": "greeting",
            "content": greeting,
            "language": "sw",
            "timestamp": datetime.utcnow().isoformat(),
        })

        # ── Message loop ──────────────────────────────────────────────────────
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "").strip()

            if not message:
                continue

            logger.info(f"📨 Message received: {message[:100]}...")

            response_text, detected_language = await process_message(
                message, business_id, user_id, session_id
            )

            await websocket.send_json({
                "type": "message",
                "content": response_text,
                "language": detected_language,
                "timestamp": datetime.utcnow().isoformat(),
            })

    except WebSocketDisconnect:
        logger.info(
            f"🔌 WebSocket disconnected: user={user_id[:8] if user_id else 'unknown'}, "
            f"session={session_id[:8] if session_id else 'none'}"
        )
    except Exception as e:
        logger.error(f"❌ WebSocket error: {str(e)}", exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        mcp_status = await mcp_client.health_check()
        
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "mcp_server": "connected" if mcp_status else "disconnected",
            "translation": "native_multilingual",
            "ai_provider": "Anthropic Claude",
            "model": config.ANTHROPIC_MODEL,
            "environment": config.ENVIRONMENT,
            "features": {
                "bilingual": True,
                "languages": ["English", "Kiswahili"],
                "translation_method": "Claude native (no external models)"
            }
        }
    except Exception as e:
        logger.error(f"❌ Health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Mali Daftari Business Assistant",
        "version": "2.0.0",
        "status": "running",
        "ai_provider": "Anthropic Claude",
        "model": config.ANTHROPIC_MODEL,
        "features": {
            "bilingual_support": True,
            "languages": ["English", "Kiswahili"],
            "translation_method": "Claude native multilingual",
            "intelligent_routing": True,
            "performance_monitoring": True
        },
        "endpoints": {
            "websocket": "/ws/chat",
            "health": "/health",
            "docs": "/docs"
        }
    }


@app.on_event("shutdown")
async def shutdown():
    """Close the persistent MCP HTTP client on server shutdown"""
    await mcp_client.close()
    logger.info("✅ MCP client closed")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")