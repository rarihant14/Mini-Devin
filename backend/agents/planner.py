"""
Task Planner Agent — Analyzes user task, breaks into subtasks, identifies tech stack.
"""
from __future__ import annotations
import json
import re
import logging
from typing import List

from backend.agents.base import BaseAgent
from backend.core.state import AgentType, PipelineState, SubTask

logger = logging.getLogger(__name__)


class TaskPlannerAgent(BaseAgent):
    agent_type = AgentType.TASK_PLANNER
    system_prompt = """You are an expert software architect and task planner. 
Your job is to analyze a user's software development request and break it into clear, actionable subtasks.

You must respond ONLY with valid JSON. No markdown, no explanation, just raw JSON.

Format:
{
  "project_type": "REST API / Web App / CLI Tool / etc.",
  "tech_stack": ["FastAPI", "SQLite", "JWT", "etc."],
  "subtasks": [
    {
      "title": "Setup project structure",
      "description": "Create folder layout, init files, requirements",
      "agent": "code_generator",
      "priority": 1,
      "depends_on": []
    }
  ],
  "summary": "Brief project overview"
}

Agent values must be one of: code_generator, tester, debugger, reviewer
Order subtasks by logical dependency and priority (1=highest).
Be specific and comprehensive."""

    async def process(self, state: PipelineState) -> PipelineState:
        prompt = f"""Analyze this software task and produce a structured plan:

TASK: {state.user_task}

Break this into 6-10 specific subtasks covering:
- Project/file structure setup
- Core backend/API implementation  
- Authentication/security (if needed)
- Database models and operations
- Error handling and validation
- Unit tests
- Code review and optimization

Remember: respond ONLY with valid JSON."""

        await self._emit_thinking(state, "🧠 Analyzing task requirements...")
        raw = await self.stream_llm(state, prompt)
        
        # Parse JSON robustly
        plan = self._parse_json(raw)
        
        state.project_type = plan.get("project_type", "Software Project")
        state.tech_stack = plan.get("tech_stack", [])
        
        subtasks = []
        for i, st in enumerate(plan.get("subtasks", [])):
            subtasks.append(SubTask(
                title=st.get("title", f"Task {i+1}"),
                description=st.get("description", ""),
                agent=AgentType(st.get("agent", "code_generator")),
                priority=st.get("priority", i + 1),
                depends_on=st.get("depends_on", []),
            ))
        
        state.subtasks = subtasks
        logger.info("Planner created %d subtasks for: %s", len(subtasks), state.project_type)
        return state
    
    def _parse_json(self, raw: str) -> dict:
        """Extract JSON from LLM response robustly."""
        # Try direct parse
        try:
            return json.loads(raw.strip())
        except json.JSONDecodeError:
            pass
        
        # Try extracting from code block
        match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass
        
        # Try finding raw JSON object
        match = re.search(r"\{[\s\S]+\}", raw)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        
        logger.warning("Could not parse planner JSON, using fallback plan")
        return self._fallback_plan()
    
    def _fallback_plan(self) -> dict:
        return {
            "project_type": "Software Project",
            "tech_stack": ["Python", "FastAPI"],
            "subtasks": [
                {"title": "Generate core code", "description": "Generate main application code", "agent": "code_generator", "priority": 1, "depends_on": []},
                {"title": "Write tests", "description": "Write unit tests", "agent": "tester", "priority": 2, "depends_on": []},
                {"title": "Review code", "description": "Review for quality", "agent": "reviewer", "priority": 3, "depends_on": []},
            ],
            "summary": "Software project"
        }
    
    async def _emit_thinking(self, state: PipelineState, msg: str):
        from backend.core.queue import message_bus
        await message_bus.send_agent_event(
            state.session_id, self.agent_type.value, "thinking", {"message": msg}
        )
