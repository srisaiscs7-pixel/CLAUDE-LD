"""Gemini wrapper with retries, JSON handling and token counting."""
from __future__ import annotations

import json
import re
import time
import threading


class LLMError(RuntimeError):
    pass


def _extract_json(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if m:
            return json.loads(m.group(1))
        raise


class GeminiLLM:
    def __init__(self, api_key: str, model: str):
        from google import genai  # imported here so the app loads without the key
        self.genai = genai
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.tokens_in = 0
        self.tokens_out = 0
        self._lock = threading.Lock()

    def list_models(self) -> list[str]:
        names = []
        for m in self.client.models.list():
            acts = getattr(m, "supported_actions", None) or []
            if "generateContent" in acts and "gemini" in m.name:
                names.append(m.name.replace("models/", ""))
        return sorted(names, reverse=True)

    def web_pages(self, query: str, limit: int = 6) -> list[tuple[str, str]]:
        """Use Gemini's Google Search tool to find web pages about a query. Returns (url, title) pairs."""
        from google.genai import types
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=f"Find web pages (medical and dental textbooks, journals, educational sites, atlases) "
                         f"that show clear illustrations, diagrams, radiographs or clinical photographs of: {query}. "
                         f"Briefly list the pages.",
                config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())],
                                                   temperature=0.2, max_output_tokens=2000))
        except Exception:
            return []
        um = getattr(resp, "usage_metadata", None)
        if um:
            with self._lock:
                self.tokens_in += um.prompt_token_count or 0
                self.tokens_out += um.candidates_token_count or 0
        out = []
        for cand in resp.candidates or []:
            gm = getattr(cand, "grounding_metadata", None)
            for ch in (getattr(gm, "grounding_chunks", None) or []):
                web = getattr(ch, "web", None)
                if web and web.uri and (web.uri, web.title) not in out:
                    out.append((web.uri, web.title or ""))
        return out[:limit]

    def generate(self, prompt, *, task: str = "", system: str = "", json_mode: bool = False,
                 temperature: float = 0.6, max_tokens: int = 16000, files: list | None = None,
                 tries: int = 4):
        from google.genai import types
        cfg = dict(temperature=temperature, max_output_tokens=max_tokens)
        if system:
            cfg["system_instruction"] = system
        if json_mode:
            cfg["response_mime_type"] = "application/json"
        contents = []
        for data, mime in files or []:
            contents.append(types.Part.from_bytes(data=data, mime_type=mime))
        contents.append(prompt)
        last = None
        for i in range(tries):
            try:
                resp = self.client.models.generate_content(
                    model=self.model, contents=contents, config=types.GenerateContentConfig(**cfg))
                um = getattr(resp, "usage_metadata", None)
                if um:
                    with self._lock:
                        self.tokens_in += um.prompt_token_count or 0
                        self.tokens_out += (um.candidates_token_count or 0) + (getattr(um, "thoughts_token_count", 0) or 0)
                text = resp.text or ""
                if not text.strip():
                    raise LLMError("Empty response (possibly blocked or out of tokens)")
                return _extract_json(text) if json_mode else text
            except Exception as e:
                last = e
                msg = str(e)
                wait = 20 * (i + 1) if ("429" in msg or "RESOURCE_EXHAUSTED" in msg) else 5 * (i + 1)
                time.sleep(wait)
        raise LLMError(f"Gemini failed for '{task}': {last}")
