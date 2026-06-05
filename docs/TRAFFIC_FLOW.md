# Traffic flow (Portkey gateway egress)

How a chat request travels end-to-end when the active LLM provider is
**Portkey**. This complements the generic
[Chat request flow](ARCHITECTURE.md#chat-request-flow) in `ARCHITECTURE.md`
by showing the parts that diagram abstracts away: the Portkey gateway hop, the
headers `llm_client` injects, the config-driven model override, and the two
independent guardrail layers.

> Reflects the live integration: `llm_provider=portkey`,
> `portkey_config=pc-guardr-43a76e` (Prisma AIRS guardrails, **monitor mode** —
> `deny:false`) **+** `portkey_virtual_key=gemini-25-flash-fc331e` →
> `gemini-2.5-flash`. A guardrail-only config has no model target, so it needs a
> virtual key alongside it. Use the config **slug** (`pc-...`), not its display
> name. Swap the config / virtual key and only the **Portkey gateway** box
> changes — the rest of the path is identical.

---

## End-to-end path

```mermaid
flowchart TB
    subgraph Client["🌐 Client"]
        BR["Browser :3000<br/>chat widget"]
    end

    subgraph Edge["🚪 Dev edge"]
        VITE["Vite dev server :3000<br/>proxy /api → :8000<br/>(prod: one container)"]
    end

    subgraph BE["⚡ FastAPI backend :8000"]
        CHAT["routes/chat.py<br/>POST /api/chat"]
        AGENT["agent.py · run_agent()<br/>0 pre-guard → 1 RAG → 2 tools<br/>3 build msgs → 4 LLM → 5 post-guard → 6 audit"]
        GUARD["guardrail_provider/<br/>Prisma AIRS · app-level"]
        LLM["llm_client.py:212<br/>build Portkey kwargs"]
    end

    subgraph GW["🛡️ Portkey gateway · api.portkey.ai"]
        CFG["config (slug pc-...)<br/>e.g. pc-guardr-43a76e → Prisma AIRS guardrails (monitor)<br/>+ virtual key gemini-25-flash-fc331e → gemini-2.5-flash<br/>(config may add timeout/fallback/cache/model override)"]
    end

    subgraph UP["🤖 Upstream LLM"]
        GEM["Google Gemini<br/>gemini-2.5-flash"]
    end

    BR -->|"POST /api/chat"| VITE --> CHAT --> AGENT
    AGENT <-->|"pre + post check_interaction"| GUARD
    AGENT -->|"chat_completion()"| LLM
    LLM -->|"litellm → POST /v1/chat/completions<br/>x-portkey-api-key<br/>x-portkey-config<br/>x-portkey-virtual-key<br/>x-portkey-metadata"| CFG
    CFG -->|"routed request"| GEM

    GEM -.->|"completion"| CFG
    CFG -.->|"OpenAI-shaped<br/>provider=google"| LLM
    LLM -.-> AGENT -.-> CHAT -.-> VITE -.-> BR
```

---

## Request lifecycle (sequence)

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant F as Frontend :3000
    participant B as Backend agent.py
    participant G as App guardrail (AIRS)
    participant L as llm_client + litellm
    participant P as Portkey gateway
    participant M as Gemini

    U->>F: type message
    F->>B: POST /api/chat (proxied :3000 → :8000)
    B->>G: check_interaction(user) — pre
    Note over G: AIRS auth 403 → fail-open<br/>(monitor: log & continue)
    G-->>B: verdict (not blocked)
    B->>B: RAG retrieve + tools manifest + build messages
    B->>L: chat_completion(model, msgs, config)
    L->>P: POST /v1/chat/completions (+ x-portkey-api-key / -config / -metadata)
    Note over P: apply config pc-guardr-43a76e (Prisma AIRS guardrails)<br/>+ virtual key → gemini-2.5-flash<br/>(guardrail monitor-mode: scores, does not block)
    P->>M: routed request
    M-->>P: completion
    P-->>L: OpenAI-shaped response (provider=google)
    L-->>B: assistant message + usage
    opt tool_calls present
        B->>B: execute MCP tools (ToolHive)
        B->>L: chat_completion #2 (with tool results)
        L->>P: POST /v1/chat/completions (again)
        P->>M: routed request
        M-->>P: completion
        P-->>L: response
        L-->>B: final assistant message
    end
    B->>G: check_interaction(user + assistant) — post
    G-->>B: verdict
    B->>B: persist + audit (tokens/cost) + webhook if flagged
    B-->>F: ChatResponse {response, lakera, ...}
    F-->>U: render
```

---

## Two guardrail layers (independent)

Portkey is purely the **LLM egress** layer — it slots in at step 4
(`llm_client.py:212`). Guardrails can run in two separate places:

```mermaid
flowchart LR
    IN["user input"] --> AG1["App AIRS guard · pre<br/>agent.py:170"]
    AG1 --> PKG["Portkey gateway<br/>(optional: Portkey AIRS guard) → LLM"]
    PKG --> AG2["App AIRS guard · post<br/>agent.py:355"]
    AG2 --> OUT["response to user"]
```

- **App-level** (Prisma AIRS) — runs inside `run_agent` around the whole prompt
  (pre at `agent.py:170`, post at `agent.py:355`). Gated by the `lakera_enabled`
  master toggle. *Currently the AIRS key auth-fails (403) and fails open — it
  logs but does not block.*
- **Portkey-level** (optional) — if the active config declares
  `input_guardrails` / `output_guardrails` (e.g. `pc-guardr-43a76e` →
  `pg-prisma-c06001`), the guardrail runs **inside the gateway**, wrapping the
  LLM call, with no AIRS key needed in the app.

---

## Notes

- **Config override**: with a config that sets `override_params.model`, the
  body `model` the app sends (`openai_model`) is replaced by the gateway — so
  sending `gpt-4o` still served `gemini-2.5-flash` in testing. The app-side
  `openai_model` is cosmetic on the config path.
- **No UA workaround needed**: litellm's `OpenAI/Python` User-Agent passes
  Portkey's Cloudflare; only the bare `Python-urllib` UA gets a 1010 block
  (unlike the ThaiLLM branch, which does override the UA — `llm_client.py:182`).
- **Header construction**: `x-portkey-config` / `x-portkey-metadata` are built
  by `_portkey_header_value()` (`llm_client.py`), which compacts inline JSON so
  it is header-safe; a bare `pc-...` slug passes through.

## Related docs

- [Architecture](ARCHITECTURE.md) — system diagram, generic chat flow, auth flow
- [Configuration](CONFIGURATION.md) — Admin tab walkthrough (Providers → Portkey)
- [API reference](API.md) — `/api/chat` and `/api/config`
