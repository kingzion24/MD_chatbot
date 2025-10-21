import os

class Config:
    # Environment
    ENVIRONMENT: str = os.getenv('ENVIRONMENT', 'production')
    
    # MCP Server
    MCP_SERVER_URL: str = os.getenv('MCP_SERVER_URL', 'http://mcp-postgres:3000')
    
    # Anthropic Configuration
    ANTHROPIC_API_KEY: str = os.getenv('ANTHROPIC_API_KEY', '')
    ANTHROPIC_MODEL: str = os.getenv('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022')
    
    @classmethod
    def validate(cls):
        """Validate required environment variables"""
        if not cls.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY must be set")
        
        if not cls.MCP_SERVER_URL:
            raise ValueError("MCP_SERVER_URL must be set")