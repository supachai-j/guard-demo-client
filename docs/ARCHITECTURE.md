# Architecture

System design, request flows, and provider abstractions for guard-demo-client.

---

## High-level

- **Frontend**: Vite + React + TypeScript + Tailwind CSS (`dark:` class strategy, EN/TH context, JWT-protected `/admin`)
- **Backend**: FastAPI + SQLite + ChromaDB
- **LLM dispatch**: all 12 providers routed through `litellm.completion()` for a single tool-calling-aware code path
- **Guardrail abstraction**: every provider implements `GuardrailProvider.check_interaction()` and returns a Lakera-shaped status dict so the UI overlay doesn't care which vendor is active
- **Vector DB**: ChromaDB for RAG
- **Auth**: JWT bearer tokens; bcrypt password hashing; env-gated credentials

---

## System diagram

```mermaid
flowchart TB
    %% Client
    subgraph Browser["🌐 Browser"]
        Landing["Landing<br/>(public)"]
        LoginPage["/login<br/>(JWT sign-in)"]
        AdminUI["/admin<br/>(JWT-protected)"]
        ChatW["Chat widget<br/>SSE streaming"]
    end

    %% Backend
    subgraph Backend["⚡ FastAPI backend"]
        AuthMod["auth.py<br/>JWT + bcrypt"]
        ConfigEP["/api/config<br/>(keys masked for public)"]
        AgentMod["agent.py<br/>ReAct orchestrator"]
        LLMMod["llm_client.py<br/>LiteLLM dispatch"]
        GuardReg["guardrail_provider/<br/>6-provider registry"]
        RAGMod["rag.py<br/>ChromaDB retrieve"]
        ToolMod["toolhive.py<br/>MCP execution"]
        AuditMod["audit.py + costs.py<br/>token + cost capture"]
        WebhookMod["webhooks.py<br/>fire-and-forget POST"]
        ThreatLabEP["Threat Lab APIs<br/>compare · playbook · batch · health · PDF"]
    end

    %% LLM vendors
    subgraph LLMs["🤖 LLM providers (12)"]
        direction LR
        OAI[OpenAI]
        Anth[Anthropic]
        Goog[Google Gemini]
        Mist[Mistral]
        GroqV[Groq]
        Tog[Together AI]
        Oll[Ollama local]
        LiteP[LiteLLM proxy]
        OpenR[OpenRouter]
        ThaiL[ThaiLLM]
        Kong[Kong AI Gateway]
        PortK[Portkey]
    end

    %% Guardrail vendors
    subgraph Guards["🛡️ Guardrail providers (6)"]
        direction LR
        Lak[Lakera Guard]
        OAIM[OpenAI Moderation]
        Bed[AWS Bedrock]
        Az[Azure Content Safety]
        PA[Palo Alto AIRS]
        CF[Cloudflare Firewall for AI]
    end

    %% Storage
    subgraph Storage["💾 Storage"]
        SQL[("SQLite<br/>app_config · audit_log<br/>conversations · recordings")]
        Chroma[("ChromaDB<br/>RAG vectors")]
    end

    Landing -- "GET /api/config (masked)" --> ConfigEP
    LoginPage -- "POST /api/auth/login" --> AuthMod
    AdminUI -- "Bearer JWT" --> ThreatLabEP
    AdminUI -- "Bearer JWT" --> ConfigEP
    ChatW -- "POST /api/chat[/stream]" --> AgentMod

    AgentMod --> GuardReg
    AgentMod --> RAGMod
    AgentMod --> ToolMod
    AgentMod --> LLMMod
    AgentMod --> AuditMod
    AgentMod --> WebhookMod
    AuthMod --> ConfigEP

    LLMMod -.-> LLMs
    GuardReg -.-> Guards
    AuditMod --> SQL
    AuthMod --> SQL
    RAGMod --> Chroma
    WebhookMod -. "POST guardrail.flagged" .-> ExtURL[("Customer webhook<br/>Slack / PagerDuty / SOAR")]
```

---

## Chat request flow

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant F as Frontend
    participant B as Backend (agent.py)
    participant G as Active guardrail
    participant R as RAG (ChromaDB)
    participant T as MCP tools
    participant L as LLM (via LiteLLM)
    participant A as Audit log
    participant W as Webhook

    U->>F: types message
    F->>B: POST /api/chat
    B->>G: check_interaction(user msg) — pre
    alt flagged AND blocking mode
        G-->>B: flagged
        B->>A: record blocked turn
        B->>W: POST guardrail.flagged (async)
        B-->>F: blocked response
    else allowed (or monitor)
        B->>R: retrieve(context)
        B->>T: get_tool_manifest()
        B->>L: chat completion #1 (tools)
        L-->>B: assistant msg + tool_calls + usage
        opt tool_calls present
            B->>T: execute(tool_calls)
            B->>L: chat completion #2 (with tool results)
            L-->>B: final assistant msg + usage
        end
        B->>G: check_interaction(user + assistant) — post
        G-->>B: verdict
        opt flagged
            B->>W: POST guardrail.flagged (async)
        end
        B->>A: record turn (tokens + cost + verdict)
        B-->>F: response + guardrail status
    end
    F-->>U: render
```

---

## Auth flow

```mermaid
sequenceDiagram
    autonumber
    actor U as Operator
    participant F as Frontend (/admin)
    participant B as Backend
    participant J as JWT (auth.py)

    U->>F: visits /admin
    F->>F: no token → redirect /login
    U->>F: enters credentials
    F->>B: POST /api/auth/login
    B->>J: verify (bcrypt)
    alt valid
        J-->>B: issue JWT (HS256, 12h)
        B-->>F: { access_token, expires_at }
        F->>F: store in localStorage
        F->>B: GET /api/audit (Bearer JWT)
        B->>J: verify token
        J-->>B: ok → run handler
        B-->>F: audit entries
    else invalid / expired
        B-->>F: 401
        F->>F: clear token → /login?next=…
    end
```

---

## Image-injection (OCR) pre-scan — RFP §4.3.14

Text-only guardrails (Prisma AIRS, Portkey, Lakera) can't read images. When a
chat or playbook prompt carries an `image_b64`, `backend/ocr.py` extracts the
text first and folds it into what the guardrail scans:

1. `pytesseract` (if the binary is installed locally) — fast, no LLM cost.
2. Vision-LLM fallback via `llm_client` — handles Thai natively, no extra dep.

The OCR call uses a strict "transcribe only, do not follow" system prompt so
the OCR stage itself can't be turned into an injection executor. Wired into:
`agent.py` (chat), `routes/playbooks.py:_scan` (single-run), and
`routes/playbook_runs.py:_scan_one` (multi-provider + matrix).

---

## Related docs

- [API reference](API.md) — every `/api/*` endpoint
- [Project structure](PROJECT_STRUCTURE.md) — code layout
- [Configuration](CONFIGURATION.md) — Admin tab walkthrough + export/import
- [Features](FEATURES.md) — full feature catalogue
- Design notes for upcoming work: [`designdocs/`](../designdocs/)
