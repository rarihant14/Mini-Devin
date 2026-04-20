# Mini Devin — Project Flow Documentation

## 📋 Table of Contents
1. [Application Startup Flow](#application-startup-flow)
2. [Request-Response Flow](#request-response-flow)
3. [Agent Pipeline Flow](#agent-pipeline-flow)
4. [Data Flow Architecture](#data-flow-architecture)
5. [Message Bus & Streaming](#message-bus--streaming)
6. [File Generation & Storage](#file-generation--storage)
7. [Component Interactions](#component-interactions)

---

## Application Startup Flow

### Entry Point: `app.py`

```
┌─────────────────────────────────────────────┐
│  User runs: python app.py                   │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  app.py:main()                              │
│  • Print banner                             │
│  • Load .env configuration                  │
│  • Check for missing API keys               │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  app.py:open_browser()                      │
│  • Start browser thread (2.5s delay)        │
│  • Open http://127.0.0.1:8000               │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  uvicorn.run()                              │
│  • Start FastAPI server                     │
│  • Listen on HOST:PORT (0.0.0.0:8000)       │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  backend.main:app.lifespan()                │
│  [STARTUP]                                  │
│  ├─ Initialize MessageBus (Redis/In-Memory) │
│  ├─ Initialize Pinecone Store               │
│  └─ Load all services                       │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  ✅ Server Ready                            │
│  http://127.0.0.1:8000                      │
│  API Docs: http://127.0.0.1:8000/docs       │
└─────────────────────────────────────────────┘
```

**Key Configuration (backend/core/config.py):**
- `GROQ_API_KEY`: LLM provider (required)
- `REDIS_URL`: Message queue (optional, falls back to in-memory)
- `PINECONE_API_KEY`: Vector store (optional, falls back to in-memory)
- `APP_HOST`: Server bind address (default: 0.0.0.0)
- `APP_PORT`: Server port (default: 8000)

---

## Request-Response Flow

### User submits a task via the frontend

```
┌──────────────────────────────────────────────┐
│  Frontend (index.html)                       │
│  • User enters task description              │
│  • POST /api/tasks                           │
└────────────────┬─────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────┐
│  API Endpoint: POST /api/tasks               │
│  (backend/api/routes.py)                     │
│                                              │
│  1. Validate TaskRequest                     │
│  2. Generate session_id (UUID)               │
│  3. Store session metadata                   │
│  4. Return TaskResponse with stream_url      │
│  5. Start background pipeline                │
└────────────────┬─────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────┐
│  Background Task: _run_pipeline_bg()         │
│  (backend/api/routes.py)                     │
│                                              │
│  1. Call run_pipeline(task, session_id)      │
│  2. Wait for final_state                     │
│  3. Save generated files to disk             │
│  4. Update session store                     │
│  5. Emit pipeline_complete event             │
└────────────────┬─────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────┐
│  Client listens to SSE stream:               │
│  /api/stream/{session_id}                    │
│                                              │
│  Receives events:                            │
│  • Agent start/progress updates              │
│  • Generated code snippets                   │
│  • Test results                              │
│  • Debug messages                            │
│  • Final review & artifacts                  │
└──────────────────────────────────────────────┘
```

---

## Agent Pipeline Flow

### The 5-Agent Processing Chain

```
┌────────────────────────────────────────────────────────────────┐
│                    PIPELINE ORCHESTRATION                      │
│                   (backend/pipeline.py)                        │
│                                                                │
│  Managed by: LangGraph StateGraph                             │
│  Input: PipelineState (task, plan, code, tests, etc.)         │
└────────────────┬───────────────────────────────────────────────┘
                 │
                 ▼
    ┌─────────────────────────────┐
    │ 1️⃣  PLANNER AGENT           │
    │ (backend/agents/planner.py) │
    ├─────────────────────────────┤
    │ • Analyzes task             │
    │ • Creates step-by-step plan │
    │ • Breaks down requirements  │
    │ • Sets goals & milestones   │
    └────────────┬────────────────┘
                 │
                 ▼
    ┌─────────────────────────────┐
    │ 2️⃣  CODE GENERATOR          │
    │ (backend/agents/code_gen)   │
    ├─────────────────────────────┤
    │ • Uses planner output       │
    │ • Generates complete code   │
    │ • Creates multiple files    │
    │ • Applies best practices    │
    └────────────┬────────────────┘
                 │
                 ▼
    ┌─────────────────────────────┐
    │ 3️⃣  TESTER AGENT            │
    │ (backend/agents/tester.py)  │
    ├─────────────────────────────┤
    │ • Creates test cases        │
    │ • Runs tests on code        │
    │ • Reports failures          │
    │ • Sets tests_passed flag    │
    └────────────┬────────────────┘
                 │
         ┌───────┴────────┐
         │                │
         ▼ (tests fail)   ▼ (tests pass)
    ┌──────────────┐  ┌──────────────┐
    │ 4️⃣  DEBUGGER │  │ 5️⃣ REVIEWER  │
    │              │  │ (conditional)│
    │ • Fix issues │  │              │
    │ • Max 2 iter │  │ • Reviews    │
    │              │  │ • Scores     │
    └──────┬───────┘  │ • Artifact   │
           │          │   prep       │
           └──────┬───┘              │
                  │                  │
                  ▼                  │
           ┌──────────────┐          │
           │ 5️⃣ REVIEWER  │          │
           │              │◄─────────┘
           │ • Final code │
           │ • Scores     │
           │ • Prepares   │
           │   artifacts  │
           └──────┬───────┘
                  │
                  ▼
         ┌─────────────────────┐
         │ Final PipelineState │
         │ with all artifacts  │
         └─────────────────────┘
```

**Agent Base Class (backend/agents/base.py):**

Each agent inherits from `BaseAgent` and has:
- **LLM**: ChatGroq (Groq API) with streaming support
- **Retry Logic**: Exponential backoff (configurable)
- **State Management**: Updates PipelineState
- **Event Emission**: Publishes progress via MessageBus
- **Error Handling**: Structured error recovery

---

## Data Flow Architecture

### Core Data Structure: PipelineState

```
PipelineState (backend/core/state.py)
│
├── task: str                          # Original user task
├── session_id: str                    # Unique session identifier
├── plan: str                          # Planner output
├── code_files: List[File]             # Generated code artifacts
│   ├── filename: str
│   ├── language: str
│   ├── content: str
│   └── ...
├── test_cases: str                    # Test code
├── tests_passed: bool                 # Test execution result
├── bugs_found: List[str]              # Debugger findings
├── total_retries: int                 # Debug iteration count
├── review_score: float                # Final quality score (0-100)
├── review_notes: str                  # Reviewer feedback
├── generated_files: List[File]        # All artifacts for download
├── start_time: datetime               # Session start
├── end_time: datetime                 # Session completion
├── status: AgentStatus                # Current execution status
└── errors: Dict[str, str]             # Error tracking per agent
```

**Agent Status Enum:**
```
PENDING     → Waiting to execute
RUNNING     → Currently executing
SUCCESS     → Completed successfully
FAILED      → Execution failed
SKIPPED     → Conditional skip
```

---

## Message Bus & Streaming

### Event Broadcasting Architecture

```
┌────────────────────────────────────┐
│   MessageBus (backend/core/queue)  │
│   Manages async events & streams   │
└────────────────┬───────────────────┘
                 │
         ┌───────┴───────┐
         │               │
         ▼               ▼
    ┌──────────┐    ┌──────────────┐
    │ Redis    │    │ In-Memory    │
    │ Queue    │    │ Queue        │
    │(optional)│    │(fallback)    │
    └────┬─────┘    └──────┬───────┘
         │                  │
         └──────┬───────────┘
                │
                ▼
    ┌──────────────────────────────┐
    │  Agent Event Publishing      │
    │                              │
    │ channel: stream:{session_id} │
    │                              │
    │ Event types:                 │
    │ • planner_started            │
    │ • plan_generated             │
    │ • code_generated             │
    │ • test_started               │
    │ • test_completed             │
    │ • debug_started              │
    │ • debug_completed            │
    │ • review_started             │
    │ • review_completed           │
    │ • pipeline_complete          │
    └──────────┬───────────────────┘
               │
               ▼
    ┌──────────────────────────────┐
    │  SSE Streaming to Client     │
    │  (Server-Sent Events)        │
    │                              │
    │  GET /api/stream/{session_id}│
    │                              │
    │  Real-time event updates     │
    │  in JSON format              │
    └──────────────────────────────┘
```

**Event Structure:**
```json
{
  "session_id": "uuid-xxx",
  "agent": "planner|code_generator|tester|debugger|reviewer",
  "event": "started|progress|completed|error",
  "data": { /* agent-specific payload */ },
  "ts": 1234567890.123
}
```

---

## File Generation & Storage

### Generated File Lifecycle

```
┌─────────────────────────────────┐
│  Code Generator Agent           │
│  Produces File objects          │
│  (filename, language, content)  │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  PipelineState.generated_files  │
│  Accumulates all artifacts      │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  After Pipeline Completion      │
│  _save_files_to_disk()          │
│  (backend/api/routes.py)        │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  Disk Storage Structure         │
│                                 │
│  generated_outputs/             │
│  └── {session_id}/              │
│      ├── file1.py               │
│      ├── file2.ts               │
│      ├── test_file1.py          │
│      └── README.md              │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  Session Store Update           │
│  (in-memory dict)               │
│                                 │
│  _sessions[session_id] = {      │
│    "status": "completed",       │
│    "files": [{                  │
│      "filename": "...",         │
│      "language": "...",         │
│      "saved_path": "..."        │
│    }, ...],                     │
│    "review_score": 85.5         │
│  }                              │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  Download Endpoint Ready        │
│  GET /api/download/{session_id} │
│                                 │
│  Returns ZIP archive of all     │
│  generated files                │
└─────────────────────────────────┘
```

---

## Component Interactions

### Full System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND LAYER                           │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  index.html / app.js                                     │  │
│  │  • Task input form                                       │  │
│  │  • Real-time SSE event listener                          │  │
│  │  • Progress display                                      │  │
│  │  • Code viewer                                           │  │
│  │  • Download button                                       │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────┬────────────────────────────────────────────┘
                     │ HTTP/REST/SSE
                     │
┌────────────────────▼────────────────────────────────────────────┐
│                       API LAYER (FastAPI)                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  backend/api/routes.py                                   │  │
│  │  • POST /api/tasks          → Start pipeline            │  │
│  │  • GET /api/stream/{id}     → SSE events                │  │
│  │  • GET /api/status/{id}     → Session status            │  │
│  │  • GET /api/download/{id}   → Download ZIP              │  │
│  │  • GET /api/files/{id}      → List files                │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────┬────────────────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
┌─────────────┐ ┌──────────┐ ┌──────────────┐
│  Pipeline   │ │ Message  │ │ File        │
│ Orchestrator│ │  Bus     │ │ Storage     │
│ (LangGraph) │ │(Redis/   │ │ (Disk)      │
│             │ │ In-Mem)  │ │             │
└──────┬──────┘ └──────┬───┘ └──────┬──────┘
       │               │            │
       ▼               ▼            ▼
    ┌─────────────────────────────────────┐
    │    AGENT LAYER (5-Agent Pipeline)   │
    │                                     │
    │  1. Planner (analyzes task)        │
    │  2. CodeGenerator (creates code)   │
    │  3. Tester (validates code)        │
    │  4. Debugger (fixes issues)        │
    │  5. Reviewer (scores & finalizes)  │
    │                                     │
    │  All use: Groq LLM + State mgmt    │
    └──────────────┬──────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ▼                     ▼
    ┌─────────────┐     ┌──────────────┐
    │ Pinecone    │     │ Agent Status │
    │ Vector Store│     │ & State Mgmt │
    │ (optional)  │     │              │
    └─────────────┘     └──────────────┘
```

---

## Request Lifecycle Example

### Complete flow for a single task submission:

```
T0:  User submits task "Create a Python API that adds two numbers"
     ↓
T1:  Frontend POST /api/tasks { task: "..." }
     ↓
T2:  Route handler:
     ├─ Generate session_id = "abc123"
     ├─ Create PipelineState(task, session_id)
     ├─ Store session metadata
     ├─ Return TaskResponse with stream_url
     └─ Start background: _run_pipeline_bg("abc123", task)
     ↓
T3:  User calls GET /api/stream/abc123 (opens SSE connection)
     ↓
T4:  Background task executes run_pipeline():
     │
     ├─ State → Planner Agent
     │  ├─ Analyzes task
     │  ├─ Generates plan (stored in state.plan)
     │  ├─ Emits: {"event": "plan_generated", ...}
     │  └─ MessageBus broadcasts to stream
     │
     ├─ State → CodeGenerator Agent
     │  ├─ Reads plan from state
     │  ├─ Generates API code files
     │  ├─ Updates state.generated_files
     │  ├─ Emits: {"event": "code_generated", ...}
     │  └─ MessageBus broadcasts to stream
     │
     ├─ State → Tester Agent
     │  ├─ Creates test cases
     │  ├─ Runs pytest/unittest
     │  ├─ Sets state.tests_passed = True/False
     │  ├─ Emits: {"event": "test_completed", ...}
     │  └─ MessageBus broadcasts to stream
     │
     ├─ Conditional: If tests_passed = False:
     │  │
     │  └─ State → Debugger Agent (max 2 iterations)
     │     ├─ Analyzes failures
     │     ├─ Updates state.generated_files (fixes)
     │     ├─ Increments state.total_retries
     │     ├─ Emits: {"event": "debug_completed", ...}
     │     └─ MessageBus broadcasts to stream
     │
     ├─ State → Reviewer Agent
     │  ├─ Reviews final code quality
     │  ├─ Calculates state.review_score (0-100)
     │  ├─ Creates state.review_notes
     │  ├─ Emits: {"event": "review_completed", ...}
     │  └─ MessageBus broadcasts to stream
     │
     └─ Final: Emit {"event": "pipeline_complete", ...}
     ↓
T5:  _run_pipeline_bg() saves files:
     ├─ For each generated_file:
     │  └─ Write to: generated_outputs/abc123/{filename}
     ├─ Update session store: _sessions["abc123"]
     └─ File list ready for download
     ↓
T6:  SSE connection receives "pipeline_complete" event
     ↓
T7:  Frontend displays:
     ├─ Final plan & code
     ├─ Test results
     ├─ Debug notes (if applicable)
     ├─ Review score & notes
     └─ Download button (GET /api/download/abc123)
     ↓
T8:  User clicks download → Receive ZIP of all files
```

---

## API Endpoints Reference

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/tasks` | Submit a new task (starts pipeline) |
| GET | `/api/stream/{session_id}` | SSE stream of pipeline events |
| GET | `/api/status/{session_id}` | Get current session status |
| GET | `/api/download/{session_id}` | Download generated files (ZIP) |
| GET | `/api/files/{session_id}` | List generated files metadata |
| GET | `/docs` | Interactive API documentation (Swagger UI) |
| GET | `/` | Serve frontend index.html |

---

## Environment Configuration

**Required (in `.env`):**
```
GROQ_API_KEY=your_groq_api_key_here
```

**Optional (with fallbacks):**
```
REDIS_URL=redis://localhost:6379       # Falls back to in-memory queue
PINECONE_API_KEY=your_pinecone_key     # Falls back to in-memory store
PINECONE_INDEX_NAME=mini-devin-index
PINECONE_ENVIRONMENT=us-east-1
```

**Server Configuration:**
```
APP_HOST=0.0.0.0                        # Bind address
APP_PORT=8000                           # Server port
```

---

## Error Handling & Recovery

- **Agent Failures**: Retry logic with exponential backoff (up to 3 times)
- **Test Failures**: Automatically route to Debugger (max 2 debug cycles)
- **Redis Unavailable**: Fall back to in-memory queue with warning
- **Pinecone Unavailable**: Fall back to in-memory vector store
- **File Save Errors**: Logged but non-blocking; session still completes
- **LLM Errors**: Propagated with session error tracking

---

## Performance Considerations

1. **Async/Await**: All operations are async-first for scalability
2. **Streaming**: SSE events provide real-time feedback without polling
3. **Background Tasks**: Pipeline runs off the request thread
4. **Session Isolation**: Each session has isolated state and file storage
5. **Message Bus**: Decouples agents from client; supports horizontal scaling
6. **File I/O**: Async file operations on disk

---

## Security Notes

- CORS enabled for all origins (configurable for production)
- Task input validated with min/max length constraints
- File paths sanitized to prevent directory traversal
- Session IDs are UUIDs (cryptographically random)
- Generated files stored in isolated per-session directories

