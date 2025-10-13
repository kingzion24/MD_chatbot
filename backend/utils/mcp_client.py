# backend/utils/mcp_client.py
import httpx
from typing import Dict
import logging

logger = logging.getLogger(__name__)

class MCPClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
    
    async def execute_query(self, sql: str) -> Dict:
        """Execute SQL query via MCP server"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/query",
                    json={"sql": sql},
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            logger.error(f"MCP HTTP error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"MCP execution error: {str(e)}")
            raise
    
    async def health_check(self) -> bool:
        """Check MCP server health"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/health",
                    timeout=5.0
                )
                return response.status_code == 200
        except:
            return False