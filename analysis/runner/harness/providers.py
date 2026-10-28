"""One call per provider route.

Each builder returns a Call: the request as recorded (binary files replaced by name and SHA-256), the
settings, and three functions. send() makes the API call and returns the provider's response object;
dump() turns that object into JSON for the raw record; parse() reads the fields the call record needs.
The runner saves dump() before running parse(), so a paid response is kept even if reading it fails.

No hidden retries: SDK retries are switched off, so every attempt is a recorded run. No automatic
switch to another model (e.g. Anthropic refusal fallbacks) is enabled. No system prompt, no tools, no
web access. Temperature is never set. Effort is sent only where the model configuration gives it: the
documented default for providers that do not report it (Anthropic, Google), and the effort-comparison
levels; otherwise the provider default applies and the reported value is recorded.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Callable

from .inputs import ManuscriptInput

TIMEOUT_S = 3600
# Endpoints are fixed here rather than read from the environment, so runs always reach the providers' own APIs.
ANTHROPIC_BASE_URL = "https://api.anthropic.com"
OPENAI_BASE_URL = "https://api.openai.com/v1"
FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"
ENDPOINTS = {"anthropic_api": ANTHROPIC_BASE_URL, "openai_api": OPENAI_BASE_URL,
             "gemini_api": "google-genai default (generativelanguage.googleapis.com)", "fireworks_serverless": FIREWORKS_BASE_URL}


def _anthropic(timeout):
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], base_url=ANTHROPIC_BASE_URL,
                               max_retries=0, timeout=timeout)


def _openai(timeout, base_url=OPENAI_BASE_URL, key_var="OPENAI_API_KEY"):
    import openai
    return openai.OpenAI(api_key=os.environ[key_var], base_url=base_url, max_retries=0, timeout=timeout)


def _gemini(timeout_ms):
    from google import genai
    from google.genai import types
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options=types.HttpOptions(
        timeout=timeout_ms, retry_options=types.HttpRetryOptions(attempts=1)))
DEFAULTS = {"effort": "not set (provider default)", "thinking": "not set (provider default)",
            "temperature": "not set (provider default)", "seed": "not set", "system_prompt": "none", "tools": "none",
            "sdk_retries": 0}


@dataclass
class Call:
    request: dict
    settings: dict
    send: Callable[[], Any]
    dump: Callable[[Any], Any]
    parse: Callable[[Any], dict]


def _b64(path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _ref(seg) -> dict:
    return {"file": str(seg.path.name), "sha256": seg.sha256, "media_type": seg.media_type, "encoding": "base64"}


def _int(x):
    return x if isinstance(x, int) else None


def _json(s):
    """Fireworks reports the settings it applied as JSON in response headers."""
    if not s:
        return None
    try:
        return json.loads(s)
    except ValueError:
        return s


# ---------------------------------------------------------------- Anthropic Messages API (streamed)

def build_anthropic(cfg: dict, mi: ManuscriptInput, prompt: str) -> Call:
    content, logged = [], []
    for seg in mi.segments:
        if seg.kind == "pdf":
            content.append({"type": "document", "source": {"type": "base64", "media_type": seg.media_type, "data": _b64(seg.path)}})
            logged.append({"type": "document", "source": _ref(seg)})
        elif seg.kind == "image":
            content.append({"type": "image", "source": {"type": "base64", "media_type": seg.media_type, "data": _b64(seg.path)}})
            logged.append({"type": "image", "source": _ref(seg)})
        else:
            content.append({"type": "text", "text": seg.text})
            logged.append({"type": "text", "text": seg.text})
    content[-1]["cache_control"] = {"type": "ephemeral"}      # cache the manuscript prefix
    logged[-1]["cache_control"] = {"type": "ephemeral"}
    content.append({"type": "text", "text": prompt})
    logged.append({"type": "text", "text": prompt})
    params = {"model": cfg["model_id"], "max_tokens": cfg["max_output_tokens"]}
    settings = {**DEFAULTS, "max_tokens": cfg["max_output_tokens"], "prompt_caching": "ephemeral breakpoint after the manuscript",
                "refusal_fallback": "none", "streaming": True}
    if cfg.get("effort"):                       # documented default, sent explicitly (output_config.effort)
        params["output_config"] = {"effort": cfg["effort"]}
        settings["effort"] = cfg["effort"]
    ctx = {}

    def send():
        client = _anthropic(TIMEOUT_S)
        with client.messages.stream(**params, messages=[{"role": "user", "content": content}]) as stream:
            msg = stream.get_final_message()
            ctx["request_id"] = stream.request_id
        return msg

    def parse(msg) -> dict:
        u = msg.usage
        written, read = u.cache_creation_input_tokens or 0, u.cache_read_input_tokens or 0
        return {
            "text": "".join(b.text for b in msg.content if b.type == "text"),
            "model_returned": msg.model, "request_id": ctx.get("request_id"), "stop_reason": msg.stop_reason,
            "usage": {"input_total": u.input_tokens + written + read, "cached_input": read, "cache_write": written,
                      "output_billed": u.output_tokens, "reasoning": "included in output, not reported separately"},
            "usage_provider_fields": u.to_dict(), "effort_reported": "unknown"}

    return Call({**params, "messages": [{"role": "user", "content": logged}]}, settings, send,
                lambda msg: {"message": msg.to_dict(), "request_id": ctx.get("request_id")}, parse)


# ---------------------------------------------------------------- Gemini API

def build_gemini(cfg: dict, mi: ManuscriptInput, prompt: str) -> Call:
    logged = [{"inline_data": _ref(seg)} if seg.kind in ("pdf", "image") else {"text": seg.text} for seg in mi.segments]
    logged.append({"text": prompt})
    config = {"max_output_tokens": cfg["max_output_tokens"]}
    settings = {**DEFAULTS, "max_output_tokens": cfg["max_output_tokens"], "prompt_caching": "implicit (provider default)"}
    if cfg.get("effort"):                       # documented default, sent explicitly (thinking_config.thinking_level)
        config["thinking_config"] = {"thinking_level": cfg["effort"].upper()}
        settings["effort"] = settings["thinking"] = f"thinking_level {cfg['effort'].upper()}"
    request = {"model": cfg["model_id"], "contents": [{"role": "user", "parts": logged}], "config": config}

    def send():
        from google.genai import types
        client = _gemini(TIMEOUT_S * 1000)
        parts = [types.Part.from_bytes(data=seg.path.read_bytes(), mime_type=seg.media_type)
                 if seg.kind in ("pdf", "image") else types.Part.from_text(text=seg.text) for seg in mi.segments]
        parts.append(types.Part.from_text(text=prompt))
        gen = {"max_output_tokens": cfg["max_output_tokens"]}
        if "thinking_config" in config:
            gen["thinking_config"] = types.ThinkingConfig(thinking_level=config["thinking_config"]["thinking_level"])
        return client.models.generate_content(
            model=cfg["model_id"], contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(**gen))

    def parse(resp) -> dict:
        um = resp.usage_metadata
        cand = resp.candidates[0] if resp.candidates else None
        fr = cand.finish_reason if cand else None
        thoughts = um.thoughts_token_count if um else None   # absent when the model does not report thinking
        return {
            "text": resp.text or "", "model_returned": resp.model_version, "request_id": resp.response_id,
            "stop_reason": getattr(fr, "name", str(fr)) if cand else "no candidate",
            "usage": {"input_total": _int(um.prompt_token_count) if um else None,
                      "cached_input": (um.cached_content_token_count or 0) if um else 0, "cache_write": 0,
                      "output_billed": ((um.candidates_token_count or 0) + (thoughts or 0)) if um else None,
                      "reasoning": thoughts if thoughts is not None else "not reported"},
            "usage_provider_fields": um.model_dump(mode="json", exclude_none=True) if um else None,
            "effort_reported": "unknown"}

    return Call(request, settings, send, lambda r: r.model_dump(mode="json", exclude_none=True), parse)


# ---------------------------------------------------------------- OpenAI Responses API

def build_openai(cfg: dict, mi: ManuscriptInput, prompt: str, system: str | None = None) -> Call:
    """system: instructions sent as the system message (judge runs only); review and coding runs send none."""
    content, logged = [], []
    for seg in mi.segments:
        if seg.kind == "pdf":
            content.append({"type": "input_file", "filename": "manuscript.pdf", "file_data": f"data:application/pdf;base64,{_b64(seg.path)}"})
            logged.append({"type": "input_file", "filename": "manuscript.pdf", "file_data": _ref(seg)})
        elif seg.kind == "image":
            content.append({"type": "input_image", "image_url": f"data:{seg.media_type};base64,{_b64(seg.path)}"})
            logged.append({"type": "input_image", "image_url": _ref(seg)})
        else:
            content.append({"type": "input_text", "text": seg.text})
            logged.append({"type": "input_text", "text": seg.text})
    content.append({"type": "input_text", "text": prompt})
    logged.append({"type": "input_text", "text": prompt})
    # Routing key for OpenAI's prompt cache, so repeated calls on the same manuscript file reach the cached copy.
    # It is the file's hash, not its name, and is not shown to the model. Judge runs key on the system text instead.
    if mi.files:
        cache_key, basis = "ms-" + mi.files[0]["sha256"][:16], "manuscript file hash"
    else:
        cache_key, basis = "sys-" + hashlib.sha256((system or "").encode()).hexdigest()[:16], "system text hash"
    params = {"model": cfg["model_id"], "max_output_tokens": cfg["max_output_tokens"], "store": False,
              "prompt_cache_key": cache_key}
    settings = {**DEFAULTS, "max_output_tokens": cfg["max_output_tokens"], "store": False,
                "prompt_caching": f"automatic, prompt_cache_key {cache_key} ({basis})"}
    if system:
        params["instructions"] = system
        settings["system_prompt"] = "given (sent as instructions; text in the request record)"
    if cfg.get("effort"):                       # effort comparison only
        params["reasoning"] = {"effort": cfg["effort"]}
        settings["effort"] = cfg["effort"]

    def send():
        client = _openai(TIMEOUT_S)
        return client.responses.create(**params, input=[{"role": "user", "content": content}])

    def parse(resp) -> dict:
        u = resp.usage
        reasoning = getattr(resp, "reasoning", None)
        inc = resp.incomplete_details
        return {
            "text": resp.output_text or "", "model_returned": resp.model,
            "request_id": getattr(resp, "_request_id", None) or resp.id,
            "stop_reason": f"incomplete: {inc.reason}" if inc else resp.status,
            "usage": {"input_total": _int(u.input_tokens) if u else None,
                      "cached_input": (getattr(u.input_tokens_details, "cached_tokens", 0) or 0) if u else 0,
                      "cache_write": (getattr(u.input_tokens_details, "cache_write_tokens", 0) or 0) if u else 0,
                      "output_billed": _int(u.output_tokens) if u else None,
                      "reasoning": (getattr(u.output_tokens_details, "reasoning_tokens", 0) or 0) if u else "unknown"},
            "usage_provider_fields": u.model_dump(mode="json") if u else None,
            "effort_reported": getattr(reasoning, "effort", None) or "unknown"}

    return Call({**params, "input": [{"role": "user", "content": logged}]}, settings, send,
                lambda r: {"response": r.model_dump(mode="json"), "request_id": getattr(r, "_request_id", None)}, parse)


# ---------------------------------------------------------------- Fireworks (OpenAI-compatible chat, streamed)

def build_chat(cfg: dict, mi: ManuscriptInput, prompt: str, system: str | None = None) -> Call:
    """system: sent as a system message (judge runs only); review and coding runs send none."""
    content, logged = [], []
    for seg in mi.segments:
        if seg.kind == "pdf":
            raise SystemExit(f"{cfg['model_id']} on {cfg['route']} cannot take a PDF; use md_figures or md_text")
        if seg.kind == "image":
            content.append({"type": "image_url", "image_url": {"url": f"data:{seg.media_type};base64,{_b64(seg.path)}"}})
            logged.append({"type": "image_url", "image_url": _ref(seg)})
        else:
            content.append({"type": "text", "text": seg.text})
            logged.append({"type": "text", "text": seg.text})
    content.append({"type": "text", "text": prompt})
    logged.append({"type": "text", "text": prompt})
    params = {"model": cfg["model_id"], "max_tokens": cfg["max_output_tokens"]}
    settings = {**DEFAULTS, "max_tokens": cfg["max_output_tokens"], "prompt_caching": "provider default",
                "streaming": True, "serving_precision": cfg.get("serving_precision", "unknown")}
    head = [{"role": "system", "content": system}] if system else []
    if system:
        settings["system_prompt"] = "given (system message; text in the request record)"
    ctx = {}

    def send():
        client = _openai(TIMEOUT_S, base_url=FIREWORKS_BASE_URL, key_var="FIREWORKS_API_KEY")
        with client.chat.completions.stream(**params, messages=[*head, {"role": "user", "content": content}],
                                            stream_options={"include_usage": True}) as stream:
            completion = stream.get_final_completion()
            http = getattr(stream, "_response", None)
            ctx["headers"] = {k: v for k, v in http.headers.items()
                              if "request-id" in k.lower() or k.lower().startswith("fireworks")} if http is not None else {}
        return completion

    def parse(resp) -> dict:
        choice = resp.choices[0]
        u = resp.usage
        details = getattr(u, "prompt_tokens_details", None) if u else None
        hdr = ctx.get("headers", {})
        reported = {k: _json(hdr.get(f"fireworks-{k}-options")) for k in ("sampling", "conversation")}
        conv = reported["conversation"] if isinstance(reported["conversation"], dict) else {}
        return {
            "text": choice.message.content or "", "model_returned": resp.model,
            "request_id": hdr.get("x-request-id") or hdr.get("fireworks-request-id") or resp.id,
            "stop_reason": choice.finish_reason,
            "usage": {"input_total": _int(u.prompt_tokens) if u else None,
                      "cached_input": (getattr(details, "cached_tokens", 0) or 0) if details else 0,
                      "cache_write": 0, "output_billed": _int(u.completion_tokens) if u else None,
                      "reasoning": (getattr(getattr(u, "completion_tokens_details", None), "reasoning_tokens", None)
                                    or "unknown") if u else "unknown"},
            "usage_provider_fields": u.model_dump(mode="json") if u else None,
            "effort_reported": conv.get("reasoning_effort") or "unknown",
            "settings_reported": {k: v for k, v in reported.items() if v is not None}}

    return Call({**params, "messages": [*head, {"role": "user", "content": logged}], "stream": True}, settings, send,
                lambda r: {"completion": r.model_dump(mode="json"), "response_headers": ctx.get("headers", {})}, parse)


# ---------------------------------------------------------------- model metadata (free endpoints, no generation)

def model_metadata(cfg: dict) -> dict:
    """What each provider's models endpoint says about the model (version, limits, dates), for the batch record."""
    try:
        if cfg["route"] == "anthropic_api":
            return _anthropic(60).models.retrieve(cfg["model_id"]).to_dict()
        if cfg["route"] == "gemini_api":
            return _gemini(60000).models.get(model=cfg["model_id"]).model_dump(mode="json", exclude_none=True)
        if cfg["route"] == "openai_api":
            return _openai(60).models.retrieve(cfg["model_id"]).model_dump(mode="json")
        if cfg["route"] == "fireworks_serverless":
            import httpx
            r = httpx.get(f"https://api.fireworks.ai/v1/{cfg['model_id']}", timeout=60,
                          headers={"Authorization": f"Bearer {os.environ['FIREWORKS_API_KEY']}"})
            r.raise_for_status()
            keep = ("name", "displayName", "createTime", "updateTime", "state", "contextLength", "supportsImageInput",
                    "supportsServerless", "huggingFaceUrl", "baseModelDetails", "deprecationDate", "kind")
            return {k: v for k, v in r.json().items() if k in keep}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    return {"error": f"no metadata endpoint for route {cfg['route']}"}


BUILDERS: dict[str, Callable[..., Call]] = {
    "anthropic_api": build_anthropic,
    "gemini_api": build_gemini,
    "openai_api": build_openai,
    "fireworks_serverless": build_chat,
}
