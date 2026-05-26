# Project Structure

```
guard-demo-client/
├── backend/                       # FastAPI backend
│   ├── main.py                    # App factory, inline SQLite migrations, mounts routes/
│   ├── routes/                    # Per-domain route modules
│   │   ├── chat.py                # /api/chat, /chat/stream, /chat/compare-*
│   │   ├── config.py              # /api/config, export/import ZIP
│   │   ├── catalogs.py            # /api/providers, /guardrail-providers, /models
│   │   ├── tools.py               # /api/tools + MCP capabilities + disabled-tools + gateway routing
│   │   ├── playbooks.py           # /api/playbooks CRUD + run + CSV export (OCR-folds image_b64)
│   │   ├── playbook_runs.py       # /api/playbook-runs — history, multi-provider, matrix, compare
│   │   └── threat_lab.py          # /api/batch, /api/health/providers, /api/webhook/test, /api/moderation/image, /api/playground/run
│   ├── models.py                  # SQLAlchemy: AppConfig, Conversation, Message, AuditLog,
│   │                              #   SessionRecording, Tool, RagSource, DemoPrompt, Playbook, PlaybookRun
│   ├── schemas.py                 # Pydantic schemas
│   ├── database.py                # SQLite engine
│   ├── agent.py                   # ReAct agent (pre-guard → OCR → RAG → tools → LLM → post-guard)
│   ├── ocr.py                     # OCR pre-scan for image-embedded prompt injection (pytesseract → vision-LLM fallback)
│   ├── llm_client.py              # LiteLLM dispatch for all 12 providers + SSE streaming
│   ├── providers.py               # LLM provider catalog (OpenAI/Anthropic/.../ThaiLLM/Kong/Portkey)
│   ├── auth.py                    # JWT login + require_admin dependency
│   ├── costs.py                   # Per-provider pricing table + cost estimator
│   ├── webhooks.py                # Outbound webhook on guardrail.flagged events
│   ├── audit.py                   # Audit log writer + CSV + token/cost capture
│   ├── playbooks.py               # Built-in suite (OWASP LLM Top 10 2025 only — POC + AIGW live in scripts/)
│   ├── scenarios.py               # 4 one-click demo company personas
│   ├── rag.py                     # RAG service, ChromaDB
│   ├── lakera.py                  # Legacy Lakera REST client + UI state
│   ├── toolhive.py                # MCP tool execution + per-connector AI Gateway routing
│   └── guardrail_provider/        # Unified guardrail abstraction
│       ├── base.py                # GuardrailProvider ABC + Lakera-shaped status
│       ├── registry.py            # Catalog + active resolver + UI metadata
│       ├── lakera_provider.py
│       ├── openai_moderation_provider.py
│       ├── bedrock_provider.py    # AWS Bedrock Guardrails (ApplyGuardrail)
│       ├── azure_content_safety_provider.py  # text:analyze + text:shieldPrompt + image:analyze
│       ├── palo_alto_provider.py  # Prisma AIRS /v1/scan/sync/request
│       └── cloudflare_provider.py # Workers AI Llama Guard 3 (S1–S14 taxonomy)
├── src/                            # React frontend
│   ├── components/
│   │   ├── ChatWidget.tsx          # Chat + image upload + multimodal + stream toggle + conversation_id threading
│   │   ├── ThreatLab.tsx           # Admin tab: panels for audit/cost/compare/playbook matrix/run history/.../webhook
│   │   ├── Playground.tsx          # Admin tab: interactive multi-turn bench (client-held history, runs full agent pipeline)
│   │   ├── PlaybookManager.tsx     # Playbook CRUD + CSV export
│   │   ├── ToolManager.tsx         # MCP connectors + per-tool allow/deny + gateway routing
│   │   ├── EditProviderModal.tsx   # Inline per-provider key/base-URL editor (Providers tab)
│   │   ├── CompareDialog.tsx       # Active-guardrail-on vs off side-by-side
│   │   ├── ScenarioSwitcher.tsx    # One-click company logo bar
│   │   ├── UIToggles.tsx           # EN/TH + Light/Dark switches
│   │   ├── LakeraOverlay.tsx       # Per-detector verdict panel
│   │   ├── DemoPromptManager.tsx
│   │   └── RagManagement.tsx
│   ├── auth/
│   │   ├── AuthContext.tsx         # JWT token storage + login/logout helpers
│   │   └── ProtectedRoute.tsx      # Wraps /admin; redirects to /login when no token
│   ├── pages/                      # AdminConsole (12 tabs incl. Providers + Playground), LandingPage, Login
│   ├── services/api.ts             # Typed REST + SSE iterator + auto Bearer header
│   ├── i18n/                       # EN/TH dictionaries + UIContext + guardrailLabel
│   └── types/
├── data/                           # gitignored: SQLite DB + ChromaDB vectors (bind-mounted in docker-compose)
├── docs/                           # Project documentation — you are here
├── designdocs/                     # In-repo design notes (incl. MULTI_WORKSPACE_DESIGN.md for Phase 2)
├── fakecompanies/                  # Bundled logos + hero images + sample exports for scenarios
├── litellm/                        # LiteLLM proxy Dockerised config
├── scripts/                        # Setup + opt-in seed scripts:
│   ├── seed_aigw_policy_playbooks.py       # 9 AI Gateway policy playbooks
│   ├── seed_poc_verification_playbook.py   # POC verification checklist
│   ├── stop_demo_stack.sh
│   └── fresh_start_demo.sh
├── tests/                          # pytest suite (providers, playbook_runs, OCR, provider_config_lock, ...)
├── e2e/                            # Playwright smoke tests
├── .github/workflows/              # CI (ruff + pytest + deps audit + gitleaks) and docker.yml (GHCR publish)
├── requirements.txt
├── package.json
├── Dockerfile
├── docker-compose.yml              # Team-facing VPS deploy — `docker compose pull && up -d`
├── start_all.py                    # Start backend + frontend + LiteLLM (recommended for local dev)
├── start_backend.py                # Backend-only
└── README.md
```
