# Configuration

End-to-end walkthrough of the Admin Console, plus export/import.

The Admin Console lives at `http://localhost:3000/admin` (or wherever you
mapped port 3000). You'll be bounced to `/login` first — sign in with
`ADMIN_USER` / `ADMIN_PASSWORD` from `.env`, or with the dev fallback
`admin` / `admin` if you haven't set credentials (the login screen warns
you in that case).

---

## Initial setup checklist

1. **Sign in** at `/login`.
2. **Providers tab** — single source of truth for keys, base URLs, and which providers are enabled.
   - Enable the LLM provider(s) you want to use and click "Edit" to enter their API key / base URL. Slots are kept per provider so you can pre-stage several and switch live.
   - Enable any Guardrail provider(s) and enter their credentials (Lakera, OpenAI Moderation, Bedrock, Azure Content Safety, Palo Alto AIRS, Cloudflare Firewall for AI).
   - Optional: toggle **"Provider config locked"** (demo-safe mode) to make the whole tab read-only for the rest of the demo.
3. **LLM tab** — pick the active model + temperature + system prompt. This tab is settings only; keys live in Providers.
4. **Security tab** — pick the active guardrail + mode (Block / Monitor). Behavior only; guardrail keys live in Providers.
5. **LiteLLM + Lakera (optional)** — if using the LiteLLM proxy with Lakera guardrails, set guardrail names in Admin → Security to match `litellm/config.yaml`:
   - blocking: `lakera-guard-block`
   - monitor: `lakera-guard-monitor`
6. **Threat Lab tab (optional)** — audit log, cost dashboard, guardrail compare, LLM compare, playbook runner, matrix run, run history, batch eval, provider health, recordings, webhook config.
7. **Playground tab (optional)** — interactive bench: pick a model × guardrail, attach an image (auto-OCR for image-encoded prompt injection), hold a multi-turn conversation through the full agent pipeline without writing to the audit log.

---

## One-click demo personas

The Landing page has four logo buttons (CredFlow, NimbusVault, SafeHarbor,
Vitalis). Clicking one swaps branding + system prompt + the entire demo
prompt corpus in a single API call — useful when running back-to-back demos
for different verticals.

## EN/TH and Light/Dark

Top-right of every page: language segmented control (EN/TH) and a sun/moon
button. Both persist via `localStorage` and survive reloads.

---

## Per-tab settings

### Branding

- Business name + tagline
- Logo + hero image upload
- Hero text customization

### LLM

- Provider selection (12 options) — see [Architecture → System diagram](ARCHITECTURE.md#system-diagram)
- Model dropdown (auto-populated from `/api/models` for the active provider)
- Temperature (0–10 scale)
- System prompt

### RAG

- Document upload (PDF, MD, TXT, CSV)
- AI-generated seed packs
- View ingested content

### Tools (MCP)

- Add custom tools
- Configure MCP endpoints (HTTP or local servers)
- Per-tool allow/deny inside each connector (toggle individual tools off without removing the connector)
- Per-connector AI Gateway routing (e.g. Kong key-auth) with a write-only `gateway_api_key` slot
- Test tool functionality

### Demo Prompts

- Create curated demo prompts per scenario
- Organize by category (general, security, tools, rag, malicious)
- Set a **preferred LLM** per prompt (chat uses that model when the prompt is selected)
- Tag-based search
- Mark prompts as malicious for security testing
- Usage statistics

**Chat autocomplete:**
- Start typing in chat (minimum 2 characters)
- Real-time suggestions overlay
- **Right arrow key (→)** completes the current suggestion
- Click suggestions in the dropdown to select
- Escape dismisses suggestions

---

## Playbooks

- **OWASP LLM Top 10 (2025)** — built-in, available in every deploy.
- **POC Verification Checklist** — opt-in via `python scripts/seed_poc_verification_playbook.py`.
- **AI Gateway policy suites (§1–§7, §9, §10)** — opt-in via `python scripts/seed_aigw_policy_playbooks.py`.
- **Custom** — create from the Admin → Playbooks UI; lives in the same `playbooks` DB table as the seeded ones.

Each prompt declares an `expected` outcome (`"blocked"` or `"allowed"`) so
the runner can compute a *pass rate* (did the guardrail behave as
expected?) in addition to a raw *detection rate*.

---

## Export / Import

Configuration is exported and imported as **ZIP files** (not JSON). You
choose which sections to include.

### Export

1. Go to **Admin Console → Export/Import**.
2. Check the sections you want in the export:
   - **Appearance**, **LLM**, **Security**, **RAG scanning**, **Demo prompts**, **Tools**, **RAG** (default: all checked).
   - **API keys** and **Project IDs** are off by default (safe for sharing).
3. Click **Export**. A ZIP is downloaded (e.g. `agentic_demo_config_2026-02-23T12-00-00.zip`).

The ZIP contains `metadata.json` (version 2.0, list of included sections),
`config.json`, and section-specific files such as `demo_prompts.json`,
`tools.json`, `rag_sources.json`, and the ChromaDB vector store when those
sections are included.

### Import

1. Go to **Admin Console → Export/Import**.
2. Upload a previously exported **ZIP** file.
3. The app **merges by section**: only sections present in the ZIP are applied (e.g. a "safe" export does not overwrite your API keys or project IDs).
4. After import, a summary shows which sections were applied. RAG (ChromaDB) is loaded from the ZIP without replacing the live `data/chroma` directory in use; the app switches to the imported vectors so RAG keeps working.

**Tips:**

- For **demo prompts** to be in the export, include the **Demo prompts** section when exporting. Re-export after adding prompts if your current ZIP was created before that change.
- **v1.0** ZIPs (no `metadata.json` version 2.0, or old format) are still supported: full replace behavior, and demo prompts can be read from `demo_prompts.json` or from `data/agentic_demo.db` inside the ZIP.

---

## Admin auth env vars

Recommended for any non-localhost deployment. Set in `.env` next to
`docker-compose.yml` or in the shell that launches `start_all.py`:

```bash
ADMIN_USER=your-admin-username
ADMIN_PASSWORD=a-strong-password
JWT_SECRET=$(openssl rand -hex 32)       # stable secret across restarts
ADMIN_TOKEN_TTL_HOURS=12                 # optional override (default 12)
```

If `ADMIN_USER` / `ADMIN_PASSWORD` are unset, the app falls back to
`admin` / `admin`, prints a warning at startup, and shows a banner on the
login screen reminding the operator to set proper credentials before
exposing the instance.
