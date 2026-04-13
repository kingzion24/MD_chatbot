"""
Mali Daftari Backend - FastAPI REST + SSE Server
Stateless architecture: JWT auth via Bearer header, SSE for streaming responses.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import AsyncGenerator, Dict, List, Literal

import jwt
from anthropic import AsyncAnthropic
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import Config
from prompts.system_prompt import get_system_prompt
from query_router import get_query_router
from utils.greetings import get_time_aware_greeting
from utils.mcp_client import MCPClient
from utils.sql_validator import validate_query_complete

# ── Logging ──────────────────────────────────────────────────────────────────

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

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Mali Daftari Business Assistant API",
    version="3.0.0",
    description="AI-powered bilingual business assistant for MSME owners (REST + SSE)"
)

try:
    Config.validate()
    logger.info("✅ Configuration validated successfully")
except ValueError as e:
    logger.error(f"❌ Configuration error: {str(e)}")
    raise

config = Config()

anthropic_client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
logger.info(f"✅ Using Anthropic Claude: {config.ANTHROPIC_MODEL}")

mcp_client = MCPClient(config.MCP_SERVER_URL)
logger.info(f"✅ MCP Server configured: {config.MCP_SERVER_URL}")

query_router = get_query_router()
logger.info("✅ Query router initialized")

# ── MCP Tool Schema ───────────────────────────────────────────────────────────

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

# ── Pydantic Models ───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    business_id: str
    session_id: str
    message: str
    context: List[Dict] = []

# ── Auth Dependency ───────────────────────────────────────────────────────────

async def verify_token(authorization: str = Header(...)) -> str:
    """Validate Supabase JWT from Authorization: Bearer header.

    Returns:
        user_id (str) extracted from the token's 'sub' claim.

    Raises:
        HTTPException 401 on any auth failure.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    token = authorization.removeprefix("Bearer ")
    try:
        claims = jwt.decode(
            token,
            config.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
        user_id = claims.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token missing 'sub' claim")
        return user_id
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

# ── Core Pipeline (unchanged) ─────────────────────────────────────────────────

def detect_language(text: str) -> Literal["sw", "en"]:
    """
    Simple keyword-based language detection.
    No ML models needed - just pattern matching.

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
    sw_count = sum(1 for indicator in swahili_indicators if indicator in text_lower)

    if sw_count >= 2:
        logger.debug(f"Detected Kiswahili ({sw_count} indicators found)")
        return "sw"
    else:
        logger.debug(f"Detected English ({sw_count} Kiswahili indicators)")
        return "en"


async def execute_mcp_tool(sql_query: str, business_id: str) -> Dict:
    """Execute SQL query via MCP server with security validation."""
    try:
        secured_query = validate_query_complete(sql_query)

        logger.info(f"🔍 Executing secured query for business {business_id[:8]}...")
        logger.debug(f"SQL: {secured_query}")

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

    Fire-and-forget via asyncio.create_task() — exceptions are caught here
    to avoid spurious 'Task exception was never retrieved' warnings.
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


async def execute_business_query(sql_query: str, business_id: str) -> tuple[Dict, bool, str]:
    """Validate and run a SQL query via the MCP client.

    Returns:
        (tool_result, success, error_message)
        Never raises — surfaces errors as data so the caller can continue.
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

# ── Transport Layer ───────────────────────────────────────────────────────────

async def generate_sql_with_llm(
    message: str,
    business_id: str,
    language: str,
    context: List[Dict],
) -> tuple:
    """First Claude call for data queries: let Claude decide if it needs the DB.

    Includes conversation context so Claude has prior turn history.

    Returns:
        (response, tool_use_block, generated_sql)
        tool_use_block and generated_sql are None if Claude answered directly.
    """
    response = await anthropic_client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=4096,
        system=get_system_prompt(language=language, business_id=business_id),
        messages=[*context, {"role": "user", "content": message}],
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


async def generate_response(
    message: str,
    business_id: str,
    user_id: str,
    session_id: str,
    context: List[Dict],
) -> AsyncGenerator[str, None]:
    """SSE streaming generator: orchestrates the full pipeline and streams
    Claude's response chunk-by-chunk.

    Yields SSE-formatted strings:
        data: {"chunk": "<text>"}\\n\\n  — for each text delta
        data: {"type": "done"}\\n\\n     — on success
        data: {"type": "done", "error": true}\\n\\n  — on failure

    Logging is fired as a background task in the finally block so it always
    runs regardless of client disconnect or exceptions.
    """
    start_time = time.time()
    generated_sql = None
    query_type = "conversational"
    query_success = False
    error_message = None
    full_response: List[str] = []

    # Detect language outside the try block so it's always available for logging.
    language = detect_language(message)
    logger.info(f"🌍 Detected language: {language.upper()}")

    try:
        logger.info(f"💬 Processing message: {message[:50]}...")

        is_data_query, query_type = classify_query_intent(message, language)

        if is_data_query:
            # ── Step 1: non-streaming call to obtain SQL (tool use) ──────────
            first_response, tool_use, generated_sql = await generate_sql_with_llm(
                message, business_id, language, context
            )

            if tool_use is not None:
                # ── Step 2: execute SQL against the DB ───────────────────────
                tool_result, query_success, error_message = await execute_business_query(
                    generated_sql, business_id
                )

                # ── Step 3: stream the formatting (second) Claude call ───────
                async with anthropic_client.messages.stream(
                    model=config.ANTHROPIC_MODEL,
                    max_tokens=4096,
                    system=get_system_prompt(language=language, business_id=business_id),
                    messages=[
                        *context,
                        {"role": "user", "content": message},
                        {"role": "assistant", "content": first_response.content},
                        {
                            "role": "user",
                            "content": [{
                                "type": "tool_result",
                                "tool_use_id": tool_use.id,
                                "content": json.dumps(tool_result),
                            }],
                        },
                    ],
                    tools=MCP_TOOLS,
                ) as stream:
                    async for chunk in stream.text_stream:
                        full_response.append(chunk)
                        yield f"data: {json.dumps({'chunk': chunk})}\n\n"

            else:
                # Claude answered without querying the DB (e.g. data not needed).
                query_success = True
                text = next(
                    (block.text for block in first_response.content if hasattr(block, "text")),
                    "",
                )
                full_response.append(text)
                yield f"data: {json.dumps({'chunk': text})}\n\n"

        else:
            # ── Conversational: stream Claude response directly ───────────────
            query_success = True
            async with anthropic_client.messages.stream(
                model=config.ANTHROPIC_MODEL,
                max_tokens=4096,
                system=get_system_prompt(language=language, business_id=business_id),
                messages=[*context, {"role": "user", "content": message}],
                tools=[],
            ) as stream:
                async for chunk in stream.text_stream:
                    full_response.append(chunk)
                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"

        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"✅ Stream complete — {len(''.join(full_response))} chars "
            f"in {processing_time_ms}ms"
        )
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except Exception as e:
        logger.error(f"❌ Error in generate_response: {e}", exc_info=True)
        error_message = str(e)
        err_text = (
            "Samahani, nimekutana na hitilafu. Tafadhali jaribu tena."
            if language == "sw"
            else "I apologize, but I encountered an error. Please try again."
        )
        full_response.append(err_text)
        yield f"data: {json.dumps({'chunk': err_text})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'error': True})}\n\n"

    finally:
        processing_time_ms = int((time.time() - start_time) * 1000)
        asyncio.create_task(log_interaction(
            business_id=business_id,
            session_id=session_id,
            original_query=message,
            language=language,
            query_type=query_type,
            generated_sql=generated_sql,
            query_success=query_success,
            response_text="".join(full_response),
            processing_time_ms=processing_time_ms,
            error_message=error_message,
        ))

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/chat/greeting")
async def get_greeting(
    business_id: str = Query(..., description="Business UUID"),
    user_id: str = Depends(verify_token),
):
    """Return a personalised, time-aware Swahili greeting for the business owner.

    The client calls this once on session open, before any chat messages.
    Auth: Authorization: Bearer <supabase-jwt>
    """
    is_owner = await mcp_client.verify_business_owner(user_id, business_id)
    if not is_owner:
        raise HTTPException(status_code=403, detail="Access denied")

    business_name = await mcp_client.get_business_name(business_id)
    greeting = get_time_aware_greeting(business_name)

    return {
        "greeting": greeting,
        "language": "sw",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/chat/message")
async def chat_message(
    request: ChatRequest,
    user_id: str = Depends(verify_token),
):
    """Process a chat message and stream the response via Server-Sent Events.

    Auth: Authorization: Bearer <supabase-jwt>
    Body: { business_id, session_id, message, context }

    SSE events:
        data: {"chunk": "..."}            — text delta (one or more)
        data: {"type": "done"}            — stream complete
        data: {"type": "done", "error": true}  — error occurred
    """
    is_owner = await mcp_client.verify_business_owner(user_id, request.business_id)
    if not is_owner:
        raise HTTPException(status_code=403, detail="Access denied")

    return StreamingResponse(
        generate_response(
            message=request.message,
            business_id=request.business_id,
            user_id=user_id,
            session_id=request.session_id,
            context=request.context,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable Nginx buffering for SSE
        },
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        mcp_status = await mcp_client.health_check()
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "mcp_server": "connected" if mcp_status else "disconnected",
            "ai_provider": "Anthropic Claude",
            "model": config.ANTHROPIC_MODEL,
            "environment": config.ENVIRONMENT,
            "features": {
                "bilingual": True,
                "languages": ["English", "Kiswahili"],
                "transport": "REST + SSE",
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
    """Root endpoint."""
    return {
        "service": "Mali Daftari Business Assistant",
        "version": "3.0.0",
        "status": "running",
        "ai_provider": "Anthropic Claude",
        "model": config.ANTHROPIC_MODEL,
        "features": {
            "bilingual_support": True,
            "languages": ["English", "Kiswahili"],
            "transport": "REST + SSE (stateless)",
            "intelligent_routing": True,
            "performance_monitoring": True,
        },
        "endpoints": {
            "greeting": "GET /chat/greeting?business_id=<uuid>",
            "message":  "POST /chat/message",
            "health":   "GET /health",
            "docs":     "GET /docs",
        }
    }


@app.on_event("shutdown")
async def shutdown():
    """Close the persistent MCP HTTP client on server shutdown."""
    await mcp_client.close()
    logger.info("✅ MCP client closed")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
