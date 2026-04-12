import os
from dotenv import load_dotenv, find_dotenv

# Walk up the directory tree from this file to find the root .env.
# In Docker the env vars are already injected by docker-compose (override=False
# is the default, so container-level vars always win). For local dev without
# Docker this call populates os.environ from MD_chatbot/.env automatically.
load_dotenv(find_dotenv())


class Config:
    # Environment
    ENVIRONMENT: str = os.getenv('ENVIRONMENT', 'production')

    # MCP Server
    MCP_SERVER_URL: str = os.getenv('MCP_SERVER_URL', 'http://mcp-postgres:8000')

    # Anthropic
    ANTHROPIC_API_KEY: str = os.getenv('ANTHROPIC_API_KEY', '')
    ANTHROPIC_MODEL: str = os.getenv('ANTHROPIC_MODEL', 'claude-sonnet-4-6')

    # Supabase Auth
    SUPABASE_JWT_SECRET: str = os.getenv('SUPABASE_JWT_SECRET', '')

    @classmethod
    def validate(cls):
        """Validate required environment variables at startup."""
        missing = [
            name for name, val in [
                ('ANTHROPIC_API_KEY', cls.ANTHROPIC_API_KEY),
                ('SUPABASE_JWT_SECRET', cls.SUPABASE_JWT_SECRET),
                ('MCP_SERVER_URL', cls.MCP_SERVER_URL),
            ]
            if not val
        ]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")