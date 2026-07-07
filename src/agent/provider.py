"""
Primary/fallback LLM abstraction: Ollama (local, free, no rate limits) is
tried first; Gemini's free tier is used if Ollama isn't installed/running.

The provider is picked once per agent run via a cheap health check, not
re-negotiated per message. Ollama and Gemini have genuinely different
tool-calling wire formats, so translating conversation state between them
mid-run isn't worth the complexity for a two-provider setup.
# ponytail: single-provider-per-run; add per-call failover if Ollama is
# ever observed dying mid-run in practice, not before.
"""

import json
import os

import requests

from src.agent.tools import TOOL_SCHEMAS

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


class Turn:
    def __init__(self, tool_calls=None, text=None):
        self.tool_calls = tool_calls or []
        self.text = text


class OllamaBackend:
    name = "ollama"

    def __init__(self, model=OLLAMA_MODEL):
        import ollama

        self._client = ollama
        self.model = model
        self.messages = []

    def _call(self):
        resp = self._client.chat(model=self.model, messages=self.messages, tools=TOOL_SCHEMAS)
        msg = resp.message
        self.messages.append(msg)
        tool_calls = [
            {"id": tc.function.name, "name": tc.function.name, "arguments": dict(tc.function.arguments)}
            for tc in (msg.tool_calls or [])
        ]
        return Turn(tool_calls=tool_calls, text=msg.content)

    def start(self, system_prompt, user_prompt):
        self.messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._call()

    def send_tool_result(self, tool_call_id, name, result: dict):
        self.messages.append({"role": "tool", "content": json.dumps(result)})
        return self._call()

    def nudge(self, text: str):
        self.messages.append({"role": "user", "content": text})
        return self._call()


class GeminiBackend:
    name = "gemini"

    def __init__(self, api_key, model=GEMINI_MODEL):
        # google-generativeai is deprecated (no more updates/bug fixes) as of
        # 2026 -- google-genai is the current SDK, so we build on that instead.
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.chat = None

    def _parse(self, response):
        parts = response.candidates[0].content.parts
        tool_calls, text = [], None
        for part in parts:
            if part.function_call:
                fc = part.function_call
                tool_calls.append({"id": fc.name, "name": fc.name, "arguments": dict(fc.args or {})})
            elif part.text:
                text = part.text
        return Turn(tool_calls=tool_calls, text=text)

    def start(self, system_prompt, user_prompt):
        declarations = [
            self._types.FunctionDeclaration(
                name=t["function"]["name"],
                description=t["function"]["description"],
                parametersJsonSchema=t["function"]["parameters"],
            )
            for t in TOOL_SCHEMAS
        ]
        config = self._types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[self._types.Tool(functionDeclarations=declarations)],
        )
        self.chat = self._client.chats.create(model=self.model, config=config)
        return self._parse(self.chat.send_message(user_prompt))

    def send_tool_result(self, tool_call_id, name, result: dict):
        part = self._types.Part.from_function_response(name=name, response=result)
        return self._parse(self.chat.send_message(part))

    def nudge(self, text: str):
        return self._parse(self.chat.send_message(text))


def get_backend():
    try:
        requests.get(OLLAMA_HOST, timeout=2).raise_for_status()
        backend = OllamaBackend()
        # A reachable server doesn't mean the model can actually load (e.g.
        # not enough free RAM) -- a cheap real chat call catches that before
        # committing this whole run to a provider that's about to crash.
        backend._client.chat(model=backend.model, messages=[{"role": "user", "content": "ping"}])
        return backend
    except Exception:
        pass

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Ollama is unusable and GEMINI_API_KEY is not set -- no LLM provider available."
        )
    return GeminiBackend(api_key)
