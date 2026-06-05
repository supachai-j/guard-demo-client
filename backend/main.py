import logging
import os
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from .database import engine
from .migrations import run_migrations
from .models import Base

# Configure logging to prevent blocking I/O issues
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

Base.metadata.create_all(bind=engine)
run_migrations()

app = FastAPI(title="Agentic Demo API", description="Backend API for the Agentic Demo application", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Path-scoped permissive CORS for the Anthropic gateway shim (/v1/*). Anthropic
# clients like Claude for Office run in a WebView and send a CORS preflight; the
# locked-down CORSMiddleware above only allows localhost, so it answers their
# OPTIONS with 400 and the browser reports "Load failed". The public gateway
# (api.portkey.ai) returns `Access-Control-Allow-Origin: *`, so we mirror that
# for /v1/* only — the Admin API's CORS posture is untouched. Added AFTER the
# CORSMiddleware so it sits outermost and short-circuits the /v1 preflight first.
@app.middleware("http")
async def _gateway_cors(request: Request, call_next):
    if not request.url.path.startswith("/v1/"):
        return await call_next(request)
    cors = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": request.headers.get("access-control-request-headers", "*"),
        "Access-Control-Max-Age": "600",
    }
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=cors)
    response = await call_next(request)
    for key, value in cors.items():
        response.headers[key] = value
    return response

# Serve the bundled fake-company brand assets (logos / hero images) used by
# the one-click scenario loader. Mounted at /static/fakecompanies/...
_fakecompanies_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fakecompanies")
if os.path.isdir(_fakecompanies_dir):
    app.mount("/static/fakecompanies", StaticFiles(directory=_fakecompanies_dir), name="fakecompanies")


# Route modules — each owns its own APIRouter with prefix. Add new endpoints
# in the matching module under backend/routes/, not here.
from .routes import anthropic_proxy as _anthropic_proxy_routes  # noqa: E402
from .routes import audit as _audit_routes  # noqa: E402
from .routes import auth as _auth_routes  # noqa: E402
from .routes import catalogs as _catalogs_routes  # noqa: E402
from .routes import chat as _chat_routes  # noqa: E402
from .routes import config as _config_routes  # noqa: E402
from .routes import conversations as _conversations_routes  # noqa: E402
from .routes import demo_prompts as _demo_prompts_routes  # noqa: E402
from .routes import lakera_legacy as _lakera_legacy_routes  # noqa: E402
from .routes import playbook_runs as _playbook_runs_routes  # noqa: E402
from .routes import playbooks as _playbooks_routes  # noqa: E402
from .routes import rag as _rag_routes  # noqa: E402
from .routes import recordings as _recordings_routes  # noqa: E402
from .routes import scenarios as _scenarios_routes  # noqa: E402
from .routes import system as _system_routes  # noqa: E402
from .routes import threat_lab as _threat_lab_routes  # noqa: E402
from .routes import tools as _tools_routes  # noqa: E402

app.include_router(_system_routes.router)
app.include_router(_auth_routes.router)
app.include_router(_config_routes.router)
app.include_router(_catalogs_routes.router)
app.include_router(_chat_routes.router)
app.include_router(_conversations_routes.router)
app.include_router(_rag_routes.router)
app.include_router(_demo_prompts_routes.router)
app.include_router(_tools_routes.router)
app.include_router(_scenarios_routes.router)
app.include_router(_lakera_legacy_routes.router)
app.include_router(_recordings_routes.router)
app.include_router(_playbooks_routes.router)
app.include_router(_playbook_runs_routes.router)
app.include_router(_audit_routes.router)
app.include_router(_threat_lab_routes.router)
app.include_router(_anthropic_proxy_routes.router)


# Re-export from the tiny config_redaction module so tests can import the
# mask list without loading the full FastAPI app (which pulls in chromadb +
# numpy, occasionally CPU-incompatible on CI).
from .config_redaction import redact_config as _config_response  # noqa: E402, F401
