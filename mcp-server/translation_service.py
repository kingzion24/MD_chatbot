"""
Translation Service Stub for MCP Server
Translation is disabled - returns None to allow graceful degradation
"""

import logging

logger = logging.getLogger(__name__)

class TranslationService:
    """Stub translation service - does nothing"""
    
    def __init__(self):
        logger.warning("⚠️ Translation service stub loaded (models disabled)")
    
    def detect_language(self, text: str):
        """Always returns English"""
        return "en"
    
    def translate_sw_to_en(self, text: str):
        """Returns original text"""
        return text
    
    def translate_en_to_sw(self, text: str):
        """Returns original text"""
        return text


# Singleton
_translation_service = None

def get_translation_service():
    """Returns None - translation disabled"""
    logger.warning("⚠️ Translation service is DISABLED in MCP server")
    return None