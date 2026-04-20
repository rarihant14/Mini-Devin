"""
Mini Devin — Root Entry Point
Run: python app.py
Opens browser automatically and starts the FastAPI + Uvicorn server.
"""
import os
import sys
import time
import socket
import threading
import webbrowser

# Ensure project root is on sys.path
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from backend.core.config import settings

HOST = "127.0.0.1"
DISPLAY_URL = ""  # set after port is chosen


def find_free_port(start: int = 8000, end: int = 8020) -> int:
    """Find a free TCP port in range — avoids WinError 10048 (port in use)."""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((HOST, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {start}-{end}")


def open_browser(url: str):
    time.sleep(2.8)
    print(f"\n🌐 Opening browser at {url} ...\n")
    webbrowser.open(url)


def check_env():
    missing = []
    if not settings.groq_api_key or settings.groq_api_key == "your_groq_api_key_here":
        missing.append("GROQ_API_KEY")
    if missing:
        print("\n" + "=" * 60)
        print("⚠️  WARNING: Missing environment variables:")
        for m in missing:
            print(f"   - {m}")
        print("\n   Copy .env.example → .env and fill in your keys.")
        print("   Pinecone and Redis are optional (fallbacks built-in).")
        print("=" * 60 + "\n")


def print_banner():
    print("""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║        🤖  MINI DEVIN — AI Software Engineer            ║
║                                                          ║
║   Agents:  Task Planner → Code Generator → Tester       ║
║            → Debugger → Reviewer                        ║
║                                                          ║
║   Stack:   Groq · LangGraph · Pinecone · FastAPI        ║
║            Redis (optional) · SSE Streaming             ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
""")


def main():
    print_banner()
    check_env()

    port = find_free_port()
    url  = f"http://127.0.0.1:{port}"

    print(f"🚀 Starting server on {url}")
    print(f"📖 API Docs      : {url}/docs")
    print(f"🛑 Press Ctrl+C to stop\n")

    threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=HOST,
        port=port,
        reload=False,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
