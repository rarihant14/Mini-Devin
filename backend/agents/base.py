"""
Base agent class with Groq LLM, retry logic, and streaming support.
"""
from __future__ import annotations
import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

from backend.core.config import settings
from backend.core.state import AgentResult, AgentStatus, AgentType, PipelineState
from backend.core.queue import message_bus

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Abstract base class for all Mini Devin agents.
    Provides: Groq LLM, retry with exponential backoff, streaming, event emission.
    """
    
    agent_type: AgentType
    system_prompt: str = ""
    use_fast_model: bool = False
    
    def __init__(self):
        model_name = settings.groq_fast_model if self.use_fast_model else settings.groq_model
        self.llm = ChatGroq(
            api_key=settings.groq_api_key,
            model_name=model_name,
            temperature=0.1,
            streaming=True,
            max_tokens=4096,
        )
        self.llm_sync = ChatGroq(
            api_key=settings.groq_api_key,
            model_name=model_name,
            temperature=0.1,
            streaming=False,
            max_tokens=4096,
        )
        self.max_retries = settings.max_retries
        self.retry_delay = settings.retry_delay
    
    @abstractmethod
    async def process(self, state: PipelineState) -> PipelineState:
        """Core logic — each agent implements this."""
        pass
    
    async def run(self, state: PipelineState) -> PipelineState:
        """
        Wrapper that handles retry logic, timing, and event emission.
        """
        start = time.time()
        state.current_agent = self.agent_type
        
        await message_bus.send_agent_event(
            state.session_id, self.agent_type.value, "agent_start",
            {"message": f"🚀 {self.agent_type.value.replace('_', ' ').title()} starting..."}
        )
        
        last_error = None
        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    delay = self.retry_delay * (2 ** (attempt - 1))
                    await message_bus.send_agent_event(
                        state.session_id, self.agent_type.value, "agent_retry",
                        {"attempt": attempt + 1, "delay": delay, "message": f"⚠️ Retry {attempt + 1}/{self.max_retries}..."}
                    )
                    await asyncio.sleep(delay)
                    state.total_retries += 1
                
                state = await self.process(state)
                
                duration = (time.time() - start) * 1000
                result = AgentResult(
                    agent=self.agent_type,
                    status=AgentStatus.SUCCESS,
                    output=f"Completed in {duration:.0f}ms",
                    retries=attempt,
                    duration_ms=duration,
                )
                state.agent_results.append(result)
                
                await message_bus.send_agent_event(
                    state.session_id, self.agent_type.value, "agent_complete",
                    {"message": f"✅ {self.agent_type.value.replace('_', ' ').title()} done ({duration:.0f}ms)", "duration_ms": duration}
                )
                return state
                
            except Exception as e:
                last_error = e
                state.error_count += 1
                logger.error("[%s] Attempt %d failed: %s", self.agent_type.value, attempt + 1, e)
                
                await message_bus.send_agent_event(
                    state.session_id, self.agent_type.value, "agent_error",
                    {"error": str(e), "attempt": attempt + 1}
                )
        
        # All retries exhausted
        duration = (time.time() - start) * 1000
        result = AgentResult(
            agent=self.agent_type,
            status=AgentStatus.FAILED,
            error=str(last_error),
            retries=self.max_retries,
            duration_ms=duration,
        )
        state.agent_results.append(result)
        logger.error("[%s] All retries exhausted.", self.agent_type.value)
        return state
    
    async def stream_llm(
        self, 
        state: PipelineState, 
        prompt: str,
        system_override: Optional[str] = None
    ) -> str:
        """Stream LLM response and emit chunks via message bus."""
        system = system_override or self.system_prompt
        messages = [SystemMessage(content=system), HumanMessage(content=prompt)]
        
        full_response = ""
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                full_response += chunk.content
                await message_bus.send_agent_event(
                    state.session_id, self.agent_type.value, "stream_chunk",
                    {"chunk": chunk.content, "agent": self.agent_type.value}
                )
        
        return full_response
    
    async def call_llm(self, prompt: str, system_override: Optional[str] = None) -> str:
        """Non-streaming LLM call for structured outputs."""
        system = system_override or self.system_prompt
        messages = [SystemMessage(content=system), HumanMessage(content=prompt)]
        response = await self.llm_sync.ainvoke(messages)
        return response.content
