"""
Debugger Agent — Analyzes failed tests and applies targeted code fixes.
"""
from __future__ import annotations
import json
import re
import logging
from typing import List, Dict

from backend.agents.base import BaseAgent
from backend.core.state import AgentType, GeneratedCode, PipelineState, TestResult
from backend.core.queue import message_bus

logger = logging.getLogger(__name__)


class DebuggerAgent(BaseAgent):
    agent_type = AgentType.DEBUGGER
    system_prompt = """You are an expert software debugger and bug fixer.
Analyze failing tests and fix the underlying code issues.

Respond ONLY with valid JSON:
{
  "bugs_found": 3,
  "fixes": [
    {
      "issue": "Missing null check on user input",
      "severity": "high",
      "fix_description": "Added validation before processing",
      "affected_file": "main.py"
    }
  ],
  "updated_files": [
    {
      "filename": "main.py",
      "language": "python", 
      "description": "Fixed null check issue",
      "content": "# Complete fixed file content..."
    }
  ],
  "debug_summary": "Found and fixed 3 issues related to..."
}

If tests all pass, return bugs_found: 0, empty fixes and updated_files arrays."""

    async def process(self, state: PipelineState) -> PipelineState:
        failed_tests = [t for t in state.test_results if not t.passed]
        
        if not failed_tests:
            await message_bus.send_agent_event(
                state.session_id, self.agent_type.value, "no_bugs",
                {"message": "✅ No bugs to fix — all tests passing!"}
            )
            state.bugs_found = 0
            return state
        
        await message_bus.send_agent_event(
            state.session_id, self.agent_type.value, "thinking",
            {"message": f"🐛 Analyzing {len(failed_tests)} failing test(s)..."}
        )
        
        failed_summary = "\n".join([
            f"- FAIL: {t.test_name}\n  Output: {t.output}\n  Error: {t.error or 'N/A'}"
            for t in failed_tests
        ])
        
        code_context = "\n\n".join([
            f"=== {f.filename} ===\n{f.content[:800]}"
            for f in state.generated_files[:4]
        ])
        
        prompt = f"""Debug and fix the following failing tests:

PROJECT: {state.project_type}
TASK: {state.user_task}

FAILING TESTS:
{failed_summary}

CURRENT CODE:
{code_context}

Identify root causes and provide complete fixed file contents.
Return ONLY valid JSON as specified."""

        raw = await self.stream_llm(state, prompt)
        debug_data = self._parse_debug_output(raw)
        
        state.bugs_found = debug_data.get("bugs_found", 0)
        state.debug_fixes = [fix.get("issue", "") for fix in debug_data.get("fixes", [])]
        
        # Apply fixes — update existing files or add new ones
        updated = debug_data.get("updated_files", [])
        if updated:
            updated_map: Dict[str, GeneratedCode] = {
                f.filename: f for f in state.generated_files
            }
            for uf in updated:
                updated_map[uf.get("filename", "fix.py")] = GeneratedCode(
                    filename=uf.get("filename", "fix.py"),
                    language=uf.get("language", "python"),
                    content=uf.get("content", ""),
                    description=uf.get("description", "Debugger fix"),
                )
            state.generated_files = list(updated_map.values())
        
        await message_bus.send_agent_event(
            state.session_id, self.agent_type.value, "debug_complete",
            {
                "message": f"🔧 Fixed {state.bugs_found} bug(s): {', '.join(state.debug_fixes[:3])}",
                "bugs_found": state.bugs_found,
                "fixes": state.debug_fixes,
                "updated_files": [uf.get("filename") for uf in updated]
            }
        )
        
        logger.info("Debugger fixed %d bugs", state.bugs_found)
        return state
    
    def _parse_debug_output(self, raw: str) -> dict:
        for pattern in [r"```(?:json)?\s*([\s\S]+?)```", r"\{[\s\S]+\}"]:
            match = re.search(pattern, raw)
            if match:
                candidate = match.group(1) if "```" in pattern else match.group(0)
                try:
                    return json.loads(candidate.strip())
                except json.JSONDecodeError:
                    continue
        return {"bugs_found": 0, "fixes": [], "updated_files": [], "debug_summary": "Analysis complete"}
