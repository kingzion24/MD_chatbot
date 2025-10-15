from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import json
import os
from datetime import datetime
from anthropic import AsyncAnthropic
from typing import Dict
import logging

from config import Config
from utils.sql_validator import validate_and_secure_sql
from utils.mcp_client import MCPClient
from prompts.system_prompt import get_system_prompt

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
    version="1.0.0",
    description="AI-powered business assistant for MSME owners"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

# MCP Tools Definition (Anthropic format)
MCP_TOOLS = [{
    "name": "query_business_data",
    "description": """Query business data from PostgreSQL database. 
    Available tables: inventories, products, sales, expenses.
    Use this tool ONLY when the user asks about their specific business data.
    Do NOT use this for general business advice questions.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "SQL SELECT query to execute (read-only). Always use proper JOINs."
            },
            "explanation": {
                "type": "string",
                "description": "Brief explanation of what this query does"
            }
        },
        "required": ["query"]
    }
}]


async def execute_mcp_tool(sql_query: str, business_id: str) -> Dict:
    """Execute SQL query via MCP server with security"""
    try:
        # Validate and secure SQL
        secured_query = validate_and_secure_sql(sql_query, business_id)
        if not secured_query:
            logger.warning(f"⚠️ Invalid SQL query rejected: {sql_query}")
            return {"error": "Invalid SQL query - only SELECT statements allowed", "results": []}
        
        logger.info(f"🔍 Executing query for business {business_id[:8]}...")
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
            "error": f"Database query failed: {str(e)}",
            "results": []
        }


async def process_message(message: str, business_id: str, user_id: str) -> str:
    """Process user message with Anthropic Claude"""
    
    try:
        logger.info(f"💬 Processing message from user {user_id[:8]}...: {message[:50]}...")
        
        # STEP 1: Send message to Claude with tools available
        response = await anthropic_client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=4096,
            system=get_system_prompt(business_id),
            messages=[
                {"role": "user", "content": message}
            ],
            tools=MCP_TOOLS,
        )
        
        logger.info(f"🤖 Claude responded with stop_reason: {response.stop_reason}")
        
        # STEP 2: Check if Claude wants to use tools (query database)
        if response.stop_reason == "tool_use":
            # Find the tool use block
            tool_use = next(block for block in response.content if block.type == "tool_use")
            tool_name = tool_use.name
            tool_input = tool_use.input
            
            logger.info(f"🔧 Tool requested: {tool_name}")
            if 'explanation' in tool_input:
                logger.info(f"📝 Query explanation: {tool_input['explanation']}")
            
            # STEP 3: Execute database query via MCP
            tool_result = await execute_mcp_tool(
                tool_input['query'],
                business_id
            )
            
            logger.info(f"📊 Tool execution complete. Success: {tool_result.get('success', False)}")
            
            # STEP 4: Send tool result back to Claude for final response
            final_response = await anthropic_client.messages.create(
                model=config.ANTHROPIC_MODEL,
                max_tokens=4096,
                system=get_system_prompt(business_id),
                messages=[
                    {"role": "user", "content": message},
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
            
            # Extract text response
            text_content = next(
                (block.text for block in final_response.content if hasattr(block, "text")),
                "I couldn't generate a response."
            )
            
            logger.info(f"✅ Response generated (with data): {len(text_content)} chars")
            return text_content
        
        # STEP 5: No tools needed - direct response (general business advice)
        text_content = next(
            (block.text for block in response.content if hasattr(block, "text")),
            "I couldn't generate a response."
        )
        
        logger.info(f"✅ Response generated (no data): {len(text_content)} chars")
        return text_content
        
    except Exception as e:
        logger.error(f"❌ Error processing message: {str(e)}", exc_info=True)
        return f"I apologize, but I encountered an error: {str(e)}"


@app.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    """WebSocket endpoint for chat"""
    await websocket.accept()
    
    business_id = None
    user_id = None
    
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
        
        logger.info(f"🔌 WebSocket connected: user={user_id[:8]}..., business={business_id[:8]}...")
        
        await websocket.send_json({
            "type": "connected",
            "message": "Connected to Mali Daftari, your personal business assistant.",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Message loop
        while True:
            data = await websocket.receive_json()
            message = data.get('message', '').strip()
            
            if not message:
                continue
            
            logger.info(f"📨 Message received: {message[:100]}...")
            
            # Process message with Claude
            response = await process_message(message, business_id, user_id)
            
            # Send response back to user
            await websocket.send_json({
                "type": "message",
                "content": response,
                "timestamp": datetime.utcnow().isoformat()
            })
            
    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket disconnected: user={user_id[:8] if user_id else 'unknown'}")
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
        # Check MCP server
        mcp_status = await mcp_client.health_check()
        
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "mcp_server": "connected" if mcp_status else "disconnected",
            "ai_provider": "Anthropic Claude",
            "model": config.ANTHROPIC_MODEL,
            "environment": config.ENVIRONMENT
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
        "version": "1.0.0",
        "status": "running",
        "ai_provider": "Anthropic Claude",
        "model": config.ANTHROPIC_MODEL,
        "endpoints": {
            "websocket": "/ws/chat",
            "health": "/health",
            "docs": "/docs"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")