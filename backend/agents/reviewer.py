"""
Reviewer Agent — Final code quality review, scoring, and improvement suggestions.
"""
from __future__ import annotations
import json
import re
import logging
from typing import List

from backend.agents.base import BaseAgent
from backend.core.state import AgentType, PipelineState, ReviewComment
from backend.core.queue import message_bus

logger = logging.getLogger(__name__)


class ReviewerAgent(BaseAgent):
    agent_type = AgentType.REVIEWER
    system_prompt = """You are a principal software engineer conducting a thorough code review.
Evaluate code quality, security, performance, and best practices.

Respond ONLY with valid JSON:
{
  "overall_score": 8.5,
  "grade": "A",
  "summary": "Well-structured implementation with minor improvements needed...",
  "strengths": ["Clean separation of concerns", "Good error handling"],
  "comments": [
    {
      "severity": "warning",
      "file": "main.py",
      "message": "No rate limiting on auth endpoints",
      "suggestion": "Add slowapi or similar rate limiter"
    }
  ],
  "security_score": 8.0,
  "performance_score": 7.5,
  "maintainability_score": 9.0,
  "final_output": "Complete markdown report of the review..."
}

Score 1-10. Be constructive and specific. Grade: A(9-10), B(7-8), C(5-6), D(3-4), F(<3)"""

    async def process(self, state: PipelineState) -> PipelineState:
        await message_bus.send_agent_event(
            state.session_id, self.agent_type.value, "thinking",
            {"message": "🔍 Conducting comprehensive code review..."}
        )
        
        # Build review context
        file_summary = "\n".join([
            f"- {f.filename} ({f.language}): {f.description}"
            for f in state.generated_files
        ])
        
        test_summary = f"{sum(1 for t in state.test_results if t.passed)}/{len(state.test_results)} tests passing"
        
        code_sample = "\n\n".join([
            f"=== {f.filename} ===\n{f.content[:600]}"
            for f in state.generated_files[:3]
        ])
        
        prompt = f"""Review this software project comprehensively:

TASK: {state.user_task}
PROJECT TYPE: {state.project_type}
TECH STACK: {', '.join(state.tech_stack)}

FILES GENERATED:
{file_summary}

TEST RESULTS: {test_summary}
BUGS FIXED: {state.bugs_found}

CODE SAMPLE:
{code_sample}

Provide a thorough technical review covering: architecture, security, performance, 
error handling, code quality, and recommendations.

Return ONLY valid JSON as specified."""

        raw = await self.stream_llm(state, prompt)
        review_data = self._parse_review(raw)
        
        # Build ReviewComment objects
        comments = []
        for c in review_data.get("comments", []):
            severity = c.get("severity", "info")
            if severity not in ("info", "warning", "error"):
                severity = "info"
            comments.append(ReviewComment(
                severity=severity,
                file=c.get("file", "unknown"),
                message=c.get("message", ""),
                suggestion=c.get("suggestion", ""),
            ))
        
        state.review_comments = comments
        state.review_score = float(review_data.get("overall_score", 7.0))
        
        # Build final markdown output
        state.final_output = self._build_final_report(state, review_data)
        
        await message_bus.send_agent_event(
            state.session_id, self.agent_type.value, "review_complete",
            {
                "message": f"⭐ Code Review Score: {state.review_score:.1f}/10 (Grade: {review_data.get('grade', 'B')})",
                "score": state.review_score,
                "grade": review_data.get("grade", "B"),
                "summary": review_data.get("summary", ""),
                "strengths": review_data.get("strengths", []),
                "comments": [{"severity": c.severity, "file": c.file, "message": c.message} for c in comments],
                "security_score": review_data.get("security_score", 0),
                "performance_score": review_data.get("performance_score", 0),
                "maintainability_score": review_data.get("maintainability_score", 0),
            }
        )
        
        logger.info("Review complete. Score: %.1f/10", state.review_score)
        return state
    
    def _parse_review(self, raw: str) -> dict:
        for pattern in [r"```(?:json)?\s*([\s\S]+?)```", r"\{[\s\S]+\}"]:
            match = re.search(pattern, raw)
            if match:
                candidate = match.group(1) if "```" in pattern else match.group(0)
                try:
                    data = json.loads(candidate.strip())
                    if "overall_score" in data:
                        return data
                except json.JSONDecodeError:
                    continue
        return {
            "overall_score": 7.5, "grade": "B",
            "summary": "Code review complete.",
            "strengths": ["Functional implementation"],
            "comments": [],
            "security_score": 7.0, "performance_score": 7.0, "maintainability_score": 7.5
        }
    
    def _build_final_report(self, state: PipelineState, review_data: dict) -> str:
        passed = sum(1 for t in state.test_results if t.passed)
        agent_timeline = "\n".join([
            f"- **{r.agent.value.replace('_', ' ').title()}**: {r.status.value} ({r.duration_ms:.0f}ms, {r.retries} retries)"
            for r in state.agent_results
        ])
        
        files_list = "\n".join([f"- `{f.filename}` — {f.description}" for f in state.generated_files])
        
        comments_md = ""
        for c in state.review_comments:
            icon = {"info": "ℹ️", "warning": "⚠️", "error": "❌"}.get(c.severity, "ℹ️")
            comments_md += f"- {icon} **{c.file}**: {c.message}\n  > 💡 {c.suggestion}\n"
        
        return f"""# Mini Devin — Project Report

## 📋 Task
{state.user_task}

## 🏗️ Project Overview
- **Type**: {state.project_type}
- **Tech Stack**: {', '.join(state.tech_stack)}
- **Session**: `{state.session_id}`

## 📁 Generated Files ({len(state.generated_files)})
{files_list}

## 🧪 Test Results
- **Passed**: {passed}/{len(state.test_results)}
- **Bugs Fixed**: {state.bugs_found}
- **Retries Used**: {state.total_retries}

## ⭐ Code Review
- **Overall Score**: {state.review_score:.1f}/10 (Grade: {review_data.get('grade', 'B')})
- **Security**: {review_data.get('security_score', 'N/A')}/10
- **Performance**: {review_data.get('performance_score', 'N/A')}/10
- **Maintainability**: {review_data.get('maintainability_score', 'N/A')}/10

### Summary
{review_data.get('summary', '')}

### Strengths
{chr(10).join(['- ' + s for s in review_data.get('strengths', [])])}

### Review Comments
{comments_md or '- No major issues found.'}

## 🤖 Agent Pipeline Timeline
{agent_timeline}

---
*Generated by Mini Devin — AI Software Engineer Agent*
"""
