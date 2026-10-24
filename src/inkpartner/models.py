"""Which model reads and judges: local first, cloud only as a fallback.

    ollama:<model>    local on the Mac (default: ollama:qwen3.6:35b-a3b) - no key, no quota, no network
    ollama-text:<m>   local text-only model (judging from the read elements, no image)
    gemini:<model>    Google REST API, GEMINI_API_KEY (free tier: ~20 requests per day and model)
    claude:<model>    Anthropic API, ANTHROPIC_API_KEY or `ant auth login`
    minimax:<model>   MiniMax cloud (Anthropic-compatible), MINIMAX_API_KEY or the local MiniMax agent's token

A chain "ollama:qwen3.6:35b-a3b,gemini:gemini-3-flash-preview" tries the models in order. Every
model gets the same contract: images + prompt + JSON schema in, a dict out.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT = "ollama:qwen3.6:35b-a3b"
ENV = "INKPARTNER_MODEL"


class ModelError(RuntimeError):
    pass


def _post(url: str, body: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _loads(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < start:
        raise ModelError(f"no JSON object in model output: {text[:200]!r}")
    return json.loads(t[start:end + 1])


class Ollama:
    def __init__(self, model: str, host: str | None = None, timeout: float = 600, images: bool = True):
        self.name = ("ollama:" if images else "ollama-text:") + model
        self.model, self.timeout, self.images = model, timeout, images
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        if not self.host.startswith("http"):
            self.host = "http://" + self.host

    def json(self, images: list[bytes], prompt: str, schema: dict) -> dict:
        # keep the model in memory: reloading 23 GB after Ollama's default 5 idle minutes costs seconds
        body = {"model": self.model, "stream": False, "format": schema, "think": False, "keep_alive": "60m",
                "options": {"temperature": 0},
                "messages": [{"role": "user", "content": prompt,
                              "images": [base64.b64encode(i).decode() for i in images] if self.images else []}]}
        r = _post(self.host + "/api/chat", body, {}, self.timeout)
        return _loads(r["message"]["content"])


class Gemini:
    def __init__(self, model: str, timeout: float = 120):
        self.name = "gemini:" + model
        self.model, self.timeout = model, timeout
        self.key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not self.key:
            raise ModelError("GEMINI_API_KEY is not set")

    def json(self, images: list[bytes], prompt: str, schema: dict) -> dict:
        parts = [{"inline_data": {"mime_type": "image/png", "data": base64.b64encode(i).decode()}} for i in images]
        parts.append({"text": prompt + "\n\nAnswer with JSON matching this schema:\n" + json.dumps(schema)})
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        r = _post(url, {"contents": [{"parts": parts}],
                        "generationConfig": {"responseMimeType": "application/json"}},
                  {"x-goog-api-key": self.key}, self.timeout)
        return _loads(r["candidates"][0]["content"]["parts"][0]["text"])


class Claude:
    def __init__(self, model: str = "claude-opus-5-5", client=None):
        import anthropic
        self.name = "claude:" + model
        self.model = model
        self.client = client or anthropic.Anthropic()

    def json(self, images: list[bytes], prompt: str, schema: dict) -> dict:
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                 "data": base64.standard_b64encode(i).decode()}} for i in images]
        content.append({"type": "text", "text": prompt})
        response = self.client.beta.messages.create(
            model=self.model, max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": content}])
        if response.stop_reason in ("refusal", "max_tokens"):
            raise ModelError(f"model stopped: {response.stop_reason}")
        return json.loads(next(b.text for b in response.content if b.type == "text"))


class MiniMax:
    """MiniMax speaks the Anthropic Messages API. No schema mode: the schema travels in the prompt.

    Known from algebra-agent (2026-10-21): MiniMax-M3.1-Flash refuses `thinking: disabled` and once
    spent all 4096 output tokens thinking on a full prose page, answer empty. So: ask without
    thinking, fall back to the model's own thinking with a large budget, and say so when it is empty.
    """

    def __init__(self, model: str = "MiniMax-M3.1-Flash", timeout: float = 180, max_tokens: int = 16000):
        self.name = "minimax:" + model
        self.model, self.timeout, self.max_tokens = model, timeout, max_tokens
        self.key = os.environ.get("MINIMAX_API_KEY", "").strip() or self._agent_token()
        if not self.key:
            raise ModelError("no MiniMax access (MINIMAX_API_KEY or ~/.minimax/auth)")
        cfg = Path.home() / ".minimax" / "config.yaml"
        m = re.search(r"^\s*baseURL\s*:\s*['\"]?([^'\"\n]+)", cfg.read_text(), re.M) if cfg.exists() else None
        self.base = (os.environ.get("MINIMAX_BASE_URL") or (m and m.group(1).strip())
                     or "https://agent.minimax.io/mavis/api/v1/llm/v1").rstrip("/")
        self.think = False
        self.usage: dict = {}

    @staticmethod
    def _agent_token() -> str:
        for f in sorted((Path.home() / ".minimax" / "auth" / "prod").glob("*/*/auth.json"), reverse=True):
            try:
                for rec in (json.loads(f.read_text()).get("records") or {}).values():
                    if rec.get("accessToken"):
                        return rec["accessToken"]
            except (OSError, ValueError):
                continue
        return ""

    def json(self, images: list[bytes], prompt: str, schema: dict) -> dict:
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                 "data": base64.b64encode(i).decode()}} for i in images]
        content.append({"type": "text", "text": prompt + "\n\nAnswer only with one JSON object matching "
                        "this schema, no text around it:\n" + json.dumps(schema)})
        body = {"model": self.model, "max_tokens": self.max_tokens, "temperature": 0,
                "messages": [{"role": "user", "content": content}]}
        headers = {"Authorization": f"Bearer {self.key}", "anthropic-version": "2023-06-01"}
        if not self.think:
            body["thinking"] = {"type": "disabled"}
        try:
            r = _post(self.base + "/messages", body, headers, self.timeout)
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", "replace")
            fresh = os.environ.get("MINIMAX_API_KEY", "").strip() or self._agent_token()
            if e.code == 401 and fresh and fresh != self.key:
                # the local agent's token lives about an hour (24.10.); a newer one may be on disk
                self.key = fresh
                return self.json(images, prompt, schema)
            if e.code == 400 and "thinking" in detail and not self.think:
                self.think = True                       # this model insists on thinking
                return self.json(images, prompt, schema)
            raise ModelError(f"HTTP {e.code}: {detail}") from None
        self.usage = r.get("usage") or {}
        text = "".join(b.get("text", "") for b in r.get("content") or [] if b.get("type") == "text")
        if not text.strip():
            raise ModelError(f"empty answer (stop: {r.get('stop_reason')}, usage: {self.usage})")
        return _loads(text)


class Chain:
    """Try each model in order; the first answer wins. Errors are kept for the log."""

    def __init__(self, models):
        self.models = list(models)
        self.name = ",".join(m.name for m in self.models)
        self.errors: list[str] = []
        self.used: str | None = None

    def json(self, images, prompt, schema):
        self.errors = []
        for m in self.models:
            try:
                out = m.json(images, prompt, schema)
                self.used = m.name
                return out
            except Exception as e:                   # next model; keep why this one failed
                self.errors.append(f"{m.name}: {e}")
        raise ModelError("all models failed: " + " | ".join(self.errors))


def get(spec: str | None = None):
    spec = spec or os.environ.get(ENV) or DEFAULT
    out = []
    for part in [p.strip() for p in spec.split(",") if p.strip()]:
        kind, _, name = part.partition(":")
        try:
            if kind == "ollama":
                out.append(Ollama(name))
            elif kind == "ollama-text":                 # text-only judge: gets the elements, not the image
                out.append(Ollama(name, images=False))
            elif kind == "gemini":
                out.append(Gemini(name))
            elif kind == "minimax":
                out.append(MiniMax(name or "MiniMax-M3.1-Flash"))
            elif kind == "claude":
                out.append(Claude(name or "claude-opus-5-5"))
            else:
                raise ModelError(f"unknown model {part!r}")
        except ModelError as e:
            if len(spec.split(",")) == 1:
                raise
            print(f"inkpartner: skipping {part}: {e}")
    if not out:
        raise ModelError(f"no usable model in {spec!r}")
    return Chain(out)
