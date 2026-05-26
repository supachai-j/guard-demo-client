# Features

Full catalogue of what the demo platform ships with. For the short pitch
see the [README](../README.md).

---

## Core platform

- **Skinnable B2B Landing Page** with customizable branding
- **AI Chatbot** with ReAct agent architecture and smart autocomplete
- **Multi-turn conversation memory** (history threaded into every turn)
- **Streaming chat** (SSE) with token-by-token rendering
- **One-click demo scenarios** — 4 fake-company personas (CredFlow, NimbusVault, SafeHarbor, Vitalis) swap branding + system prompt + demo prompts in a single click
- **Bilingual UI** — English / Thai toggle, with **Light / Dark** mode
- **Demo Prompt Corpus** with autocomplete (right-arrow trigger)
- **RAG System** supporting file uploads and AI-generated seed packs
- **MCP Tools** via ToolHive integration
- **Admin Console** with selective ZIP export/import (sections: appearance, LLM, security, RAG, demo prompts, tools)

## Multi-provider integrations

- **12 LLM providers**: OpenAI, Anthropic (Claude), Google (Gemini), Mistral, Groq, Together AI, Ollama (local), self-hosted LiteLLM proxy, OpenRouter, ThaiLLM (national Thai LLM gateway), Kong AI Gateway (self-hosted, OpenAI-compatible), Portkey AI Gateway
- **6 Guardrail providers**: Lakera Guard, OpenAI Moderation, AWS Bedrock Guardrails, Azure AI Content Safety, Palo Alto Prisma AIRS, Cloudflare Firewall for AI
- Per-provider key slots — switching providers does not require re-entering credentials
- Catalog-driven UI — dropdowns auto-populate from `/api/providers` and `/api/guardrail-providers`
- **Dedicated Providers tab** — enable/disable each LLM and guardrail provider, edit keys/base-URL/extra params inline via `EditProviderModal`
- **Demo-safe provider config lock** — read-only toggle that freezes the entire provider config (keys + enable flags) so demo audiences cannot mutate it from the UI

## Playground (Admin tab — single-shot + multi-turn bench)

- Pick any model × any guardrail and hold a conversation against the full agent pipeline (pre-guard → RAG → tools → LLM → post-guard)
- **Image upload + OCR pre-scan** — drop an image, OCR pulls embedded text, the extracted text is fed through the guardrail to catch image-encoded prompt injection (RFP §4.3.14)
- Each assistant turn shows its own verdict (FLAGGED/clean), per-detector breakdown, and any OCR-extracted text inline
- Client-held history — nothing persisted to DB / audit / conversation log; clear or refresh to wipe

## Threat Lab (Admin tab — 9 sub-panels)

- **Audit log** — every chat/guardrail call captured; CSV + PDF export for compliance demos
- **Cost** — per-provider token + spend dashboard (USD/M-token pricing table for 8 providers)
- **Guardrail compare** — fan one prompt to every configured guardrail in parallel, show per-vendor verdict + latency
- **Compare LLMs** — fan one prompt to N LLM providers in parallel (response + tokens + cost + latency)
- **Playbook runner & matrix** — run any playbook (OWASP LLM Top 10 2025 built-in; AIGW policy and POC checklist are opt-in seed scripts; custom) against a chosen guardrail set, or run **M playbooks × N providers** in one shot (concurrency throttled to 5 calls/provider). Each run is persisted with history + side-by-side compare across providers and exportable as CSV
- **Batch eval** — upload CSV of prompts (max 500), get per-prompt verdict matrix
- **Health** — ping every configured LLM + guardrail, return up/down + latency
- **Recordings** — capture a sequence of prompts and replay them through the current agent stack
- **Webhook** — POST to a URL (Slack, PagerDuty, SOAR) on every flagged event; built-in test button
- Plus from the landing page: **Lakera on vs off compare** modal (works for every guardrail provider) and **image moderation** via `POST /api/moderation/image`

## MCP tool controls (Admin → Tools)

- ToolHive integration for MCP connectors (HTTP or local servers)
- **Per-tool allow/deny** — discover each connector's exposed tools, toggle individual tools off without removing the connector (`disabled_tools` list per connector)
- **Per-connector AI Gateway routing** — route a connector's traffic through a named gateway (e.g. Kong key-auth) with a write-only `gateway_api_key` slot that is never echoed back from the API

## Admin authentication

- **JWT-based login** (`POST /api/auth/login`) — 12 h sessions; protects every mutating + sensitive admin endpoint
- **Sign-in screen** at `/login` with default-credentials warning banner
- **`GET /api/config` masks every credential** (`***`) for unauthenticated callers so anonymous visitors can't lift API keys via DevTools
- Env config: `ADMIN_USER`, `ADMIN_PASSWORD`, `JWT_SECRET`, `ADMIN_TOKEN_TTL_HOURS` (fallback `admin`/`admin` + per-process random secret for dev)

---

## Demo-time goodies

### Chat Interface

- Real-time chat with AI assistant
- **Streaming mode** (SSE) — token-by-token rendering, toggle below the input
- **Multi-turn memory** — `conversation_id` threaded automatically; "New chat" button to reset
- Smart autocomplete with demo prompt corpus
- Tool usage tracking
- Guardrail status overlay (works for every guardrail provider)
- Message history

### Guardrail integration

- Six interchangeable providers — switch from the Admin → Security dropdown
- Blocking vs Monitor mode applies to all providers
- LiteLLM-native Lakera guardrails when LiteLLM proxy is active
- Unified Lakera-shaped result dict so the UI overlay is provider-agnostic
- Per-detector breakdown with TL;DR summaries

### Compare on the Landing page

- Lakera-on vs Lakera-off side-by-side modal (`POST /api/chat/compare`)

### RAG capabilities

- Document upload (PDF, MD, TXT, CSV)
- AI-generated content creation
- Semantic search
- Content chunking and embedding

### Tool integration

- Calculator tool
- HTTP fetch tool
- Calendar lookup
- GitHub repository info
- Custom tool addition

### Demo Prompt Corpus

- Curated prompt library for consistent demos
- Category-based organization (general, security, tools, rag, malicious)
- Tag-based search and filtering
- Usage tracking and analytics
- Smart autocomplete in chat interface
- Right arrow key (→) completion trigger
- Visual indicators for malicious prompts
- Admin interface for prompt management

---

## Security features

- **JWT admin auth** with login screen — protects every mutating + sensitive endpoint
- **API key masking on public reads** — `GET /api/config` returns `"***"` for every credential field unless the caller presents a valid Bearer token
- **bcrypt password hashing** + per-process JWT secret fallback (override via `JWT_SECRET` env)
- **Audit log + webhook** — every flagged guardrail event captured and optionally POSTed to a customer-configured URL (Slack / PagerDuty / SOAR)
- **Image-injection mitigation (RFP §4.3.14)** — OCR pre-scan on attached images before any text-only guardrail call. Wired into chat, single-run playbooks, multi-provider playbooks, and matrix runs.
- Content moderation via any of 6 guardrail providers (Lakera / OpenAI Moderation / Bedrock / Azure / Palo Alto AIRS / Cloudflare Firewall for AI)
- Secure file upload validation
- Input sanitization
- CORS configuration
