from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncpg
import os
import logging
from datetime import datetime
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PostgreSQL MCP Server")

class QueryRequest(BaseModel):
    sql: str

@app.get("/")
async def root():
    return {
        "service": "PostgreSQL MCP Server",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/query")
async def execute_query(request: QueryRequest):
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL not configured")
        raise HTTPException(status_code=500, detail="DATABASE_URL not configured")
    
    # Security: Only allow SELECT queries
    sql = request.sql.strip().upper()
    if not sql.startswith("SELECT"):
        logger.warning(f"Rejected non-SELECT query: {request.sql[:50]}...")
        raise HTTPException(status_code=400, detail="Only SELECT queries are allowed")
    
    try:
        logger.info(f"Executing query: {request.sql[:100]}...")
        
        # Parse DATABASE_URL to extract components
        parsed = urlparse(database_url)
        
        # Connect with explicit SSL for Supabase
        conn = await asyncpg.connect(
            user=parsed.username,
            password=parsed.password,
            database=parsed.path[1:],  # Remove leading '/'
            host=parsed.hostname,
            port=parsed.port or 5432,
            ssl='require'  # Simple string for Supabase
        )
        
        try:
            # Execute query
            rows = await conn.fetch(request.sql)
            
            # Convert to list of dicts
            result = [dict(row) for row in rows]
            
            logger.info(f"Query successful: {len(result)} rows returned")
            
            return {
                "rows": result,
                "row_count": len(result),
                "columns": list(result[0].keys()) if result else []
            }
            
        finally:
            await conn.close()
            
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000, log_level="info")