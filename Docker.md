# Running Guard Demo in Docker

Team-facing deploy guide. Works on **Mac** (Docker Desktop), **Windows**
(Docker Desktop), **Linux** (Docker Engine), and any VPS with Docker
installed.

---

## TL;DR — deploy to a server

`scp docker-compose.yml` and a `.env` to the box, then:

```bash
docker compose pull
docker compose up -d
```

Open http://<server>:3000 in your browser. State lives in `./data` on the
host (bind-mounted), so `docker compose down && up -d` keeps the audit log,
provider keys, and uploaded RAG files.

To upgrade:

```bash
docker compose pull && docker compose up -d
```

---

## Run locally (single container)

Use this for a quick try-it-out on your laptop without writing a compose
file.

```bash
docker run -d \
  --name guard-demo \
  -p 3000:3000 -p 8000:8000 \
  -v "$PWD/data:/home/lakeraai/data" \
  ghcr.io/supachai-j/guard-demo-client:latest
```

Then open **http://localhost:3000**. First boot takes ~2 min while the
container runs `npm install` and verifies Python deps.

**Linux** — add `--add-host=host.docker.internal:host-gateway` if you need
the demo to reach ToolHive (or any other service running on your host).

---

## Build from source (for fork development)

Only needed if you're modifying the code and want to test the image before
pushing. Clone, then:

```bash
docker compose up -d --build
```

Compose tags the locally-built image with the same name as the GHCR
reference, so subsequent `pull`s will then overwrite it once you push.

---

## Connecting to ToolHive (or other host services)

Inside the container, `127.0.0.1` is the container itself, not your
machine. ToolHive and other MCP servers usually run on the **host**, so
the demo must address them via the host gateway.

- **Mac / Windows:** use `host.docker.internal` in tool URLs (works out of
  the box with Docker Desktop).
- **Linux:** the `docker run` command above needs
  `--add-host=host.docker.internal:host-gateway`; the compose file already
  handles this via the host network model. Then use `host.docker.internal`
  in tool URLs.

**Example:** ToolHive gives you `http://127.0.0.1:51003/mcp` — configure
the tool in Admin → Tool Management as:

```text
http://host.docker.internal:51003/mcp
```

Same port, only the host changes.

---

## Pre-seeding provider API keys

The Admin UI (`/admin`) can set every provider key at runtime, but for an
unattended VPS deploy you can bake them into the container's environment
via the compose file's `environment:` block (or `.env` next to
`docker-compose.yml`):

```env
OPENAI_API_KEY=sk-...
LAKERA_API_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
```

Compose reads `.env` automatically. Add only the providers you intend the
demo to use — anything missing falls back to "configure in Admin UI."

---

## Image tags

Published to `ghcr.io/supachai-j/guard-demo-client` via the
`.github/workflows/docker.yml` workflow on every push to `main` and on
semver tags:

| Tag                  | When you'd use it                              |
|----------------------|------------------------------------------------|
| `:latest`            | Whatever main last built — typical demo deploy |
| `:main`              | Same as `:latest`, explicit branch name         |
| `:vX.Y.Z`            | Pin to a tagged release for reproducibility    |
| `:sha-<short>`       | Pin to a specific commit (e.g. for rollback)   |

Multi-arch (`linux/amd64` + `linux/arm64`) so ARM VPS providers work from
the same reference.

---

## Troubleshooting

- **`docker compose pull` 404 / unauthorized** — the GHCR image hasn't
  been published yet. Either push to `main` (triggers the workflow), tag
  a release, or fall back to `docker compose up -d --build`.
- **App reachable on 8000 but not 3000** — frontend dev server hasn't
  started; check `docker compose logs` for `npm install` errors.
- **Audit log / provider keys reset after restart** — the `./data` host
  bind is missing or write-protected. `chmod -R u+w data` and retry.
- **Inside the container, can't reach ToolHive on `127.0.0.1`** — see
  the *Connecting to ToolHive* section above; use `host.docker.internal`.
