"""
LangGraph pipeline that orchestrates all Mini Devin agents.
Implements the full: Plan → Generate → Test → Debug → Review flow
with async message passing and streaming.
"""
from __future__ import annotations
import logging
import asyncio
import time
from typing import Any, Dict, TypedDict

from langgraph.graph import StateGraph, END

from backend.agents.planner import TaskPlannerAgent
from backend.agents.code_generator import CodeGeneratorAgent
from backend.agents.tester import TesterAgent
from backend.agents.debugger import DebuggerAgent
from backend.agents.reviewer import ReviewerAgent
from backend.core.state import AgentStatus, PipelineState
from backend.core.queue import message_bus

logger = logging.getLogger(__name__)

# ─── LangGraph compatible state dict ───────────────────────────────────────────
class GraphState(TypedDict):
    pipeline_state: dict  # Serialized PipelineState


# ─── Agent instances (singleton) ───────────────────────────────────────────────
_planner = TaskPlannerAgent()
_code_gen = CodeGeneratorAgent()
_tester = TesterAgent()
_debugger = DebuggerAgent()
_reviewer = ReviewerAgent()


# ─── Node functions ─────────────────────────────────────────────────────────────

async def run_planner(state: GraphState) -> GraphState:
    ps = PipelineState(**state["pipeline_state"])
    ps = await _planner.run(ps)
    return {"pipeline_state": ps.model_dump()}


async def run_code_generator(state: GraphState) -> GraphState:
    ps = PipelineState(**state["pipeline_state"])
    ps = await _code_gen.run(ps)
    return {"pipeline_state": ps.model_dump()}


async def run_tester(state: GraphState) -> GraphState:
    ps = PipelineState(**state["pipeline_state"])
    ps = await _tester.run(ps)
    return {"pipeline_state": ps.model_dump()}


async def run_debugger(state: GraphState) -> GraphState:
    ps = PipelineState(**state["pipeline_state"])
    ps = await _debugger.run(ps)
    return {"pipeline_state": ps.model_dump()}


async def run_reviewer(state: GraphState) -> GraphState:
    ps = PipelineState(**state["pipeline_state"])
    ps = await _reviewer.run(ps)
    return {"pipeline_state": ps.model_dump()}


# ─── Conditional routing ────────────────────────────────────────────────────────

def should_debug(state: GraphState) -> str:
    """Route to debugger if tests failed, else skip to reviewer."""
    ps_data = state["pipeline_state"]
    tests_passed = ps_data.get("tests_passed", True)
    bugs_fixed = ps_data.get("total_retries", 0)
    
    # Only debug once to avoid infinite loops
    if not tests_passed and bugs_fixed < 2:
        return "debug"
    return "review"


# ─── Build the graph ────────────────────────────────────────────────────────────

def build_pipeline() -> StateGraph:
    graph = StateGraph(GraphState)
    
    # Add nodes
    graph.add_node("planner", run_planner)
    graph.add_node("code_generator", run_code_generator)
    graph.add_node("tester", run_tester)
    graph.add_node("debugger", run_debugger)
    graph.add_node("reviewer", run_reviewer)
    
    # Set entry point
    graph.set_entry_point("planner")
    
    # Linear flow with conditional debug
    graph.add_edge("planner", "code_generator")
    graph.add_edge("code_generator", "tester")
    graph.add_conditional_edges("tester", should_debug, {
        "debug": "debugger",
        "review": "reviewer"
    })
    graph.add_edge("debugger", "reviewer")
    graph.add_edge("reviewer", END)
    
    return graph.compile()


# Compiled pipeline singleton
_pipeline = None


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = build_pipeline()
    return _pipeline


# ─── Main execution function ────────────────────────────────────────────────────

async def run_pipeline(user_task: str, session_id: str) -> PipelineState:
    """
    Execute the full Mini Devin pipeline for a given task.
    Streams events via message_bus as it runs.
    """
    start = time.time()
    
    initial_state = PipelineState(
        session_id=session_id,
        user_task=user_task,
        pipeline_status=AgentStatus.RUNNING,
    )
    
    await message_bus.send_agent_event(
        session_id, "pipeline", "pipeline_start",
        {
            "message": "🚀 Mini Devin pipeline starting...",
            "task": user_task,
            "session_id": session_id,
        }
    )
    
    graph_input: GraphState = {"pipeline_state": initial_state.model_dump()}
    
    try:
        pipeline = get_pipeline()
        result = await pipeline.ainvoke(graph_input)
        
        final_state = PipelineState(**result["pipeline_state"])
        final_state.pipeline_status = AgentStatus.SUCCESS
        
        duration = time.time() - start
        await message_bus.send_agent_event(
            session_id, "pipeline", "pipeline_complete",
            {
                "message": f"🎉 Pipeline complete in {duration:.1f}s!",
                "session_id": session_id,
                "duration": duration,
                "files_generated": len(final_state.generated_files),
                "review_score": final_state.review_score,
                "final_output": final_state.final_output,
                "generated_files": [
                    {
                        "filename": f.filename,
                        "language": f.language,
                        "description": f.description,
                        "content": f.content,
                        "lines": len(f.content.splitlines()),
                    }
                    for f in final_state.generated_files
                ],
            }
        )
        
        logger.info("Pipeline complete for session %s in %.1fs", session_id, duration)
        return final_state
        
    except Exception as e:
        logger.error("Pipeline failed for session %s: %s", session_id, e, exc_info=True)
        initial_state.pipeline_status = AgentStatus.FAILED
        
        await message_bus.send_agent_event(
            session_id, "pipeline", "pipeline_error",
            {"message": f"❌ Pipeline failed: {str(e)}", "error": str(e)}
        )
        # Still emit complete so frontend doesn't hang
        await message_bus.send_agent_event(
            session_id, "pipeline", "pipeline_complete",
            {"message": "Pipeline ended with errors.", "error": str(e), "final_output": ""}
        )
        return initial_state
