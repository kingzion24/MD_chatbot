import os
from typing import Optional

class Config:
    # Environment
    ENVIRONMENT: str = os.getenv('ENVIRONMENT', 'development')
    
    # MCP Server
    MCP_SERVER_URL: str = os.getenv('MCP_SERVER_URL', 'http://mcp-postgres:3000')
    
    # Anthropic Configuration
    ANTHROPIC_API_KEY: str = os.getenv('ANTHROPIC_API_KEY', '')
    USE_ANTHROPIC: bool = os.getenv('USE_ANTHROPIC', 'true').lower() == 'true'
    ANTHROPIC_MODEL: str = os.getenv('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022')
    
    # OpenRouter Configuration (fallback)
    OPENROUTER_API_KEY: str = os.getenv('OPENROUTER_API_KEY', '')
    OPENROUTER_MODEL: str = os.getenv('OPENROUTER_MODEL', 'google/gemini-flash-1.5')
    
    @classmethod
    def validate(cls):
        """Validate required environment variables"""
        if cls.USE_ANTHROPIC:
            if not cls.ANTHROPIC_API_KEY:
                raise ValueError("ANTHROPIC_API_KEY must be set when USE_ANTHROPIC=true")
        else:
            if not cls.OPENROUTER_API_KEY:
                raise ValueError("OPENROUTER_API_KEY must be set when USE_ANTHROPIC=false")
        
        if not cls.MCP_SERVER_URL:
            raise ValueError("MCP_SERVER_URL must be set")