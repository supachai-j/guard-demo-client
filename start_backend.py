#!/usr/bin/env python3
"""
Startup script for the Agentic Demo backend server.
"""

import uvicorn
import os
import sys

# Disable ChromaDB telemetry globally
os.environ["CHROMA_TELEMETRY_ENABLED"] = "false"

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Backend port — overridable via env so local dev can sidestep port-8000
# collisions (e.g. another project's uvicorn) without editing source. Compose
# threads the same env to the healthcheck + frontend proxy so a single
# `BACKEND_PORT=8001` flips everything consistently.
_BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8000"))

from backend.main import app

if __name__ == "__main__":
    print("🚀 Starting Agentic Demo Backend Server...")
    print(f"📍 Server will be available at: http://localhost:{_BACKEND_PORT}")
    print(f"📚 API documentation at: http://localhost:{_BACKEND_PORT}/docs")
    print("🔧 Admin interface at: http://localhost:3000/admin")
    print("🌐 Demo page at: http://localhost:3000")
    print("\n" + "="*50)

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=_BACKEND_PORT,
        reload=True,
        log_level="info"
    )

