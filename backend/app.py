from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import json
import os
from datetime import datetime
from anthropic import AsyncAnthropic
from typing import Dict
import logging
import time
import uuid

from config import Config
from utils.sql_validator import validate_query_complete
from utils.mcp_client import MCPClient
from prompts.system_prompt import get_system_prompt
from translation_service import get_translation_service
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
    description="AI-powered bilingual business assistant for MSME owners"
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

# Initialize Translation Service
try:
    translation_service = get_translation_service()
    logger.info("✅ Translation service initialized")
except Exception as e:
    logger.error(f"❌ Failed to initialize translation service: {e}")
    translation_service = None

# Initialize Query Router
query_router = get_query_router()
logger.info("✅ Query router initialized")

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


async def execute_mcp_tool(sql_query: str, business_id: str) -> Dict:
    """Execute SQL query via MCP server with security validation"""
    try:
        # Validate and secure the query
        secured_query = validate_query_complete(sql_query, business_id)
        
        if not secured_query:
            logger.warning(f"⚠️ Invalid SQL query rejected: {sql_query[:50]}...")
            return {
                "success": False,
                "error": "Invalid SQL query - security validation failed",
                "results": [],
                "row_count": 0
            }
        
        logger.info(f"🔍 Executing secured query for business {business_id[:8]}...")
        logger.debug(f"SQL: {secured_query}")
        
        # Execute via MCP
        result = await mcp_client.execute_query(secured_query)
        
        row_count = len(result.get('rows', []))
        logger.info(f"✅ Query returned {row_count} rows")
        
        return {
            "success": True,
            "results": result.get('rows', []),
            "row_count": row_count,
            "columns": result.get('columns', [])
        }
        
    except Exception as e:
        logger.error(f"❌ MCP execution error: {str(e)}")
        return {
            "success": False,
            "error": f"Database query failed: {str(e)}",
            "results": [],
            "row_count": 0
        }


async def log_interaction_to_mcp(
    business_id: str,
    session_id: str,
    original_query: str,
    detected_language: str,
    translated_query: str,
    query_type: str,
    generated_sql: str,
    query_success: bool,
    response_text: str,
    processing_time_ms: int,
    error_message: str = None
):
    """Log interaction to MCP server for admin monitoring"""
    try:
        # Call MCP server's logging endpoint
        import httpx
        
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{config.MCP_SERVER_URL}/log-interaction",
                json={
                    "business_id": business_id,
                    "session_id": session_id,
                    "original_query": original_query,
                    "detected_language": detected_language,
                    "translated_query": translated_query,
                    "query_type": query_type,
                    "generated_sql": generated_sql,
                    "query_success": query_success,
                    "response_text": response_text,
                    "response_language": detected_language,
                    "total_processing_time_ms": processing_time_ms,
                    "error_message": error_message
                },
                timeout=5.0
            )
            logger.debug(f"📝 Interaction logged to MCP server")
    except Exception as e:
        logger.warning(f"⚠️ Failed to log interaction to MCP: {e}")


async def process_message_with_translation(
    message: str, 
    business_id: str, 
    user_id: str,
    session_id: str
) -> tuple[str, str]:
    """
    Process user message with bilingual support and full logging
    
    Returns:
        (response_text, detected_language)
    """
    
    start_time = time.time()
    original_query = message
    detected_language = "en"
    translated_query = None
    query_type = "conversational"
    generated_sql = None
    query_success = False
    error_message = None
    
    try:
        logger.info(f"💬 Processing message from user {user_id[:8]}...: {message[:50]}...")
        
        # STEP 1: Detect language
        if translation_service:
            detected_language = translation_service.detect_language(message)
            logger.info(f"🌍 Detected language: {detected_language.upper()}")
            
            # STEP 2: Translate to English if needed
            if detected_language == "sw":
                message_english = translation_service.translate_sw_to_en(message)
                translated_query = message_english
                logger.info(f"🔄 Translated: '{message[:30]}...' → '{message_english[:30]}...'")
            else:
                message_english = message
        else:
            # Fallback if translation service not available
            detected_language = "en"
            message_english = message
        
        # STEP 3: Check if this is a data query or conversational query
        is_data_query = query_router.is_data_query(message_english, detected_language)
        query_type = "data_query" if is_data_query else "conversational"
        
        if is_data_query:
            logger.info("📊 Classified as DATA QUERY - will use database if needed")
        else:
            logger.info("💬 Classified as CONVERSATIONAL - general advice")
        
        # STEP 4: Send to Claude with appropriate system prompt and tools
        response = await anthropic_client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=4096,
            system=get_system_prompt(business_id, detected_language),
            messages=[
                {"role": "user", "content": message_english}
            ],
            tools=MCP_TOOLS if is_data_query else [],
        )
        
        logger.info(f"🤖 Claude responded with stop_reason: {response.stop_reason}")
        
        # STEP 5: Handle tool use (database queries)
        if response.stop_reason == "tool_use":
            tool_use = next(block for block in response.content if block.type == "tool_use")
            tool_name = tool_use.name
            tool_input = tool_use.input
            
            logger.info(f"🔧 Tool requested: {tool_name}")
            generated_sql = tool_input.get('query', '')
            
            if 'explanation' in tool_input:
                logger.info(f"📝 Query explanation: {tool_input['explanation']}")
            
            # Execute database query
            tool_result = await execute_mcp_tool(
                tool_input['query'],
                business_id
            )
            
            query_success = tool_result.get('success', False)
            
            if not query_success:
                error_message = tool_result.get('error', 'Unknown error')
                logger.warning(f"⚠️ Query failed: {error_message}")
            else:
                logger.info(f"✅ Query successful: {tool_result.get('row_count', 0)} rows")
            
            # Send tool result back to Claude for final response
            final_response = await anthropic_client.messages.create(
                model=config.ANTHROPIC_MODEL,
                max_tokens=4096,
                system=get_system_prompt(business_id, detected_language),
                messages=[
                    {"role": "user", "content": message_english},
                    {"role": "assistant", "content": response.content},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use.id,
                                "content": json.dumps(tool_result),
                            }
                        ],
                    }
                ],
                tools=MCP_TOOLS,
            )
            
            text_content = next(
                (block.text for block in final_response.content if hasattr(block, "text")),
                "I couldn't generate a response."
            )
        else:
            # No tools needed - direct response
            query_success = True  # Conversational queries are always "successful"
            text_content = next(
                (block.text for block in response.content if hasattr(block, "text")),
                "I couldn't generate a response."
            )
        
        # STEP 6: Translate response back to Kiswahili if needed
        if translation_service and detected_language == "sw":
            final_response_text = translation_service.translate_en_to_sw(text_content)
            logger.info(f"🔄 Response translated back to Kiswahili")
        else:
            final_response_text = text_content
        
        # Calculate processing time
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        logger.info(f"✅ Response generated: {len(final_response_text)} chars in {processing_time_ms}ms")
        
        # STEP 7: Log interaction to MCP server for admin monitoring
        await log_interaction_to_mcp(
            business_id=business_id,
            session_id=session_id,
            original_query=original_query,
            detected_language=detected_language,
            translated_query=translated_query,
            query_type=query_type,
            generated_sql=generated_sql,
            query_success=query_success,
            response_text=final_response_text,
            processing_time_ms=processing_time_ms,
            error_message=error_message
        )
        
        return final_response_text, detected_language
        
    except Exception as e:
        logger.error(f"❌ Error processing message: {str(e)}", exc_info=True)
        
        # Calculate processing time even for errors
        processing_time_ms = int((time.time() - start_time) * 1000)
        error_message = str(e)
        
        # Log failed interaction
        await log_interaction_to_mcp(
            business_id=business_id,
            session_id=session_id,
            original_query=original_query,
            detected_language=detected_language,
            translated_query=translated_query,
            query_type=query_type,
            generated_sql=generated_sql,
            query_success=False,
            response_text="Error occurred",
            processing_time_ms=processing_time_ms,
            error_message=error_message
        )
        
        # Return error in user's language
        if translation_service and detected_language == "sw":
            error_msg = "Samahani, nimekutana na hitilafu. Tafadhali jaribu tena."
        else:
            error_msg = "I apologize, but I encountered an error. Please try again."
        
        return error_msg, detected_language


@app.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    """WebSocket endpoint for chat"""
    await websocket.accept()
    
    business_id = None
    user_id = None
    session_id = str(uuid.uuid4())  # Generate session ID
    
    try:
        # Initialize connection
        init_data = await websocket.receive_json()
        business_id = init_data.get('business_id')
        user_id = init_data.get('user_id')
        
        if not business_id or not user_id:
            await websocket.send_json({
                "type": "error",
                "message": "business_id and user_id are required"
            })
            return
        
        logger.info(f"🔌 WebSocket connected: user={user_id[:8]}..., business={business_id[:8]}..., session={session_id[:8]}...")
        
        # Send welcome message
        welcome_msg = "Hello! I'm Karaba, your Mali Daftari assistant 💼"
        if translation_service:
            welcome_msg += " I can communicate in both English and Kiswahili!"
        
        await websocket.send_json({
            "type": "connected",
            "message": welcome_msg,
            "session_id": session_id,
            "supports_swahili": translation_service is not None,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Message loop
        while True:
            data = await websocket.receive_json()
            message = data.get('message', '').strip()
            
            if not message:
                continue
            
            logger.info(f"📨 Message received: {message[:100]}...")
            
            # Process message with translation and logging
            response_text, detected_language = await process_message_with_translation(
                message, business_id, user_id, session_id
            )
            
            # Send response back to user
            await websocket.send_json({
                "type": "message",
                "content": response_text,
                "language": detected_language,
                "timestamp": datetime.utcnow().isoformat()
            })
            
    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket disconnected: user={user_id[:8] if user_id else 'unknown'}, session={session_id[:8]}")
    except Exception as e:
        logger.error(f"❌ WebSocket error: {str(e)}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except:
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
            "translation": "enabled" if translation_service else "disabled",
            "ai_provider": "Anthropic Claude",
            "model": config.ANTHROPIC_MODEL,
            "environment": config.ENVIRONMENT,
            "features": {
                "bilingual": translation_service is not None,
                "languages": ["English", "Kiswahili"] if translation_service else ["English"]
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
            "bilingual_support": translation_service is not None,
            "languages": ["English", "Kiswahili"] if translation_service else ["English"],
            "intelligent_routing": True,
            "performance_monitoring": True
        },
        "endpoints": {
            "websocket": "/ws/chat",
            "health": "/health",
            "docs": "/docs"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")