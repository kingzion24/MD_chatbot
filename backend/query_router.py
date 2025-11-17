"""
Intelligent Query Router for Mali Daftari
Classifies queries as DATA or CONVERSATIONAL
"""

from typing import Literal
import logging
import re

logger = logging.getLogger(__name__)


class QueryRouter:
    """Routes queries to appropriate handlers based on type"""
    
    def __init__(self):
        """Initialize query router with keyword indicators"""
        
        # Keywords indicating need for database access
        self.data_query_indicators = {
            'english': [
                # Query verbs
                'show', 'display', 'list', 'get', 'find', 'see',
                
                # Question patterns
                'how many', 'how much', 'what is', 'what are', 'which',
                'what\'s', 'whats',
                
                # Business metrics
                'sales', 'revenue', 'profit', 'income', 'earnings',
                'total', 'sum', 'count',
                
                # Data entities
                'inventory', 'stock', 'products', 'expenses', 'cost',
                'items', 'goods',
                
                # Specific queries
                'my sales', 'my products', 'my inventory', 'my expenses',
                'this month', 'this week', 'today', 'yesterday',
                
                # Status queries
                'low stock', 'out of stock', 'best selling', 'top products'
            ],
            'swahili': [
                # Query verbs
                'nionyeshe', 'orodha', 'tazama', 'pata', 'onyesha',
                
                # Question patterns  
                'ni ngapi', 'ni kiasi gani', 'ni nini', 'zipi',
                
                # Business metrics
                'mauzo', 'mapato', 'faida', 'jumla', 'hesabu',
                
                # Data entities
                'bidhaa', 'hifadhi', 'stock', 'gharama', 'matumizi',
                'vitu',
                
                # Specific queries
                'mauzo yangu', 'bidhaa zangu', 'hifadhi yangu',
                'mwezi huu', 'wiki hii', 'leo', 'jana',
                
                # Status queries
                'bidhaa zinazokaribia kuisha', 'zinazouzwa zaidi'
            ]
        }
        
        # Keywords indicating conversational/advice queries
        self.conversational_indicators = {
            'english': [
                # Greetings
                'hello', 'hi', 'hey', 'greetings',
                
                # Small talk
                'how are you', 'what\'s up', 'whats up',
                
                # Capability questions
                'what can you do', 'help me', 'can you help',
                
                # Advice requests (no specific data needed)
                'how can i improve', 'how should i', 'what should i do',
                'advice', 'suggest', 'recommend', 'tips',
                'best practice', 'strategy'
            ],
            'swahili': [
                # Greetings
                'habari', 'mambo', 'vipi', 'hujambo', 'shikamoo',
                
                # Small talk
                'uko aje', 'unafanya nini',
                
                # Capability questions  
                'unaweza nini', 'nisaidie', 'unaweza kunisaidia',
                
                # Advice requests
                'ninawezaje kuboresha', 'nifanye nini', 'nipendekeze',
                'ushauri', 'mapendekezo', 'mikakati',
                'mbinu bora'
            ]
        }
        
        # Patterns that DEFINITELY indicate data queries
        self.data_patterns = [
            r'\bmy\s+(sales|products|inventory|expenses|stock)\b',
            r'\bthis\s+(month|week|year|quarter)\b',
            r'\blast\s+\d+\s+(days|weeks|months)\b',
            r'\bhow\s+many\b',
            r'\bhow\s+much\b',
            r'\btotal\s+(sales|revenue|expenses)\b',
            r'\bmauzo\s+yangu\b',
            r'\bmwezi\s+huu\b',
            r'\bwiki\s+hii\b',
        ]
    
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
        
        # FIRST: Check definite data patterns
        for pattern in self.data_patterns:
            if re.search(pattern, query_lower):
                logger.info(f"📊 DEFINITE data query matched pattern: {pattern}")
                return True
        
        # Get language-specific indicators
        lang_key = 'swahili' if language == 'sw' else 'english'
        data_indicators = self.data_query_indicators[lang_key]
        chat_indicators = self.conversational_indicators[lang_key]
        
        # Count matches
        data_matches = sum(1 for indicator in data_indicators if indicator in query_lower)
        chat_matches = sum(1 for indicator in chat_indicators if indicator in query_lower)
        
        logger.debug(
            f"Query: '{query}' | Language: {language} | "
            f"Data matches: {data_matches} | Chat matches: {chat_matches}"
        )
        
        # Decision logic:
        # - If NO matches at all, default to conversational
        # - If data_matches > 0 and chat_matches == 0, it's data
        # - If both have matches, data wins if it has more matches
        # - If equal matches, prefer data (safer to check database)
        
        if data_matches == 0 and chat_matches == 0:
            logger.info("💬 No clear indicators - defaulting to CONVERSATIONAL")
            return False
        
        if data_matches > 0 and chat_matches == 0:
            logger.info(f"📊 Clear DATA query ({data_matches} indicators)")
            return True
        
        if data_matches == 0 and chat_matches > 0:
            logger.info(f"💬 Clear CONVERSATIONAL query ({chat_matches} indicators)")
            return False
        
        # Both have matches - use majority
        is_data = data_matches >= chat_matches
        
        logger.info(
            f"{'📊 DATA' if is_data else '💬 CONVERSATIONAL'} query "
            f"(data:{data_matches} vs chat:{chat_matches})"
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