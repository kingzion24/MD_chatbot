# backend/app.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import json
import os
from datetime import datetime
from openai import AsyncOpenAI
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
    title="MSME Business Assistant API",
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
    logger.info("Configuration validated successfully")
except ValueError as e:
    logger.error(f"Configuration error: {str(e)}")
    raise

# Initialize clients
config = Config()
openrouter_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=config.OPENROUTER_API_KEY,
)
mcp_client = MCPClient(config.MCP_SERVER_URL)

# MCP Tools Definition
MCP_TOOLS = [{
    "type": "function",
    "function": {
        "name": "query_business_data",
        "description": """Query business data from PostgreSQL database. 
        Available tables: inventories, products, sales, expenses.
        Use this tool ONLY when the user asks about their specific business data.
        Do NOT use this for general business advice questions.""",
        "parameters": {
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
    }
}]

async def execute_mcp_tool(sql_query: str, business_id: str) -> Dict:
    """Execute SQL query via MCP server with security"""
    try:
        # Validate and secure SQL
        secured_query = validate_and_secure_sql(sql_query, business_id)
        if not secured_query:
            logger.warning(f"Invalid SQL query rejected: {sql_query}")
            return {"error": "Invalid SQL query - only SELECT statements allowed", "results": []}
        
        logger.info(f"Executing query for business {business_id[:8]}...")
        logger.debug(f"SQL: {secured_query}")
        
        # Execute via MCP
        result = await mcp_client.execute_query(secured_query)
        
        row_count = len(result.get('rows', []))
        logger.info(f"Query returned {row_count} rows")
        
        return {
            "success": True,
            "results": result.get('rows', []),
            "row_count": row_count,
            "columns": result.get('columns', [])
        }
        
    except Exception as e:
        logger.error(f"MCP execution error: {str(e)}")
        return {
            "error": f"Database query failed: {str(e)}",
            "results": []
        }

async def process_message(message: str, business_id: str, user_id: str) -> str:
    """Process user message with OpenRouter"""
    
    try:
        logger.info(f"Processing message from user {user_id[:8]}...: {message[:50]}...")
        
        # Initial LLM call with tools
        response = await openrouter_client.chat.completions.create(
            model=config.OPENROUTER_MODEL,
            messages=[
                {"role": "system", "content": get_system_prompt(business_id)},
                {"role": "user", "content": message}
            ],
            tools=MCP_TOOLS,
            tool_choice="auto",
            extra_headers={
                "HTTP-Referer": "https://msme-assistant.app",
                "X-Title": "MSME Business Assistant"
            }
        )
        
        message_obj = response.choices[0].message
        
        # Check if LLM wants to use tools (query database)
        if message_obj.tool_calls:
            tool_call = message_obj.tool_calls[0]
            function_args = json.loads(tool_call.function.arguments)
            
            logger.info(f"Tool requested: {tool_call.function.name}")
            if 'explanation' in function_args:
                logger.info(f"Query explanation: {function_args['explanation']}")
            
            # Execute database query
            tool_result = await execute_mcp_tool(
                function_args['query'],
                business_id
            )
            
            # Get final response with tool results
            final_response = await openrouter_client.chat.completions.create(
                model=config.OPENROUTER_MODEL,
                messages=[
                    {"role": "system", "content": get_system_prompt(business_id)},
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": None, "tool_calls": message_obj.tool_calls},
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(tool_result)
                    }
                ]
            )
            
            response_content = final_response.choices[0].message.content
            logger.info(f"Response generated (with data): {len(response_content)} chars")
            return response_content
        
        # No tools needed - direct response (general business advice)
        logger.info(f"Response generated (no data): {len(message_obj.content)} chars")
        return message_obj.content
        
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}", exc_info=True)
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
        
        logger.info(f"WebSocket connected: user={user_id[:8]}..., business={business_id[:8]}...")
        
        await websocket.send_json({
            "type": "connected",
            "message": "Connected to MSME Business Assistant",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Message loop
        while True:
            data = await websocket.receive_json()
            message = data.get('message', '').strip()
            
            if not message:
                continue
            
            logger.info(f"Message received: {message[:100]}...")
            
            # Process message
            response = await process_message(message, business_id, user_id)
            
            # Send response
            await websocket.send_json({
                "type": "message",
                "content": response,
                "timestamp": datetime.utcnow().isoformat()
            })
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: user={user_id[:8] if user_id else 'unknown'}")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}", exc_info=True)
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
            "model": config.OPENROUTER_MODEL,
            "environment": config.ENVIRONMENT
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "MSME Business Assistant",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "websocket": "/ws/chat",
            "health": "/health",
            "docs": "/docs"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")