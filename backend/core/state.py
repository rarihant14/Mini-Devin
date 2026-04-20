"""
Shared state models for the LangGraph multi-agent pipeline.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field
from enum import Enum
import time
import uuid


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"


class AgentType(str, Enum):
    TASK_PLANNER = "task_planner"
    CODE_GENERATOR = "code_generator"
    TESTER = "tester"
    DEBUGGER = "debugger"
    REVIEWER = "reviewer"


class SubTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str
    description: str
    agent: AgentType
    priority: int = 1
    depends_on: List[str] = []
    status: AgentStatus = AgentStatus.PENDING


class AgentResult(BaseModel):
    agent: AgentType
    status: AgentStatus
    output: str = ""
    error: Optional[str] = None
    retries: int = 0
    duration_ms: float = 0.0
    timestamp: float = Field(default_factory=time.time)


class GeneratedCode(BaseModel):
    filename: str
    language: str
    content: str
    description: str


class TestResult(BaseModel):
    test_name: str
    passed: bool
    output: str
    error: Optional[str] = None


class ReviewComment(BaseModel):
    severity: Literal["info", "warning", "error"]
    file: str
    message: str
    suggestion: str


class PipelineState(BaseModel):
    """Central LangGraph state object passed between agents."""
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_task: str = ""
    
    # Planning
    subtasks: List[SubTask] = []
    project_type: str = ""
    tech_stack: List[str] = []
    
    # Code generation
    generated_files: List[GeneratedCode] = []
    project_structure: Dict[str, Any] = {}
    
    # Testing
    test_results: List[TestResult] = []
    tests_passed: bool = False
    
    # Debugging
    debug_fixes: List[str] = []
    bugs_found: int = 0
    
    # Review
    review_comments: List[ReviewComment] = []
    review_score: float = 0.0
    final_output: str = ""
    
    # Pipeline tracking
    agent_results: List[AgentResult] = []
    current_agent: Optional[AgentType] = None
    pipeline_status: AgentStatus = AgentStatus.PENDING
    error_count: int = 0
    total_retries: int = 0
    
    # Streaming
    stream_chunks: List[str] = []
    
    class Config:
        use_enum_values = True
