"""
Translation Service for Mali Daftari
Handles Kiswahili ↔ English translation using Helsinki-NLP models
"""

from transformers import MarianMTModel, MarianTokenizer
from typing import Literal
import logging

logger = logging.getLogger(__name__)

class TranslationService:
    """Handles bidirectional translation between Kiswahili and English"""
    
    def __init__(self):
        """Initialize translation models (loads on startup)"""
        logger.info("Loading translation models...")
        
        try:
            # Kiswahili → English
            self.sw_to_en_model = MarianMTModel.from_pretrained(
                'Helsinki-NLP/opus-mt-sw-en'
            )
            self.sw_to_en_tokenizer = MarianTokenizer.from_pretrained(
                'Helsinki-NLP/opus-mt-sw-en'
            )
            
            # English → Kiswahili
            self.en_to_sw_model = MarianMTModel.from_pretrained(
                'Helsinki-NLP/opus-mt-en-sw'
            )
            self.en_to_sw_tokenizer = MarianTokenizer.from_pretrained(
                'Helsinki-NLP/opus-mt-en-sw'
            )
            
            logger.info("✅ Translation models loaded successfully!")
            
        except Exception as e:
            logger.error(f"❌ Failed to load translation models: {e}")
            raise
    
    def detect_language(self, text: str) -> Literal["sw", "en"]:
        """
        Detect if text is in Kiswahili or English
        
        Args:
            text: Input text to analyze
            
        Returns:
            "sw" for Kiswahili, "en" for English
        """
        # Common Kiswahili words/phrases
        swahili_indicators = [
            # Greetings
            'habari', 'mambo', 'hujambo', 'shikamoo', 'vipi',
            
            # Common verbs
            'nionyeshe', 'nina', 'niko', 'nataka', 'ninahitaji',
            'tafadhali', 'nitumie', 'nipatie',
            
            # Business terms
            'mauzo', 'bidhaa', 'bei', 'gharama', 'faida',
            'hifadhi', 'duka', 'mteja',
            
            # Time expressions
            'leo', 'jana', 'kesho', 'wiki', 'mwezi', 'mwaka',
            
            # Question words
            'je', 'nini', 'ngapi', 'vipi', 'lini', 'wapi',
            
            # Common words
            'ya', 'za', 'wa', 'na', 'kwa', 'au', 'ni',
            'jumla', 'kiasi', 'pesa', 'shilingi'
        ]
        
        text_lower = text.lower()
        
        # Count Kiswahili indicators
        sw_count = sum(1 for indicator in swahili_indicators if indicator in text_lower)
        
        # If 2 or more Kiswahili words found, classify as Kiswahili
        if sw_count >= 2:
            logger.debug(f"Detected Kiswahili ({sw_count} indicators found)")
            return "sw"
        else:
            logger.debug(f"Detected English ({sw_count} Kiswahili indicators)")
            return "en"
    
    def translate_sw_to_en(self, text: str) -> str:
        """Translate Kiswahili to English"""
        try:
            inputs = self.sw_to_en_tokenizer(
                text, 
                return_tensors="pt", 
                padding=True,
                truncation=True,
                max_length=512
            )
            
            translated = self.sw_to_en_model.generate(**inputs)
            result = self.sw_to_en_tokenizer.decode(
                translated[0], 
                skip_special_tokens=True
            )
            
            logger.debug(f"Translated SW→EN: '{text}' → '{result}'")
            return result
            
        except Exception as e:
            logger.error(f"Translation error (SW→EN): {e}")
            return text  # Return original if translation fails
    
    def translate_en_to_sw(self, text: str) -> str:
        """Translate English to Kiswahili"""
        try:
            inputs = self.en_to_sw_tokenizer(
                text,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512
            )
            
            translated = self.en_to_sw_model.generate(**inputs)
            result = self.en_to_sw_tokenizer.decode(
                translated[0],
                skip_special_tokens=True
            )
            
            logger.debug(f"Translated EN→SW: '{text}' → '{result}'")
            return result
            
        except Exception as e:
            logger.error(f"Translation error (EN→SW): {e}")
            return text  # Return original if translation fails


# Singleton instance
_translation_service = None

def get_translation_service() -> TranslationService:
    """Get or create translation service singleton"""
    global _translation_service
    if _translation_service is None:
        _translation_service = TranslationService()
    return _translation_service 