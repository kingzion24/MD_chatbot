"""
Performance Logger for Admin Panel Monitoring
Logs all interactions to database for real-time analytics
"""

import asyncpg
import uuid
import json
from datetime import datetime
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)


class PerformanceLogger:
    """Logs AI agent interactions for monitoring"""
    
    def __init__(self, db_pool: asyncpg.Pool):
        self.db_pool = db_pool
    
    async def log_interaction(
        self,
        business_id: str,
        session_id: str,
        original_query: str,
        detected_language: str,
        translated_query: Optional[str],
        query_type: str,
        sql_generated: Optional[str],
        query_success: bool,
        response_text: str,
        processing_time_ms: int,
        error_message: Optional[str] = None
    ) -> str:
        """
        Log complete interaction for admin monitoring
        
        Returns:
            interaction_id
        """
        
        interaction_id = str(uuid.uuid4())
        
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO agent_interactions (
                        id, business_id, session_id,
                        original_query, detected_language,
                        translated_query, query_type,
                        generated_sql, query_success,
                        response_text, response_language,
                        total_processing_time_ms,
                        error_message, created_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW()
                    )
                """,
                    interaction_id, business_id, session_id,
                    original_query, detected_language,
                    translated_query, query_type,
                    sql_generated, query_success,
                    response_text, detected_language,
                    processing_time_ms,
                    error_message
                )
            
            logger.debug(f"📝 Logged interaction: {interaction_id}")
            return interaction_id
            
        except Exception as e:
            logger.error(f"Failed to log interaction: {e}")
            return str(uuid.uuid4())  # Return dummy ID
    
    async def update_feedback(
        self,
        interaction_id: str,
        rating: int,
        feedback: Optional[str] = None
    ):
        """Update interaction with user feedback"""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE agent_interactions
                    SET user_rating = $1, user_feedback = $2
                    WHERE id = $3
                """, rating, feedback, interaction_id)
            
            logger.info(f"✅ Feedback updated for {interaction_id}")
            
        except Exception as e:
            logger.error(f"Failed to update feedback: {e}")