# 🚀 Mini Devin — AI Software Engineer Agent
---

A **multi-agent AI system** that autonomously plans, generates, tests, debugs, and reviews code for any software task.

---

## 🧠 Architecture

```
User Task → Task Planner → Code Generator → Tester → Debugger* → Reviewer
                                                        ↑ only if tests fail
```

---

## 🤖 Agents

| Agent             | Role                                   | Model                        |
| ----------------- | -------------------------------------- | ---------------------------- |
| 🧠 Task Planner   | Breaks task into subtasks + tech stack | Groq llama-3.3-70b-versatile |
| ⚙️ Code Generator | Generates production code files        | Groq llama-3.3-70b-versatile |
| 🧪 Tester         | Creates and simulates test suite       | Groq llama-3.1-8b-instant    |
| 🐛 Debugger       | Fixes failing tests (conditional)      | Groq llama-3.1-8b-instant    |
| 🔍 Reviewer       | Scores quality, security, performance  | Groq llama-3.3-70b-versatile |

---

## 🧱 Tech Stack

* **LLM**: [Groq](https://groq.com) — `llama-3.3-70b-versatile` (primary), `llama-3.1-8b-instant` (fast)
* **Orchestration**: [LangGraph](https://langchain-ai.github.io/langgraph/) — StateGraph with conditional edges
* **Vector DB**: [Pinecone](https://pinecone.io) — code pattern caching (in-memory fallback)
* **Message Queue**: Redis pub/sub — async agent communication (in-memory fallback)
* **API**: FastAPI + SSE streaming
* **Frontend**: Vanilla JS + CSS (dark terminal aesthetic)

---

## ⚡ Quick Start

## 1. Clone Repository

```bash
git clone https://github.com/rarihant14/Mini-Devin.git
cd Mini-Devin
```

### 2. Install dependencies

```bash
cd mini-devin
pip install -r requirements.txt
```

---

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and add your API keys
```

**Required:**

* `GROQ_API_KEY` — get free at https://console.groq.com

**Optional (fallbacks built-in):**

* `PINECONE_API_KEY` — for vector caching
* `REDIS_URL` — for production message queue

---

### 3. Run

```bash
python app.py
```

Open in browser:

```
http://localhost:8000
```

---

## 📂 Project Structure

```
mini-devin/
├── app.py                        # Entry point — launches server + browser
├── requirements.txt
├── .env.example
├── POST_MORTEM.md                # Required: scaling issues, design decisions
│
├── backend/
│   ├── __init__.py
│   ├── main.py                   # FastAPI app factory + lifespan
│   ├── pipeline.py               # LangGraph pipeline orchestration
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py               # BaseAgent: Groq LLM + retry + streaming
│   │   ├── planner.py            # Task Planner Agent
│   │   ├── code_generator.py     # Code Generator Agent
│   │   ├── tester.py             # Tester Agent
│   │   ├── debugger.py           # Debugger Agent
│   │   └── reviewer.py           # Reviewer Agent
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py             # Pydantic settings
│   │   ├── state.py              # PipelineState model (LangGraph state)
│   │   └── queue.py              # Redis/in-memory message bus
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   └── pinecone_store.py     # Pinecone vector store + fallback
│   │
│   └── api/
│       ├── __init__.py
│       └── routes.py             # FastAPI routes + SSE endpoint
│
└── frontend/
    ├── __init__.py
    ├── templates/
    │   └── index.html            # Main SPA
    └── static/
        ├── css/styles.css        # Dark terminal UI
        └── js/app.js             # SSE client + pipeline controller
```

---

## 🌐 API Endpoints

| Method | Endpoint                     | Description                     |
| ------ | ---------------------------- | ------------------------------- |
| POST   | `/api/tasks`                 | Submit a task, get `session_id` |
| GET    | `/api/stream/{session_id}`   | SSE stream of agent events      |
| GET    | `/api/sessions/{session_id}` | Session status                  |
| GET    | `/api/health`                | Health check                    |
| GET    | `/docs`                      | Swagger UI                      |

---

## ✨ Features

* ✅ **5-agent LangGraph pipeline** with conditional routing
* ✅ **Real-time SSE streaming** — watch agents work live
* ✅ **Redis message bus** with in-memory fallback
* ✅ **Pinecone vector cache** for code pattern reuse
* ✅ **Retry with exponential backoff** (3 attempts per agent)
* ✅ **Conditional debug loop** — only runs if tests fail
* ✅ **Code review scoring** — security, performance, maintainability
* ✅ **Full project report** in markdown

---


## 👨‍💻 Development Attribution

* 🤖 **100% UI** — Generated by AI (Frontend built autonomously)
* 👨‍💻 **Backend** — Developed by human 




## 🧪 Example Tasks

* "Build a REST API for a todo app with JWT authentication and SQLite"
* "Create a Python web scraper with rate limiting and CSV export"
* "Build a real-time chat backend with WebSockets and Redis pub/sub"
* "Create a CLI tool for managing environment variables with encryption"

