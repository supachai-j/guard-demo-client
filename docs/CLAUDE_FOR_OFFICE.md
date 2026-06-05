# Claude for Office (PowerPoint) → Portkey gateway shim

Anthropic-native clients like **Claude for Office** send their gateway auth in
the `x-api-key` header and don't let you change it. **Portkey only accepts its
key via `x-portkey-api-key`** (or `Authorization: Bearer`), so pointing the
plugin straight at `https://api.portkey.ai/v1` fails:

```
Claude for Office connection failed (Gateway)
Invalid authentication token
  url: https://api.portkey.ai/v1
  authHeader: x-api-key
HTTP 401 {"message":"Portkey Error: Invalid API Key. Error Code: 03"}
```

This backend ships a small **Anthropic-format shim** that bridges the two.

## How it works

```
Claude for Office ──(x-api-key, anthropic format)──▶ POST /v1/messages (this backend)
                                                          │ validate x-api-key == Portkey key
                                                          │ rewrite → x-portkey-api-key + routing
                                                          ▼
                                                     api.portkey.ai/v1/messages ──▶ model
```

- Endpoint: `POST /v1/messages` (`backend/routes/anthropic_proxy.py`).
- Auth: the incoming `x-api-key` must equal the configured `portkey_api_key`
  (constant-time compare). It is **not an open relay** — the caller must
  already hold the Portkey key.
- Routing: forwards with the active `portkey_config` (or `portkey_virtual_key`)
  — the same routing the chat path uses. Today that resolves to
  `gemini-2.5-flash` (the account has no Anthropic provider).
- Streaming: both non-streaming JSON and SSE streaming are proxied unchanged.

## Setup (you change ONE thing in the plugin)

1. **Expose this backend at a public HTTPS URL.** Claude for Office calls the
   gateway from the user's machine over the internet, so `localhost` is not
   enough. Use your existing tunnel, e.g. Tailscale Funnel:
   ```
   tailscale up           # if it's stopped
   tailscale funnel 8000  # serves the backend over HTTPS at your tailnet domain
   ```
2. **In Claude for Office → connection settings, change only the gateway URL:**

   | Field | Before | After |
   |---|---|---|
   | gateway URL | `https://api.portkey.ai/v1` | `https://<your-tunnel-host>/v1` |
   | token (`x-api-key`) | *(Portkey key)* | **unchanged** |
   | apiFormat | `anthropic` | **unchanged** |

   The plugin will call `https://<your-tunnel-host>/v1/messages` with the same
   `x-api-key`; the shim accepts it and forwards to Portkey.

## Security notes

- The relay forwards using the **server's** Portkey key, gated by the
  `x-api-key` match. Because exposing this backend publicly also exposes the
  Admin Console, set real `ADMIN_USER` / `ADMIN_PASSWORD` / `JWT_SECRET` before
  opening a tunnel — don't leave the `admin` / `admin` dev fallback.
- Disable the shim without removing the route by setting
  `CLAUDE_OFFICE_PROXY_ENABLED=0` (then `/v1/messages` returns 404).

## Want real Claude instead of gemini?

The Portkey account currently has no Anthropic provider, so requests resolve to
gemini wearing Anthropic response format. To serve real Claude, add an
**Anthropic integration** in Portkey (needs an Anthropic API key) and point the
active `portkey_config` / `portkey_virtual_key` at it — no code change needed;
the shim forwards whatever routing is configured.
