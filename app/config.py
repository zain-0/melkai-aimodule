from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # AWS Bedrock Configuration
    AWS_REGION: str = "us-east-2"
    
    # AWS Credentials (optional - uses IAM role if not provided)
    # For local testing, set these in .env file
    # On EC2 with IAM role, leave these empty
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    
    # Model Configuration
    # Use cross-region inference profiles (us. prefix) for on-demand access
    FREE_MODEL: str = "us.anthropic.claude-3-5-haiku-20241022-v1:0"  # Claude 3.5 Haiku - Fast and cost-effective for all APIs
    LEASE_GENERATOR_MODEL: str = "us.anthropic.claude-3-5-haiku-20241022-v1:0"  # Claude 3.5 Haiku - Fastest for lease generation
    
    # AWS Bedrock Models - All use DuckDuckGo search (no native search in Bedrock)
    # Use cross-region inference profiles (us. prefix) for on-demand throughput
    ALL_MODELS: List[str] = [
        # Anthropic Claude - Best for legal analysis
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",    # Claude Sonnet 4.5 - Latest, best quality
        "us.anthropic.claude-3-5-sonnet-20241022-v2:0",  # Latest Claude 3.5 Sonnet
        "us.anthropic.claude-3-5-sonnet-20240620-v1:0",  # Previous Claude 3.5 Sonnet
        "us.anthropic.claude-3-opus-20240229-v1:0",      # Highest quality
        "us.anthropic.claude-3-haiku-20240307-v1:0",     # Fastest, cheapest
        
        # Meta Llama - Open source, cost-effective
        "us.meta.llama3-1-405b-instruct-v1:0",  # Largest, best quality
        "us.meta.llama3-1-70b-instruct-v1:0",   # Balanced performance/cost
        "us.meta.llama3-1-8b-instruct-v1:0",    # Fastest, cheapest
        
        # Mistral AI - European alternative
        "us.mistral.mistral-large-2407-v1:0",   # Best quality
        "us.mistral.mistral-small-2402-v1:0",   # Cost-effective
    ]
    
    # AWS Bedrock has NO native search - all models use DuckDuckGo
    MODELS_WITH_NATIVE_SEARCH: List[str] = []
    
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
    
    # Lease Extraction API Settings
    LEASE_EXTRACTION_MODEL: str = "us.anthropic.claude-3-5-haiku-20241022-v1:0"  # Claude 3.5 Haiku with inference profile
    LEASE_EXTRACTION_TEMPERATURE: float = 0.0
    LEASE_EXTRACTION_MAX_TOKENS: int = 16000
    LEASE_EXTRACTION_MAX_CONCURRENT: int = 5
    LEASE_EXTRACTION_TIMEOUT: int = 120
    LEASE_EXTRACTION_WINDOW_SIZE: int = 7
    LEASE_EXTRACTION_WINDOW_OVERLAP: int = 2
    LEASE_EXTRACTION_MAX_PAGES: int = 100
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
