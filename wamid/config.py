from pathlib import Path
from typing import Tuple, Type

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

CONFIG_DIR = Path.home() / ".wamid"
CONFIG_PATH = CONFIG_DIR / "config.toml"


class DbConfig(BaseModel):
    url: str = f"file:{CONFIG_DIR / 'wamid.db'}"
    token: str = ""


class ApiConfig(BaseModel):
    read_only: bool = False
    write_token: str = ""  # if set, writes require Authorization: Bearer <token>


class LlmConfig(BaseModel):
    endpoint: str = "http://localhost:8080/v1"
    model: str = "gemma-3-27b"
    api_key: str = ""
    timeout_s: float = 300.0
    reasoning_effort: str | None = None  # "none" disables thinking on Ollama /v1


class Config(BaseSettings):
    db: DbConfig = Field(default_factory=DbConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)

    model_config = SettingsConfigDict(
        toml_file=CONFIG_PATH,
        env_prefix="WAMID_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        # env > toml > defaults
        return (env_settings, TomlConfigSettingsSource(settings_cls), init_settings)


def load() -> Config:
    return Config()


DEFAULT_TOML = """\
[db]
url = "file:~/.wamid/wamid.db"
token = ""

[llm]
endpoint = "http://localhost:8080/v1"
model = "gemma-3-27b"
api_key = ""
reasoning_effort = "none"

[api]
read_only = false
write_token = ""
"""


def write_default_config() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(DEFAULT_TOML)
    return CONFIG_PATH
