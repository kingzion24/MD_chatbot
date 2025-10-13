# backend/config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # OpenRouter
    OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
    OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', 'anthropic/claude-3.5-sonnet')
    
    # Database
    DATABASE_URL = os.getenv('DATABASE_URL')
    
    # MCP
    MCP_SERVER_URL = os.getenv('MCP_SERVER_URL', 'http://mcp-postgres:3000')
    
    # Application
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    ENVIRONMENT = os.getenv('ENVIRONMENT', 'production')
    
    @classmethod
    def validate(cls):
        """Validate required configuration"""
        required = ['OPENROUTER_API_KEY', 'DATABASE_URL']
        missing = [key for key in required if not getattr(cls, key)]
        if missing:
            raise ValueError(f"Missing required config: {', '.join(missing)}")