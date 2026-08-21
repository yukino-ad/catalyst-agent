from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from dotenv import load_dotenv


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMSettings:
    enabled: bool
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int
    max_tokens: int
    kimi_k3_min_tokens: int

    @classmethod
    def load(cls, project_root: str | Path | None = None) -> "LLMSettings":
        root = Path(project_root or Path(__file__).resolve().parents[1])
        load_dotenv(root / ".env", override=False)
        return cls(
            enabled=os.getenv("LLM_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
            api_key=os.getenv("LLM_API_KEY", "").strip(),
            base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/"),
            model=os.getenv("LLM_MODEL", "").strip(),
            timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "90")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "32768")),
            kimi_k3_min_tokens=int(os.getenv("KIMI_K3_MIN_TOKENS", "2048")),
        )

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.api_key and self.base_url and self.model)

    def validate(self) -> None:
        if not self.enabled:
            raise LLMError("LLM 未启用，请在 .env 中设置 LLM_ENABLED=true。")
        if not self.api_key:
            raise LLMError("LLM_API_KEY 未填写。")
        placeholders = ("your-api-key", "replace-with", "api_key", "apikey")
        lowered = self.api_key.lower()
        if any(word in lowered for word in placeholders):
            raise LLMError("LLM_API_KEY 仍是示例占位符，请在 .env 中替换为真实密钥。")
        if not self.api_key.isascii():
            raise LLMError("LLM_API_KEY 含有中文或其他非 ASCII 字符，请检查是否仍是占位文字。")
        if any(character.isspace() for character in self.api_key):
            raise LLMError("LLM_API_KEY 含有空格或换行，请重新填写。")
        if not self.base_url.startswith(("https://", "http://")):
            raise LLMError("LLM_BASE_URL 必须以 https:// 或 http:// 开头。")
        if not self.model:
            raise LLMError("LLM_MODEL 未填写。")


class OpenAICompatibleClient:
    """Minimal dependency-free client for OpenAI-compatible chat APIs."""

    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or LLMSettings.load()

    @property
    def available(self) -> bool:
        return self.settings.ready

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 1.0,
        max_tokens: int = 4096,
        timeout_seconds: int | None = None,
    ) -> str:
        self.settings.validate()
        if not isinstance(messages, list) or not messages:
            raise LLMError("LLM messages must be a non-empty list")
        if temperature != 1.0:
            raise LLMError("The configured Kimi model requires temperature=1.0")
        max_tokens = self._effective_max_tokens(max_tokens)
        payload = json.dumps(
            {
                "model": self.settings.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.settings.base_url}/chat/completions",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "catalyst-agent/0.2",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=(timeout_seconds or self.settings.timeout_seconds),
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:1000]
            raise LLMError(f"大模型接口返回 HTTP {error.code}: {detail}") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise LLMError(f"大模型请求失败: {error}") from error
        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise LLMError(f"Cannot parse LLM response: {str(body)[:1000]}") from error
        text = self._message_text(message)
        if not text:
            raise LLMError("The Kimi response did not contain a final answer.")
        return text

    @staticmethod
    def _message_text(message: Any) -> str:
        """Extract final answer text from common OpenAI-compatible response shapes."""

        if not isinstance(message, dict):
            return ""
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    value = item.get("text") or item.get("content")
                    if isinstance(value, str):
                        parts.append(value)
            return "\n".join(part.strip() for part in parts if part.strip()).strip()
        for key in ("output_text", "text"):
            value = message.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def chat_json(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        text = self.chat(
            messages,
            temperature=1.0,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        candidate = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError as error:
            raise LLMError(f"大模型没有返回合法 JSON: {text[:800]}") from error
        if not isinstance(value, dict):
            raise LLMError("大模型规划结果必须是 JSON 对象。")
        return value

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 8192,
        timeout_seconds: int | None = None,
    ) -> Iterator[str]:
        """Yield final-answer text from an OpenAI-compatible SSE response."""

        self.settings.validate()
        if not isinstance(messages, list) or not messages:
            raise LLMError("LLM messages must be a non-empty list")
        effective_tokens = self._effective_max_tokens(max_tokens)
        payload = json.dumps(
            {
                "model": self.settings.model,
                "messages": messages,
                "temperature": 1.0,
                "max_tokens": effective_tokens,
                "stream": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.settings.base_url}/chat/completions",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "User-Agent": "catalyst-agent/0.7",
            },
        )
        received = False
        try:
            with urllib.request.urlopen(
                request,
                timeout=(timeout_seconds or self.settings.timeout_seconds),
            ) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0].get("delta", {})
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                        continue
                    content = delta.get("content") if isinstance(delta, dict) else ""
                    if isinstance(content, str) and content:
                        received = True
                        yield content
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:1000]
            raise LLMError(
                f"Kimi streaming request returned HTTP {error.code}: {detail}"
            ) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise LLMError(f"Kimi streaming request failed: {error}") from error
        if not received:
            raise LLMError("The Kimi stream did not contain a final answer.")

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
        timeout_seconds: int | None = None,
        tool_choice: str = "auto",
    ) -> dict[str, Any]:
        """Return the assistant message with any requested tool calls."""

        self.settings.validate()
        if not isinstance(messages, list) or not messages:
            raise LLMError("Tool-capable LLM messages must be a non-empty list")
        if not isinstance(tools, list):
            raise LLMError("LLM tools must be a list")
        max_tokens = self._effective_max_tokens(max_tokens)
        payload = json.dumps(
            {
                "model": self.settings.model,
                "messages": messages,
                "temperature": 1.0,
                "max_tokens": max_tokens,
                "tools": tools,
                "tool_choice": tool_choice,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.settings.base_url}/chat/completions",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "catalyst-agent/0.6",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=(timeout_seconds or self.settings.timeout_seconds),
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:1000]
            raise LLMError(
                f"Tool-capable LLM request returned HTTP {error.code}: {detail}"
            ) from error
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as error:
            raise LLMError(f"Tool-capable LLM request failed: {error}") from error
        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as error:
            raise LLMError(
                f"Cannot parse tool-capable LLM response: {str(body)[:1000]}"
            ) from error
        if not isinstance(message, dict):
            raise LLMError("Tool-capable LLM response message must be an object.")
        tool_calls = message.get("tool_calls", []) or []
        if not isinstance(tool_calls, list):
            raise LLMError("LLM tool_calls must be a list.")
        return {
            "role": "assistant",
            "content": str(message.get("content", "") or ""),
            "tool_calls": tool_calls,
        }

    def _effective_max_tokens(self, requested: int) -> int:
        if isinstance(requested, bool) or int(requested) < 1:
            raise LLMError("max_tokens must be a positive integer")
        configured_max = min(max(int(self.settings.max_tokens), 1), 32768)
        value = min(int(requested), configured_max)
        if self.settings.model.lower() == "kimi-k3":
            value = max(value, min(self.settings.kimi_k3_min_tokens, configured_max))
        return value
