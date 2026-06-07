"""Portkey gateway-guardrails adapter.

Unlike the other adapters (which hit a guardrail-only API), Portkey runs
guardrails *inline with a chat completion* — there is no standalone scan
endpoint. So we POST the prompt to `…/chat/completions` using the configured
Portkey **Config** (`portkey_config`) and read the `hook_results` it returns.

Cost/throughput note: because the call goes through the LLM, every check
consumes one (tiny, max_tokens=1) completion against whatever provider the
Config targets — so this provider is rpm-bound by that Config's virtual key,
where Lakera/AIRS are not. 429s surface as `rate_limited`.

Verdict semantics (verified empirically against the live gateway):
- HTTP 446  -> a guardrail denied the request (deny:true + hook failed) = flagged.
- hook `verdict: false` -> the hook failed (would deny) = flagged, even in
  monitor mode (deny:false, async) where HTTP stays 200.
- hook `verdict: true`  -> passed = not flagged.
- a check carrying `error` (e.g. the AIRS integration returning 403) did NOT
  evaluate — surfaced as a classified error status, never as "passed".
"""

import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from .base import GuardrailProvider, GuardrailStatus, classify_http, make_error_status

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://api.portkey.ai/v1"
# A browser-shaped UA: Portkey sits behind Cloudflare, which 1010-blocks the
# bare httpx/urllib UA (verified) but lets normal agents through — same reason
# the ThaiLLM dispatch branch overrides its UA.
_UA = "Mozilla/5.0 (compatible; guard-demo-client)"
_STATUS_RE = re.compile(r"status:\s*(\d{3})")


def _last_user_text(messages: List[Dict[str, str]]) -> Optional[str]:
    for m in reversed(messages or []):
        if m.get("role") == "user" and m.get("content"):
            c = m["content"]
            # vision content-blocks arrive as a list; pull the text parts.
            if isinstance(c, list):
                c = " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
            return c or None
    return None


def _check_error_class(check: Dict[str, Any]) -> Optional[str]:
    """If a Portkey check errored, classify it; else None."""
    err = check.get("error")
    if not err:
        return None
    msg = err.get("message", "") if isinstance(err, dict) else str(err)
    m = _STATUS_RE.search(msg)
    return classify_http(int(m.group(1))) if m else "http_error"


def _map_hook_results(status_code: int, body: Dict[str, Any], source: str) -> GuardrailStatus:
    """Turn a Portkey completion response into the Lakera-shaped status."""
    hr = body.get("hook_results") or {}
    hooks = list(hr.get("before_request_hooks") or []) + list(hr.get("after_request_hooks") or [])

    if not hooks:
        # No guardrails ran. If the gateway itself errored, surface that.
        if status_code >= 400 and status_code != 446:
            detail = (body.get("error") or {}).get("message") if isinstance(body.get("error"), dict) else None
            return make_error_status(source, classify_http(status_code), http_status=status_code, detail=detail)
        return {
            "flagged": False, "breakdown": [], "payload": [],
            "metadata": {"source": source, "http_status": status_code, "note": "no guardrails in the configured Portkey config"},
        }

    flagged = status_code == 446
    breakdown: List[Dict[str, Any]] = []
    error_classes: List[str] = []
    evaluated = False
    guard_ids: List[str] = []

    for hook in hooks:
        guard_ids.append(hook.get("id"))
        errs = [c for c in (hook.get("checks") or []) if c.get("error")]
        if errs and not any(not c.get("error") for c in (hook.get("checks") or [])):
            # Every check in this hook errored -> it didn't evaluate.
            error_classes.append(_check_error_class(errs[0]) or "http_error")
            continue
        evaluated = True
        if hook.get("verdict") is False:
            flagged = True
            breakdown.append({
                "project_id": None,
                "policy_id": f"portkey-{hook.get('id')}",
                "detector_id": hook.get("id"),
                "detector_type": "prompt_attack",
                "detected": True,
                "message_id": 0,
            })

    if not evaluated and error_classes:
        return make_error_status(source, error_classes[0], http_status=status_code,
                                 detail=f"guardrail check errored: {error_classes}")

    return {
        "flagged": flagged,
        "breakdown": breakdown,
        "payload": [],
        "metadata": {"source": source, "http_status": status_code, "guardrails": guard_ids},
    }


class PortkeyGuardrailProvider(GuardrailProvider):
    id = "portkey_guardrail"
    display_name = "Portkey (Gateway Guardrails)"

    @classmethod
    def is_configured(cls, cfg: Any) -> bool:
        return bool(getattr(cfg, "portkey_api_key", None) and getattr(cfg, "portkey_config", None))

    async def check_interaction(
        self,
        messages: List[Dict[str, str]],
        cfg: Any,
        meta: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
    ) -> Optional[GuardrailStatus]:
        api_key = getattr(cfg, "portkey_api_key", None)
        config_id = (getattr(cfg, "portkey_config", None) or "").strip()
        if not api_key or not config_id:
            return make_error_status(self.id, "config_error",
                                     detail="portkey_api_key + portkey_config (a Config slug with guardrails) are required")

        user_text = _last_user_text(messages)
        if not user_text:
            return make_error_status(self.id, "config_error", detail="no user message to scan")

        custom_base = (getattr(cfg, "portkey_base_url", None) or "").strip()
        base = (custom_base.rstrip("/") if custom_base else _DEFAULT_BASE)
        if not base.endswith("/v1"):
            base = f"{base}/v1"

        headers = {
            "x-portkey-api-key": api_key,
            "x-portkey-config": config_id,
            "Content-Type": "application/json",
            "User-Agent": _UA,
        }
        virtual_key = (getattr(cfg, "portkey_virtual_key", None) or "").strip()
        if virtual_key:
            headers["x-portkey-virtual-key"] = virtual_key

        body = {
            "model": getattr(cfg, "openai_model", None) or "gpt-4o",
            "messages": [{"role": "user", "content": user_text}],
            "max_tokens": 1,
        }

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(f"{base}/chat/completions", headers=headers, json=body)
        except Exception as e:  # noqa: BLE001
            logger.warning("Portkey guardrail transport error: %s", e)
            return make_error_status(self.id, "transport_error", detail=str(e))

        try:
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            # Only a parse failure with no hook data is unrecoverable.
            return make_error_status(self.id, "parse_error", http_status=resp.status_code, detail=str(e))

        return _map_hook_results(resp.status_code, data, self.id)
