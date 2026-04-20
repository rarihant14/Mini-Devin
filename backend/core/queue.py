"""
Redis-based message queue for async agent communication.
Fallback to in-memory queue when Redis is unavailable.
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, AsyncGenerator
from collections import defaultdict

logger = logging.getLogger(__name__)


class InMemoryQueue:
    """Fallback in-memory queue when Redis is unavailable."""
    
    def __init__(self):
        self._queues: Dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)
        self._pubsub: Dict[str, list] = defaultdict(list)
    
    async def enqueue(self, channel: str, message: Dict[str, Any]) -> None:
        await self._queues[channel].put(json.dumps(message))
    
    async def dequeue(self, channel: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        try:
            raw = await asyncio.wait_for(self._queues[channel].get(), timeout=timeout)
            return json.loads(raw)
        except asyncio.TimeoutError:
            return None
    
    async def publish(self, channel: str, message: Dict[str, Any]) -> None:
        for listener in self._pubsub.get(channel, []):
            await listener.put(json.dumps(message))
    
    async def subscribe(self, channel: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._pubsub[channel].append(q)
        return q
    
    async def ping(self) -> bool:
        return True


class RedisQueue:
    """Redis-backed message queue for production."""
    
    def __init__(self, url: str):
        self.url = url
        self._redis = None
        self._available = False
    
    async def connect(self):
        try:
            import redis.asyncio as aioredis
            self._redis = await aioredis.from_url(self.url, decode_responses=True)
            await self._redis.ping()
            self._available = True
            logger.info("✅ Redis connected at %s", self.url)
        except Exception as e:
            logger.warning("⚠️  Redis unavailable (%s). Using in-memory queue.", e)
            self._available = False
    
    async def ping(self) -> bool:
        return self._available
    
    async def enqueue(self, channel: str, message: Dict[str, Any]) -> None:
        if self._available and self._redis:
            await self._redis.rpush(channel, json.dumps(message))
        
    async def dequeue(self, channel: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        if self._available and self._redis:
            result = await self._redis.blpop(channel, timeout=int(timeout))
            if result:
                return json.loads(result[1])
        return None
    
    async def publish(self, channel: str, message: Dict[str, Any]) -> None:
        if self._available and self._redis:
            await self._redis.publish(channel, json.dumps(message))


class MessageBus:
    """
    Unified message bus that wraps Redis with in-memory fallback.
    Used for async communication between agents in the pipeline.
    """
    
    def __init__(self):
        self._redis_queue: Optional[RedisQueue] = None
        self._memory_queue = InMemoryQueue()
        self._use_redis = False
        self._stream_listeners: Dict[str, list] = defaultdict(list)
    
    async def initialize(self, redis_url: str):
        self._redis_queue = RedisQueue(redis_url)
        await self._redis_queue.connect()
        self._use_redis = await self._redis_queue.ping()
        backend = "Redis" if self._use_redis else "In-Memory"
        logger.info("📨 MessageBus initialized with %s backend", backend)
    
    async def send_agent_event(self, session_id: str, agent: str, event_type: str, data: Any):
        """Send an event from one agent to the stream."""
        message = {
            "session_id": session_id,
            "agent": agent,
            "event": event_type,
            "data": data,
            "ts": time.time()
        }
        channel = f"stream:{session_id}"
        await self._memory_queue.publish(channel, message)
    
    async def subscribe_to_session(self, session_id: str) -> asyncio.Queue:
        """Subscribe to all events for a session."""
        channel = f"stream:{session_id}"
        return await self._memory_queue.subscribe(channel)
    
    async def stream_events(self, session_id: str) -> AsyncGenerator[str, None]:
        """Async generator that yields SSE-formatted events."""
        q = await self.subscribe_to_session(session_id)
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(q.get(), timeout=60.0)
                    msg = json.loads(raw)
                    yield f"data: {json.dumps(msg)}\n\n"
                    if msg.get("event") == "pipeline_complete":
                        break
                except asyncio.TimeoutError:
                    yield "data: {\"event\": \"heartbeat\"}\n\n"
        except asyncio.CancelledError:
            pass


# Singleton instance
message_bus = MessageBus()
