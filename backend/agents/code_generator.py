"""
Code Generator Agent — Generates production-ready code for the user's task.
Uses Pinecone for caching previously generated patterns.
"""
from __future__ import annotations
import json
import re
import logging
from typing import List, Optional

from backend.agents.base import BaseAgent
from backend.core.state import AgentType, GeneratedCode, PipelineState
from backend.core.queue import message_bus
from backend.db.pinecone_store import pinecone_store

logger = logging.getLogger(__name__)


class CodeGeneratorAgent(BaseAgent):
    agent_type = AgentType.CODE_GENERATOR
    system_prompt = """You are a world-class software engineer. Generate clean, production-ready code.

Rules:
- Write complete, working code (no placeholders, no "# TODO")
- Include proper error handling and input validation
- Follow best practices for the chosen language/framework
- Add helpful inline comments
- Use modern patterns and idioms

Respond ONLY with a JSON array of file objects:
[
  {
    "filename": "main.py",
    "language": "python",
    "description": "Main application entry point",
    "content": "# Full file content here\\n..."
  }
]

No markdown, no explanation outside the JSON array."""

    async def process(self, state: PipelineState) -> PipelineState:
        # Check Pinecone cache for similar patterns
        cached = await self._check_cache(state.user_task)
        if cached:
            await message_bus.send_agent_event(
                state.session_id, self.agent_type.value, "cache_hit",
                {"message": "⚡ Found similar pattern in knowledge base, adapting..."}
            )
        
        subtask_summary = "\n".join([
            f"- {st.title}: {st.description}" 
            for st in state.subtasks
        ])
        
        prompt = f"""Generate complete, production-ready code for this project:

PROJECT TYPE: {state.project_type}
TECH STACK: {', '.join(state.tech_stack)}

USER TASK: {state.user_task}

SUBTASKS TO IMPLEMENT:
{subtask_summary}

Generate ALL necessary files for a complete, working implementation.
Include: main application file, models/schemas, routes/handlers, auth (if needed),
database setup, utility helpers, requirements.txt, and README.md.

Return ONLY a JSON array of file objects. Each file must be complete and functional."""

        await message_bus.send_agent_event(
            state.session_id, self.agent_type.value, "thinking",
            {"message": "⚙️ Generating code files..."}
        )
        
        raw = await self.stream_llm(state, prompt)
        files = self._parse_files(raw)
        
        state.generated_files = files
        
        # Store pattern in Pinecone for future use
        if files:
            await self._cache_pattern(state.user_task, state.project_type, files)
        
        await message_bus.send_agent_event(
            state.session_id, self.agent_type.value, "files_generated",
            {
                "message": f"📁 Generated {len(files)} files",
                "files": [
                    {
                        "filename": f.filename,
                        "language": f.language,
                        "description": f.description,
                        "content": f.content,
                        "lines": len(f.content.splitlines()),
                    }
                    for f in files
                ]
            }
        )
        
        logger.info("Generated %d files for task: %s", len(files), state.user_task[:50])
        return state
    
    def _parse_files(self, raw: str) -> List[GeneratedCode]:
        """Parse LLM response into GeneratedCode objects."""
        # Try direct JSON array parse
        for pattern in [r"\[[\s\S]+\]", r"```(?:json)?\s*([\s\S]+?)```"]:
            match = re.search(pattern, raw)
            if match:
                candidate = match.group(1) if "```" in pattern else match.group(0)
                try:
                    data = json.loads(candidate.strip())
                    if isinstance(data, list):
                        return [
                            GeneratedCode(
                                filename=f.get("filename", f"file_{i}.txt"),
                                language=f.get("language", "text"),
                                content=f.get("content", ""),
                                description=f.get("description", ""),
                            )
                            for i, f in enumerate(data)
                            if isinstance(f, dict)
                        ]
                except (json.JSONDecodeError, KeyError):
                    continue
        
        # Fallback: create a single file with whatever was generated
        logger.warning("Could not parse code files JSON, creating raw output file")
        return [GeneratedCode(
            filename="generated_code.py",
            language="python",
            content=raw,
            description="Generated code (raw output)"
        )]
    
    async def _check_cache(self, task: str) -> Optional[str]:
        """Query Pinecone for similar previously generated patterns."""
        try:
            results = await pinecone_store.query_similar(task, top_k=1)
            if results and results[0].get("score", 0) > 0.85:
                return results[0].get("metadata", {}).get("pattern")
        except Exception as e:
            logger.debug("Pinecone cache check failed: %s", e)
        return None
    
    async def _cache_pattern(self, task: str, project_type: str, files: List[GeneratedCode]):
        """Store generated pattern in Pinecone."""
        try:
            filenames = [f.filename for f in files]
            await pinecone_store.upsert(
                text=task,
                metadata={
                    "project_type": project_type,
                    "files": filenames,
                    "pattern": f"{project_type}: {', '.join(filenames[:3])}"
                }
            )
        except Exception as e:
            logger.debug("Pinecone upsert failed: %s", e)
