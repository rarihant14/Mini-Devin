"""
Pinecone vector store for caching and retrieving code generation patterns.
Falls back gracefully when Pinecone is unavailable.
"""
from __future__ import annotations
import hashlib
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class InMemoryVectorStore:
    """Simple in-memory fallback when Pinecone is unavailable."""
    
    def __init__(self):
        self._store: Dict[str, Dict[str, Any]] = {}
    
    def upsert(self, vector_id: str, values: List[float], metadata: Dict) -> bool:
        self._store[vector_id] = {"values": values, "metadata": metadata}
        return True
    
    def query(self, values: List[float], top_k: int = 3) -> List[Dict]:
        """Simple cosine-like similarity using dot product (for demo)."""
        results = []
        for vid, data in self._store.items():
            stored = data["values"]
            if len(stored) == len(values):
                dot = sum(a * b for a, b in zip(stored, values))
                mag_a = sum(a**2 for a in stored) ** 0.5
                mag_b = sum(b**2 for b in values) ** 0.5
                score = dot / (mag_a * mag_b + 1e-10)
                results.append({"id": vid, "score": score, "metadata": data["metadata"]})
        return sorted(results, key=lambda x: -x["score"])[:top_k]


class PineconeStore:
    """
    Pinecone-backed vector store for code pattern retrieval.
    Wraps the Pinecone SDK with a simple embedding approach.
    Falls back to in-memory store when Pinecone is unavailable.
    """
    
    def __init__(self):
        self._index = None
        self._available = False
        self._fallback = InMemoryVectorStore()
        self._embed_dim = 128  # Lightweight hash-based embedding for demo
    
    async def initialize(self, api_key: str, index_name: str, environment: str):
        """Initialize Pinecone connection."""
        if not api_key or api_key == "your_pinecone_api_key_here":
            logger.info("📌 Pinecone not configured. Using in-memory vector store.")
            return
        
        try:
            from pinecone import Pinecone, ServerlessSpec
            
            pc = Pinecone(api_key=api_key)
            
            # Create index if it doesn't exist
            existing = [idx.name for idx in pc.list_indexes()]
            if index_name not in existing:
                pc.create_index(
                    name=index_name,
                    dimension=self._embed_dim,
                    metric="cosine",
                    spec=ServerlessSpec(cloud="aws", region=environment)
                )
                logger.info("✅ Created Pinecone index: %s", index_name)
            
            self._index = pc.Index(index_name)
            self._available = True
            logger.info("✅ Pinecone connected: index=%s", index_name)
            
        except Exception as e:
            logger.warning("⚠️  Pinecone unavailable (%s). Using in-memory store.", e)
            self._available = False
    
    def _embed(self, text: str) -> List[float]:
        """
        Lightweight hash-based embedding for demo purposes.
        In production: use sentence-transformers or OpenAI embeddings.
        """
        h = hashlib.sha256(text.lower().encode()).digest()
        # Create 128-dim float vector from hash bytes
        vec = []
        for i in range(0, min(len(h), self._embed_dim // 4)):
            byte = h[i % len(h)]
            vec.extend([
                (byte & 0b11000000) / 192.0,
                (byte & 0b00110000) / 48.0,
                (byte & 0b00001100) / 12.0,
                (byte & 0b00000011) / 3.0,
            ])
        # Pad/truncate to exact dim
        while len(vec) < self._embed_dim:
            vec.append(0.0)
        return vec[:self._embed_dim]
    
    def _make_id(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()[:16]
    
    async def upsert(self, text: str, metadata: Dict[str, Any]) -> bool:
        """Store a text + metadata vector."""
        try:
            vec_id = self._make_id(text)
            embedding = self._embed(text)
            
            if self._available and self._index:
                self._index.upsert(vectors=[{
                    "id": vec_id,
                    "values": embedding,
                    "metadata": {**metadata, "text": text[:500], "ts": time.time()}
                }])
                logger.debug("Pinecone upsert: %s", vec_id)
            else:
                self._fallback.upsert(vec_id, embedding, {**metadata, "text": text[:500]})
            
            return True
        except Exception as e:
            logger.debug("Upsert failed: %s", e)
            return False
    
    async def query_similar(self, text: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """Find similar patterns from vector store."""
        try:
            embedding = self._embed(text)
            
            if self._available and self._index:
                results = self._index.query(
                    vector=embedding,
                    top_k=top_k,
                    include_metadata=True
                )
                return [
                    {"id": m.id, "score": m.score, "metadata": m.metadata or {}}
                    for m in results.matches
                ]
            else:
                return self._fallback.query(embedding, top_k)
        except Exception as e:
            logger.debug("Query failed: %s", e)
            return []
    
    @property
    def is_available(self) -> bool:
        return self._available


# Singleton
pinecone_store = PineconeStore()
