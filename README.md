# Agentic Demo — Complete Application

B2B sales demo platform: AI chatbot with multi-vendor LLM + guardrail
integration, RAG, and MCP tools. Pluggable across 12 LLM providers and
6 guardrail providers; ships an Admin Console for live config, a
Threat Lab for security comparisons, and a Playground for interactive
testing.

> Need the full feature list, system design, or API reference? See the
> [**`docs/`**](docs/) folder.

---

## Run it

### On a server (recommended for team deploys)

`scp` the compose file + an optional `.env` to your VPS, then:

```bash
docker compose pull
docker compose up -d
```

Open `http://<server>:3000`. State (audit log, admin config, RAG
vectors) persists in `./data` on the host. Upgrade with
`docker compose pull && docker compose up -d`.

Full options — single-container `docker run`, building from source,
ToolHive on `host.docker.internal`, image tags and rollback — are in
[Docker.md](Docker.md).

### Locally for development

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
python start_all.py
```

The script installs Python + Node deps, auto-starts the LiteLLM proxy
and its Postgres in Docker, and brings up the backend (`:8000`) and
frontend (`:3000`). Manual two-terminal setup + LiteLLM proxy notes
are in [SETUP_INSTRUCTIONS.md](SETUP_INSTRUCTIONS.md).

**Prerequisites**: Python 3.10–3.12, Node.js 16+, Docker (for the
LiteLLM auto-bootstrap), plus at least one LLM provider key
(OpenAI / Anthropic / Google / Mistral / Groq / Together / OpenRouter
/ Portkey / Kong / ThaiLLM, or a self-hosted Ollama / LiteLLM
endpoint). A guardrail key is optional (OpenAI Moderation reuses your
OpenAI key for free).

---

## First-time configuration

1. Open `http://localhost:3000/admin` → sign in (`ADMIN_USER` /
   `ADMIN_PASSWORD` from `.env`, or `admin` / `admin` dev fallback).
2. **Providers tab** → enable + paste keys for the LLM and guardrail
   providers you want to use.
3. **LLM tab** → pick the active model + temperature + system prompt.
4. **Security tab** → pick the active guardrail + mode (Block /
   Monitor).
5. (Optional) Open the **Playground** or **Threat Lab** tabs and start
   running prompts.

Detailed walkthrough — per-tab settings, demo personas, playbook seed
scripts, export/import — in [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

---

## URLs

| Service             | URL                          |
|---------------------|------------------------------|
| Demo page           | http://localhost:3000        |
| Admin console       | http://localhost:3000/admin  |
| Backend API         | http://localhost:8000        |
| API docs (Swagger)  | http://localhost:8000/docs   |
| LiteLLM proxy (opt) | http://localhost:4000        |
| LiteLLM UI (opt)    | http://localhost:4000/ui     |

---

## Documentation

| Doc | What's in it |
|-----|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, request flow, auth flow, OCR pre-scan diagrams |
| [docs/API.md](docs/API.md) | Every `/api/*` endpoint with auth + response notes |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Admin Console walkthrough + export/import + env vars |
| [docs/FEATURES.md](docs/FEATURES.md) | Full feature catalogue (Core + Multi-provider + Playground + Threat Lab + Security) |
| [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) | Annotated file tree |
| [Docker.md](Docker.md) | Container deploy options + GHCR image tags + troubleshooting |
| [SETUP_INSTRUCTIONS.md](SETUP_INSTRUCTIONS.md) | Manual local-dev setup (two-terminal + LiteLLM) |
| [designdocs/](designdocs/) | In-flight design proposals (e.g. multi-workspace) |
| [CHANGELOG.md](CHANGELOG.md) | Recent changes |

---

## Troubleshooting

- **Backend won't start** → Python 3.10–3.12, port 8000 free,
  `pip install -r requirements.txt`.
- **Frontend won't start** → Node.js 16+, port 3000 free, `npm install`.
- **API errors** → set an LLM key in Admin → Providers, check network.
- **Database / RAG issues** → delete the `data/` folder to reset
  (warning: wipes audit log + admin config + vectors).
- **LiteLLM logs** → `docker logs -f guard-demo-litellm-proxy`.
- **Container deploy issues** → see [Docker.md § Troubleshooting](Docker.md#troubleshooting).

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes — `ruff check backend tests` + `pytest` must pass
4. Submit a pull request

## License

MIT. See the LICENSE file.

## Support

Check the troubleshooting section above, then the browser console + backend
terminal logs. The Swagger UI at `http://localhost:8000/docs` is the most
authoritative source for the live API surface.
