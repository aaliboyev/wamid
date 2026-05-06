"""Shared pytest fixtures.
- `cfg` builds an isolated Config pointed at a per-test sqlite file
- `session` opens a Session and runs all migrations
- `fake_llm` is a deterministic stand-in for LlmService — no network, no surprises
"""

import os
from dataclasses import dataclass, field
from typing import Callable

import pytest

from wamid import config as config_mod
from wamid import db as db_mod
from wamid.config import ApiConfig, Config, DbConfig, LlmConfig
from wamid.services.llm import TurnResult
from wamid.services.session import Session


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    # Strip any WAMID_* env vars so test config isn't polluted by the dev shell.
    for k in list(os.environ):
        if k.startswith("WAMID_") or k == "SSL_CERT_FILE":
            monkeypatch.delenv(k, raising=False)
    # Point the toml loader at a nonexistent path so `Config(...)` only sees init kwargs.
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "noop.toml")


@pytest.fixture
def cfg(tmp_path, monkeypatch) -> Config:
    # Use env override — pydantic-settings' source order is env > toml > init,
    # so env is the most reliable way to force a fresh per-test db.
    monkeypatch.setenv("WAMID_DB__URL", f"file:{tmp_path / 'test.db'}")
    return config_mod.load()


@pytest.fixture
def session(cfg):
    with db_mod.client(cfg) as c:
        db_mod.migrate(c)
        yield Session(client=c, cfg=cfg)


@dataclass
class FakeLlm:
    """Stand-in for LlmService. `chat` returns canned text (or echoes input).
    `step` consumes pre-queued TurnResult objects for tool-call flows."""
    chat_response: Callable[[str, str], str] = field(default=lambda system, user: f"[summary] {user}")
    chat_calls: list[tuple[str, str]] = field(default_factory=list)
    step_queue: list[TurnResult] = field(default_factory=list)
    step_calls: list[tuple[list[dict], list[dict]]] = field(default_factory=list)

    def chat(self, system: str, user: str, temperature: float = 0.4) -> str:
        self.chat_calls.append((system, user))
        return self.chat_response(system, user)

    def complete(self, messages, temperature: float = 0.4) -> str:
        return self.chat_response("", messages[-1]["content"] if messages else "")

    def step(self, messages, tools, temperature: float = 0.4) -> TurnResult:
        self.step_calls.append((list(messages), list(tools)))
        if not self.step_queue:
            raise RuntimeError("FakeLlm.step called with no queued response")
        return self.step_queue.pop(0)

    def close(self) -> None:
        pass


@pytest.fixture
def fake_llm() -> FakeLlm:
    return FakeLlm()
