# API Reference

All API routes are under the `/api` prefix. Endpoints marked **🔒** require a
valid Bearer token from `POST /api/auth/login`.

Live OpenAPI schema + Swagger UI: `http://localhost:8000/docs`.

---

## Auth

- `GET /api/auth/status` — Public — is admin auth enabled, default-creds warning
- `POST /api/auth/login` — Public — `{ username, password }` → `{ access_token, expires_at, user }`
- `GET /api/auth/me` — 🔒 Current session info
- `POST /api/auth/logout` — 🔒 No-op server side; client drops token

## Config

- `GET /api/config` — Public; **API keys masked** (`***`) unless caller is authenticated
- `PUT /api/config` — 🔒 Update configuration
- `GET /api/config/export` — 🔒 Export config as a **ZIP** (query: `?include=appearance,llm,...&version=2`)
- `POST /api/config/import` — 🔒 Import config from an exported ZIP (merge by section)

## Catalogs (drive the Admin dropdowns)

- `GET /api/providers` — Available LLM providers (12)
- `GET /api/guardrail-providers` — Available guardrail providers (6)
- `GET /api/models` — Models for the active LLM provider (dynamic for proxy/Ollama, else static)

## Chat

- `POST /api/chat` — Public — Send a message; returns response + guardrail status + `conversation_id`
- `POST /api/chat/stream` — Public — Streaming SSE variant (events: `chunk`, `done`, `blocked`, `error`)
- `POST /api/chat/compare` — Public — Run the same prompt with guardrail on **and** off (works for every active guardrail), return both panes
- `POST /api/chat/compare-guardrails` — 🔒 Fan one prompt to every configured guardrail in parallel
- `POST /api/chat/compare-llms` — 🔒 Fan one prompt to N LLM providers in parallel; returns response + tokens + latency + cost per provider

## Conversations (multi-turn memory)

- `GET /api/conversations` — 🔒
- `GET /api/conversations/{id}` — 🔒 Full message history
- `DELETE /api/conversations/{id}` — 🔒

## Audit log

- `GET /api/audit?limit=200&flagged_only=true` — 🔒 JSON entries
- `GET /api/audit?format=csv` — 🔒 CSV export attachment
- `GET /api/audit/cost-summary` — 🔒 Per-provider tokens + estimated USD spend
- `GET /api/audit/report.pdf` — 🔒 Printable PDF summary (reportlab)
- `DELETE /api/audit` — 🔒 Wipe entries (admin / demo-reset only)

## Guardrails

- `GET /api/lakera/last` — Public — Last Lakera result (legacy frontend overlay)
- `POST /api/moderation/image` — 🔒 Scan an image with the active guardrail (`{ image_data_url }`)
- `GET /api/health/providers` — 🔒 Ping every configured LLM + guardrail, return up/down + latency

## Playbooks (security suites)

- `GET /api/playbooks` — Public — Catalog (OWASP LLM Top 10 2025 built-in; AIGW policy + POC verification opt-in via `scripts/seed_*.py`; user-defined)
- `GET /api/playbooks/{id}` — Public — Single playbook detail
- `GET /api/playbooks/{id}/export` — Public — Export the playbook's prompts as **CSV**
- `POST /api/playbooks` — 🔒 Create custom playbook
- `PUT /api/playbooks/{id}` — 🔒 Update playbook
- `DELETE /api/playbooks/{id}` — 🔒
- `POST /api/playbooks/{id}/run` — 🔒 Score every prompt through the selected guardrail(s) (OCR-folds attached `image_b64` items into the scan — §4.3.14)

## Playbook runs (history + matrix + compare)

- `GET /api/playbook-runs` — 🔒 List past runs (filterable by playbook + provider)
- `POST /api/playbook-runs/multi-provider` — 🔒 Fan one playbook to N providers (concurrency throttled to 5/provider; OCR pre-scan on image-bearing items)
- `POST /api/playbook-runs/matrix` — 🔒 **Matrix run** — M playbooks × N providers in one shot
- `GET /api/playbook-runs/compare` — 🔒 Side-by-side compare across providers for a given run set
- `GET /api/playbook-runs/{run_id}` — 🔒 Full per-prompt verdict matrix
- `PATCH /api/playbook-runs/{run_id}` — 🔒 Edit run metadata (title/notes)
- `DELETE /api/playbook-runs/{run_id}` — 🔒

## Playground

- `POST /api/playground/run` — 🔒 Single-turn or multi-turn (client-held history) call through the full agent pipeline with chosen model + guardrail; runs OCR on attached images before guardrail. Does **not** persist to conversations / audit log.

## Batch eval

- `POST /api/batch/run` — 🔒 Upload CSV of prompts (column `prompt` or one-per-line, max 500); return verdict matrix

## Recordings (demo replay)

- `GET /api/recordings` — 🔒 List
- `POST /api/recordings` — 🔒 Save `{ name, events }`
- `GET /api/recordings/{id}` — 🔒 Full payload
- `POST /api/recordings/{id}/replay` — 🔒 Re-run every prompt through the current agent
- `DELETE /api/recordings/{id}` — 🔒

## Webhooks

- `POST /api/webhook/test` — 🔒 Fire a `guardrail.test` event to a URL to verify integration; the saved `webhook_url` is fired automatically on every `guardrail.flagged` event

## Scenarios (one-click company switcher)

- `GET /api/scenarios` — Public — List previews
- `POST /api/scenarios/{id}/apply` — 🔒 Apply branding + prompts

## RAG

- `POST /api/rag/upload` — Upload documents
- `POST /api/rag/generate` — Generate AI content
- `GET /api/rag/search` — Search stored content

## Tools (MCP connectors)

- `GET /api/tools` — Public — List tools (used by chat tool manifest)
- `POST /api/tools` — 🔒 Create tool
- `PUT /api/tools/{id}` — 🔒 Update tool (incl. per-connector AI Gateway routing — `gateway_id`, write-only `gateway_api_key`)
- `DELETE /api/tools/{id}` — 🔒 Delete tool
- `POST /api/tools/test/{id}` — 🔒 Test tool (rediscovers MCP capabilities)
- `GET /api/tools/{id}/capabilities` — Public — List the tools/methods this MCP connector exposes, plus any items currently disabled
- `PATCH /api/tools/{id}/disabled-tools` — 🔒 Update the per-tool allow/deny list on this MCP connector

## Demo Prompts

- `GET /api/demo-prompts` — Public — List demo prompts (chat widget reads this)
- `GET /api/demo-prompts/search` — Public — Search with autocomplete suggestions
- `POST /api/demo-prompts` — 🔒 Create
- `PUT /api/demo-prompts/{id}` — 🔒 Update
- `DELETE /api/demo-prompts/{id}` — 🔒 Delete
- `POST /api/demo-prompts/{id}/use` — Public — Track usage (called from chat widget)
