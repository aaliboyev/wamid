import json
from dataclasses import dataclass, field

import httpx

from ..config import Config


class LlmError(Exception):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class TurnResult:
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    assistant_message: dict | None = None   # raw assistant message, append to history verbatim


class LlmService:
    """Low-level OpenAI-compatible chat-completions client.
    Domain prompts and tool schemas live in the services that use them."""

    def __init__(self, cfg: Config, client: httpx.Client | None = None):
        self.cfg = cfg
        self._client = client or httpx.Client(timeout=cfg.llm.timeout_s)

    def _post(self, payload: dict) -> dict:
        """POST with one retry on transient failures (timeouts, 5xx, network errors).
        4xx is our bug — fail fast, don't retry."""
        url = self.cfg.llm.endpoint.rstrip("/") + "/chat/completions"
        headers = {}
        if self.cfg.llm.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.llm.api_key}"
        last: Exception | None = None
        for attempt in range(2):
            try:
                r = self._client.post(url, headers=headers, json=payload)
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                if 500 <= e.response.status_code < 600 and attempt == 0:
                    last = e
                    continue
                raise LlmError(f"llm request failed: {e}") from e
            except (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
            ) as e:
                last = e
                if attempt == 0:
                    continue
                raise LlmError(f"llm request failed: {e}") from e
            except httpx.HTTPError as e:
                raise LlmError(f"llm request failed: {e}") from e
        raise LlmError(f"llm request failed after retry: {last}") from last

    def complete(self, messages: list[dict], temperature: float = 0.4) -> str:
        data = self._post(
            {"model": self.cfg.llm.model, "messages": messages, "temperature": temperature}
        )
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError) as e:
            raise LlmError(f"unexpected llm response: {data}") from e

    def chat(self, system: str, user: str, temperature: float = 0.4) -> str:
        return self.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=temperature,
        )

    def step(
        self,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.4,
    ) -> TurnResult:
        """One turn with tool-call support. Returns parsed tool calls or text.
        The caller is responsible for appending `assistant_message` to history."""
        data = self._post(
            {
                "model": self.cfg.llm.model,
                "messages": messages,
                "tools": tools,
                "temperature": temperature,
            }
        )
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise LlmError(f"unexpected llm response: {data}") from e

        calls: list[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            args_raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), args=args))

        return TurnResult(
            text=(msg.get("content") or "").strip() or None,
            tool_calls=calls,
            assistant_message=msg,
        )

    def close(self) -> None:
        self._client.close()
