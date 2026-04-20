"""
Core configuration and settings for Mini Devin.
"""
import os
from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    # Groq
    groq_api_key: str = Field(default="", env="GROQ_API_KEY")
    groq_model: str = "llama-3.3-70b-versatile"
    groq_fast_model: str = "llama-3.1-8b-instant"

    # Pinecone
    pinecone_api_key: str = Field(default="", env="PINECONE_API_KEY")
    pinecone_index_name: str = Field(default="mini-devin-index", env="PINECONE_INDEX_NAME")
    pinecone_environment: str = Field(default="us-east-1", env="PINECONE_ENVIRONMENT")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379", env="REDIS_URL")

    # App
    app_host: str = Field(default="127.0.0.1", env="APP_HOST")
    app_port: int = Field(default=8000, env="APP_PORT")

    # Agent settings
    max_retries: int = 3
    retry_delay: float = 1.0
    stream_chunk_size: int = 50

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
