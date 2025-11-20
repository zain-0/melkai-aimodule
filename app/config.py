from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # API Keys
    OPENROUTER_API_KEY: str
    
    # OpenRouter Configuration
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    FREE_MODEL: str = "google/gemini-2.0-flash-001"
    
    # Models to test - ONLY models with web search capabilities
    # Models without web search have been removed
    ALL_MODELS: List[str] = [
        # Perplexity - Native online search built-in (VERIFIED WORKING)
        "perplexity/sonar-pro",
        "perplexity/sonar",
        "perplexity/sonar-reasoning",
        
        # Anthropic Claude - Latest working models with search capabilities
        "anthropic/claude-sonnet-4.5",
        "anthropic/claude-3.7-sonnet",
        "anthropic/claude-opus-4",
        
        # OpenAI - Latest models with web search
        "openai/gpt-5",
        "openai/gpt-5-mini",
        "openai/gpt-4o",
        
        # Google Gemini - Working 2.5 series
        "google/gemini-2.5-flash-preview-09-2025",
        "google/gemini-2.5-flash-lite",
        
        # Meta Llama - Free and paid models
        "meta-llama/llama-4-scout",
        "meta-llama/llama-3.3-8b-instruct:free",
        
        # Mistral - Working models
        "mistralai/mistral-medium-3.1",
        "mistralai/devstral-medium",
        
        # DeepSeek - Working models with search
        "deepseek/deepseek-v3.2-exp",
        "deepseek/deepseek-chat-v3.1:free",
        
        # Qwen - Working models
        "qwen/qwen3-max",
        "qwen/qwen3-coder-plus",
    ]
    
    # Legacy: Models categorized by native search capability
    # (kept for backward compatibility with DuckDuckGo endpoint)
    MODELS_WITH_NATIVE_SEARCH: List[str] = [
        "perplexity/sonar-pro",
        "perplexity/sonar",
        "perplexity/sonar-reasoning",
    ]
    
    # Deprecated properties (for backward compatibility)
    @property
    def MODELS_WITH_SEARCH(self) -> List[str]:
        """Legacy property - returns models with native search"""
        return self.MODELS_WITH_NATIVE_SEARCH
    
    @property
    def MODELS_WITHOUT_SEARCH(self) -> List[str]:
        """Legacy property - returns models without native search"""
        return [m for m in self.ALL_MODELS if m not in self.MODELS_WITH_NATIVE_SEARCH]
    
    @property
    def MODELS_WITHOUT_NATIVE_SEARCH(self) -> List[str]:
        """Models that don't have built-in web search (for DuckDuckGo endpoint)"""
        return [m for m in self.ALL_MODELS if m not in self.MODELS_WITH_NATIVE_SEARCH]
    
    # Application settings
    MAX_FILE_SIZE_MB: int = 10
    SEARCH_RESULTS_LIMIT: int = 10
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
