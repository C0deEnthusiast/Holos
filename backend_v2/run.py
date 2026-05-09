"""
Entry point for the FastAPI v2 backend.

Run with:
    python backend_v2/run.py           # dev (reload on change)
    uvicorn backend_v2.main:app --host 0.0.0.0 --port 8001   # prod
"""
import sys
import os

# Ensure the project root is on sys.path so `backend_v2` is importable
# both in the main process and in uvicorn's reloader subprocess.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "backend_v2.main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info",
    )
