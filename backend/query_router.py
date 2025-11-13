"""
Intelligent Query Router for Mali Daftari
Classifies queries as DATA or CONVERSATIONAL
"""

from typing import Literal
import logging

logger = logging.getLogger(__name__)

class QueryRouter:
    """Routes queries to appropriate handlers based on type"""
    
    def __init__(self):
        """Initialize query router with keyword indicators"""
        
        # Keywords indicating need for database access
        self.data_query_indicators = {
            'english': [
                'show', 'display', 'list', 'get', 'how many', 'how much',
                'what is the', 'what are', 'total', 'sales', 'inventory',
                'stock', 'products', 'expenses', 'revenue', 'profit'
            ],
            'swahili': [
                'nionyeshe', 'orodha', 'ni ngapi', 'jumla', 'mauzo',
                'bidhaa', 'hifadhi', 'gharama', 'mapato', 'faida'
            ]
        }
        
        # Keywords indicating conversational/advice queries
        self.conversational_indicators = {
            'english': [
                'hello', 'hi', 'how are you', 'what can you do',
                'help', 'advice', 'suggest', 'how can i', 'should i'
            ],
            'swahili': [
                'habari', 'mambo', 'vipi', 'unaweza nini',
                'saidia', 'ushauri', 'pendekeza', 'ninawezaje'
            ]
        }
    
    def is_data_query(self, query: str, language: Literal["sw", "en"]) -> bool:
        """
        Determine if query needs database access
        
        Args:
            query: The query text
            language: Detected language
            
        Returns:
            True if query needs database, False otherwise
        """
        query_lower = query.lower()
        
        # Get language-specific indicators
        lang_key = 'swahili' if language == 'sw' else 'english'
        data_indicators = self.data_query_indicators[lang_key]
        chat_indicators = self.conversational_indicators[lang_key]
        
        # Count matches
        data_matches = sum(1 for indicator in data_indicators if indicator in query_lower)
        chat_matches = sum(1 for indicator in chat_indicators if indicator in query_lower)
        
        # Decision: data query if more data indicators than chat indicators
        is_data = data_matches > chat_matches
        
        logger.debug(
            f"Query classification: data_matches={data_matches}, "
            f"chat_matches={chat_matches}, is_data={is_data}"
        )
        
        return is_data


# Singleton instance
_query_router = None

def get_query_router() -> QueryRouter:
    """Get or create query router singleton"""
    global _query_router
    if _query_router is None:
        _query_router = QueryRouter()
    return _query_router