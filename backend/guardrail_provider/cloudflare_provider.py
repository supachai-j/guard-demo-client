"""Cloudflare Firewall for AI guardrail adapter.

Cloudflare's "Firewall for AI" sits on top of AI Gateway. The detection
endpoint we use is the public Llama Guard model exposed via the Workers AI
REST API, which is the most stable surface that customers without an AI
Gateway gateway-id can still hit:

  POST https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/meta/llama-guard-3-8b
  Authorization: Bearer <api_token>
  { "messages": [{"role":"user","content":"..."}] }

Returns a `response` containing "safe" or "unsafe\nS1\nS3..." where S* are
hazard categories from MLCommons. We map unsafe categories → the standard
moderated_content/* taxonomy used by every other guardrail provider.

If `cloudflare_gateway_id` is configured we route through the gateway
(`/ai-gateway/gateways/{gateway_id}/workers-ai/...`) so requests show up in
the user's AI Gateway analytics; otherwise we hit the direct Workers AI URL.
"""

import json
from typing import Any, Dict, List, Optional

import httpx

from .base import GuardrailProvider, GuardrailStatus


# MLCommons hazard taxonomy used by Llama Guard 3.
_LLAMA_GUARD_CATEGORIES: Dict[str, str] = {
    "S1": "moderated_content/violent_crimes",
    "S2": "moderated_content/non_violent_crimes",
    "S3": "moderated_content/sex_related_crimes",
    "S4": "moderated_content/child_sexual_exploitation",
    "S5": "moderated_content/defamation",
    "S6": "moderated_content/specialized_advice",
    "S7": "moderated_content/privacy",
    "S8": "moderated_content/intellectual_property",
    "S9": "moderated_content/indiscriminate_weapons",
    "S10": "moderated_content/hate",
    "S11": "moderated_content/suicide_self_harm",
    "S12": "moderated_content/sexual_content",
    "S13": "moderated_content/elections",
    "S14": "moderated_content/code_interpreter_abuse",
}


class CloudflareFirewallForAIProvider(GuardrailProvider):
    id = "cloudflare_firewall_ai"
    display_name = "Cloudflare Firewall for AI"

    @classmethod
    def is_configured(cls, cfg: Any) -> bool:
        if not cfg:
            return False
        return bool(
            getattr(cfg, "cloudflare_account_id", None)
            and getattr(cfg, "cloudflare_api_token", None)
        )

    async def check_interaction(
        self,
        messages: List[Dict[str, str]],
        cfg: Any,
        meta: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
    ) -> Optional[GuardrailStatus]:
        account_id = getattr(cfg, "cloudflare_account_id", None)
        api_token = getattr(cfg, "cloudflare_api_token", None)
        gateway_id = (getattr(cfg, "cloudflare_gateway_id", None) or "").strip()

        if not (account_id and api_token):
            return None

        # Route through AI Gateway if configured so usage shows up in the dashboard.
        if gateway_id:
            url = (
                f"https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}"
                f"/workers-ai/@cf/meta/llama-guard-3-8b"
            )
        else:
            url = (
                f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
                f"/ai/run/@cf/meta/llama-guard-3-8b"
            )

        payload = {"messages": messages or []}
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            return {
                "flagged": False,
                "breakdown": [],
                "payload": [],
                "metadata": {"source": "cloudflare_firewall_ai", "error": str(e)},
            }

        # Workers AI envelope: {"result": {"response": "safe"|"unsafe\nS1\nS3", ...}, "success": true}
        result_obj = data.get("result") if isinstance(data, dict) else None
        text = ""
        if isinstance(result_obj, dict):
            text = str(result_obj.get("response") or "").strip()
        elif isinstance(result_obj, str):
            text = result_obj.strip()

        flagged = text.lower().startswith("unsafe")
        breakdown: List[Dict[str, Any]] = []
        # message_id: index of the last user/assistant turn we sent
        target_idx = max(0, len(messages) - 1)

        if flagged:
            # Parse hazard codes from response body ("unsafe\nS1,S3" or "unsafe\nS1\nS3").
            codes: List[str] = []
            for line in text.splitlines()[1:]:
                for token in line.replace(",", " ").split():
                    token = token.strip().upper()
                    if token.startswith("S") and token[1:].isdigit():
                        codes.append(token)
            if not codes:
                codes = ["UNKNOWN"]
            for code in codes:
                breakdown.append({
                    "detector_type": _LLAMA_GUARD_CATEGORIES.get(code, "moderated_content/unsafe"),
                    "detected": True,
                    "detector_id": f"cloudflare/llama-guard-3-8b#{code}",
                    "message_id": target_idx,
                })

        return {
            "flagged": flagged,
            "breakdown": breakdown,
            "payload": [{"messages": messages}],
            "metadata": {
                "source": "cloudflare_firewall_ai",
                "model": "@cf/meta/llama-guard-3-8b",
                "via_gateway": bool(gateway_id),
                "raw_response": text,
            },
        }
