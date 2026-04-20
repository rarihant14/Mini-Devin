# Mini Devin — Post-Mortem Document

## Project Overview
Mini Devin is a production-grade multi-agent AI system that autonomously plans, generates, tests, debugs, and reviews code for any software task. Built with Groq, LangGraph, Pinecone, FastAPI, and Redis.

---

## One Scaling Issue Encountered

### Issue: SSE Fan-out with In-Memory Queue

**What happened:**  
The Server-Sent Events (SSE) streaming relies on a publish/subscribe pattern implemented with `asyncio.Queue`. Each session creates a new subscriber queue in a Python dictionary. When multiple concurrent users submit tasks simultaneously, the message bus holds all subscriber queues in memory on a single process.

**Why it's a problem at scale:**  
- Under 100+ concurrent pipeline sessions, memory pressure increases linearly — each session maintains a live queue holding potentially thousands of stream chunks.
- More critically: if multiple FastAPI workers (Uvicorn with `workers=N`) are spawned, the in-memory pub/sub **breaks entirely**. Worker A runs the pipeline and publishes events to its own in-memory queue; Worker B handles the SSE GET request and listens on its own empty queue. The client receives nothing.
- Redis pub/sub solves this (the `RedisQueue` class is already implemented), but requires Redis to be running. In development with no Redis, the fallback silently isolates each worker.

**What we would do differently at scale:**  
Deploy Redis as the mandatory message broker (not optional). Use `redis.asyncio` with proper pub/sub channels keyed by `session_id`. Each Uvicorn worker subscribes to the same Redis channel, ensuring cross-worker event delivery. Additionally, add a circuit breaker: if Redis goes down mid-session, the SSE endpoint returns a 503 and the frontend reconnects with exponential backoff.

---

## One Design Decision We Would Change

### Decision: Serializing PipelineState Through LangGraph as a Dict

**What we did:**  
LangGraph requires its state to be a `TypedDict`. Since our `PipelineState` is a Pydantic `BaseModel`, we serialize it with `.model_dump()` before every node call and deserialize with `PipelineState(**state["pipeline_state"])` inside every node. This round-trips the entire state (potentially hundreds of KB of generated code) through JSON serialization on every graph edge.

**Why it's a problem:**  
- Every agent node pays a full serialization + deserialization cost, even for fields it doesn't touch (e.g., the Tester node re-serializes all generated code just to pass it to the Debugger).
- Pydantic validation runs on every deserialize, which adds CPU overhead and can mask bugs when invalid data silently coerces.
- The `generated_files` list containing full code file contents can grow to 50–200 KB, making each state transition expensive.

**What we would do instead:**  
Use LangGraph's native Pydantic state support (available in LangGraph 0.2+) by annotating `GraphState` as a `PipelineState` directly, or store large blobs (generated file contents) in Redis or a temp DB and pass only file IDs through the graph state. This keeps the graph state lightweight (< 1 KB per transition) while large artifacts live in external storage.

---

## Trade-offs Made During Development

### 1. Hash-based Embeddings vs. Real Embeddings (Pinecone)
**Trade-off:** We use a 128-dimensional SHA-256 hash-based embedding instead of real sentence embeddings (e.g., `text-embedding-3-small`) for Pinecone vector storage.  
**Why:** Avoids adding OpenAI or a separate embedding model as a dependency. Keeps the system self-contained and reduces API cost.  
**Cost:** Hash embeddings have zero semantic similarity — they only match *exact* text, not paraphrases. Two tasks like "Build a REST API" and "Create an HTTP API" would get completely different vectors and never match in cache lookup.  
**Production fix:** Replace `_embed()` in `pinecone_store.py` with `langchain_openai.OpenAIEmbeddings` or `sentence_transformers`.

### 2. Simulated Test Execution vs. Real Code Execution
**Trade-off:** The Tester agent asks the LLM to *simulate* test results rather than actually executing `pytest` in a subprocess.  
**Why:** Executing untrusted generated code in a subprocess is a significant security risk in a shared environment. It also requires the generated code's dependencies to be installed, which is non-trivial for arbitrary user tasks.  
**Cost:** Test pass/fail results are not ground truth — they reflect the LLM's confidence rather than actual runtime behavior.  
**Production fix:** Run generated code in isolated Docker containers (one per session) with a timeout. Use `subprocess.run(["pytest", "--tb=short"], capture_output=True, timeout=30)` inside the container and feed real output back to the Debugger.

### 3. In-Memory Session Store vs. Persistent DB
**Trade-off:** Active sessions are stored in a Python dict (`_sessions` in `routes.py`), which resets on server restart.  
**Why:** Simplicity. Adding SQLite or PostgreSQL for session persistence adds migration complexity and another dependency.  
**Cost:** Server restart loses all session history and in-flight pipelines. Users cannot resume a pipeline after a crash.  
**Production fix:** Use SQLite (via SQLAlchemy async) for session metadata and Redis for in-flight state. Add a `/api/sessions/{id}/result` endpoint that returns cached final outputs.

### 4. Single-pass Debug vs. Iterative Refinement Loop
**Trade-off:** The pipeline only runs the Debugger once. If the Debugger's fix introduces new bugs, those are not caught.  
**Why:** A naive loop (Test → Debug → Test → Debug...) can run indefinitely. Adding a retry counter to the graph state prevents infinite loops but adds complexity.  
**Cost:** ~10-15% of real-world cases would benefit from a second debug pass.  
**Production fix:** Add a `debug_attempts` counter to `PipelineState` and a loop edge from Reviewer back to Tester (max 2 iterations), conditioned on `review_score < 7.0`.

---

## Architecture Summary

```
User Task
   │
   ▼
[FastAPI POST /api/tasks]
   │ session_id
   ▼
[LangGraph Pipeline] ──────────────────────────────────
   │
   ├─ TaskPlannerAgent    (Groq llama3-70b) → subtasks, tech stack
   ├─ CodeGeneratorAgent  (Groq llama3-70b) → generated files, Pinecone cache
   ├─ TesterAgent         (Groq llama3-70b) → test results
   ├─ DebuggerAgent       (Groq llama3-70b) → bug fixes (conditional)
   └─ ReviewerAgent       (Groq llama3-70b) → score, comments, final report
        │
        ▼
   [MessageBus (Redis/InMemory)]
        │ SSE events
        ▼
   [Frontend SSE /api/stream/{session_id}]
        │
        ▼
   Browser UI (real-time streaming)
```

**Message Queue:** Redis pub/sub (in-memory fallback)  
**Vector DB:** Pinecone (in-memory fallback)  
**LLM:** Groq (llama3-70b-8192)  
**Orchestration:** LangGraph StateGraph with conditional edges  
**Streaming:** Server-Sent Events (SSE)  
**Retry:** Per-agent exponential backoff (max 3 attempts)
