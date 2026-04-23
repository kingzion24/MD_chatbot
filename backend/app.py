"""
Mali Daftari Backend - FastAPI REST + SSE Server
Stateless architecture: JWT auth via Bearer header, SSE for streaming responses.
"""

import asyncio
import json
import logging
import os
import time
import uuid
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
        'nionyeshe', 'onyesha', 'linganisha', 'angalia', 'toa',
        'nina', 'niko', 'nataka', 'ninahitaji',
        'tafadhali', 'nitumie', 'nipatie', 'naweza', 'unaweza',

        # Business terms
        'mauzo', 'bidhaa', 'bei', 'gharama', 'faida',
        'hifadhi', 'duka', 'mteja', 'wateja',
        'mapato', 'matumizi', 'hesabu', 'taarifa', 'rekodi',
        'orodha', 'stoki', 'akiba',

        # Time expressions — singular and plural forms
        'leo', 'jana', 'kesho', 'wiki', 'mwezi', 'miezi',
        'mwaka', 'miaka', 'siku', 'kila', 'kwanza', 'mwisho',

        # Numbers (uniquely Kiswahili, safe to use as indicators)
        'moja', 'mbili', 'tatu', 'nne', 'tano',
        'saba', 'nane', 'tisa', 'kumi', 'ishirini',
        'mitatu', 'miwili', 'minne', 'mitano',

        # Question words
        'je', 'nini', 'ngapi', 'vipi', 'lini', 'wapi', 'nani',

        # Common connectors / particles
        'ya', 'za', 'wa', 'na', 'kwa', 'au', 'ni',
        'jumla', 'kiasi', 'pesa', 'shilingi',

        # Possessives
        'yangu', 'yako', 'yake', 'zako', 'zangu',

        # Other common
        'inaendeleaje', 'namna', 'zaidi', 'kidogo',
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


def classify_query_intent(
    message: str,
    language: str,
    context: List[Dict] = [],
) -> tuple[bool, str]:
    """Route a message to either the data or conversational pipeline.

    Includes a context-aware override: if the previous assistant turn asked a
    clarifying question (contains '?') and the current reply is short, inherit
    the data_query classification so follow-up answers aren't misrouted.

    Returns:
        (is_data_query, query_type)
    """
    is_data_query = query_router.is_data_query(message, language)

    if not is_data_query and context:
        last_assistant_content = next(
            (m["content"] for m in reversed(context) if m["role"] == "assistant"),
            None,
        )
        if last_assistant_content and "?" in last_assistant_content and len(message.strip()) < 60:
            is_data_query = True
            logger.info("📊 Context override: short reply to assistant question → DATA QUERY")

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
        (response, tool_use_blocks, generated_sqls)
        tool_use_blocks is [] and generated_sqls is [] if Claude answered directly.
        Claude may return multiple tool_use blocks (e.g. one per time period).
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
        return response, [], []

    tool_uses = [block for block in response.content if block.type == "tool_use"]
    generated_sqls = []
    for tu in tool_uses:
        sql = tu.input.get("query", "")
        generated_sqls.append(sql)
        logger.info(f"🔧 Tool requested: {tu.name}")
        if "explanation" in tu.input:
            logger.info(f"📝 Query explanation: {tu.input['explanation']}")

    return response, tool_uses, generated_sqls


def _sanitize_context(context: List[Dict]) -> List[Dict]:
    """Validate and sanitize client-supplied conversation context.

    Security rules applied in order:
    1. Hard cap: keep only the most recent _CONTEXT_MAX_TURNS turns so a
       client cannot inflate token usage or bury the system prompt.
    2. Role allowlist: only "user" and "assistant" are forwarded to the API.
       Any other role (e.g. "system") is dropped — a "system" role message
       from the client could override the server-controlled system prompt.
    3. Content type: only plain strings are accepted. List-valued content
       (raw API objects containing tool_use / tool_result blocks) is either
       collapsed to its text portions or dropped entirely.
    4. Empty messages: stripped after sanitization.
    5. Total word cap: if the sanitized context exceeds Config.CONTEXT_MAX_WORDS,
       the oldest messages are trimmed until it fits.
    """
    ALLOWED_ROLES = {"user", "assistant"}

    # Step 1 — keep only the tail of the history (most recent turns).
    # Multiply by 2 because each turn = 1 user + 1 assistant message.
    context = context[-(Config.CONTEXT_MAX_TURNS * 2):]

    clean: List[Dict] = []
    for msg in context:
        role = msg.get("role", "")
        content = msg.get("content", "")

        # Step 2 — role allowlist.
        if role not in ALLOWED_ROLES:
            logger.warning(f"Context message with disallowed role '{role}' dropped")
            continue

        # Step 3 — normalise content to a plain string.
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            # Drop user messages that are purely tool_result exchanges.
            if role == "user" and all(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            ):
                continue
            # Collapse any remaining list content to text blocks only.
            text = "".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ).strip()
        else:
            continue

        # Step 4 — drop empty messages.
        if not text:
            continue

        clean.append({"role": role, "content": text})

    # Step 5 — total character cap: trim oldest messages first.
    while clean and sum(len(m["content"]) for m in clean) > Config.CONTEXT_MAX_CHARS:
        clean.pop(0)

    return clean


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

    # Sanitize context before any API call to remove orphaned tool_use/
    # tool_result blocks that would cause a 400 from the Anthropic API.
    context = _sanitize_context(context)

    # Detect language outside the try block so it's always available for logging.
    language = detect_language(message)
    logger.info(f"🌍 Detected language: {language.upper()}")

    try:
        logger.info(f"💬 Processing message: {message[:50]}...")

        is_data_query, query_type = classify_query_intent(message, language, context)

        if is_data_query:
            # ── Step 1: non-streaming call to obtain SQL (tool use) ──────────
            first_response, tool_uses, generated_sqls = await generate_sql_with_llm(
                message, business_id, language, context
            )

            if tool_uses:
                # ── Step 2: execute ALL SQL queries against the DB ───────────
                # Claude may request multiple queries (e.g. this month + last month).
                # Every tool_use block must have a matching tool_result in the next
                # message or the Anthropic API will return a 400.
                all_tool_results = []
                generated_sql = "; ".join(generated_sqls)
                for tu, sql in zip(tool_uses, generated_sqls):
                    tool_result, success, err = await execute_business_query(sql, business_id)
                    if success:
                        query_success = True
                    elif error_message is None:
                        error_message = err
                    all_tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": json.dumps(tool_result),
                    })

                # ── Step 3: stream the formatting (second) Claude call ───────
                async with anthropic_client.messages.stream(
                    model=config.ANTHROPIC_MODEL,
                    max_tokens=4096,
                    system=get_system_prompt(language=language, business_id=business_id),
                    messages=[
                        *context,
                        {"role": "user", "content": message},
                        {"role": "assistant", "content": first_response.content},
                        {"role": "user", "content": all_tool_results},
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

            disclaimer = (
                "Ushauri huu umetolewa na AI. Kwa maamuzi makubwa ya biashara, tafadhali wasiliana na mtaalamu."
                if language == "sw"
                else "This guidance is AI-generated. For major business decisions, consult a qualified professional."
            )
            yield f"data: {json.dumps({'type': 'disclaimer', 'text': disclaimer})}\n\n"

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

    session_id = str(uuid.uuid4())
    business_name = await mcp_client.get_business_name(business_id)
    greeting = get_time_aware_greeting(business_name)

    return {
        "session_id": session_id,
        "content": greeting,
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
