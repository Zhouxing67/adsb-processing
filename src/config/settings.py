"""Application configuration loaded from the local TOML file."""

from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, TomlConfigSettingsSource

from airport_surface import DEFAULT_GRAPH_PATH
from path_map import MatchConfig

CONFIG_FILE = Path("config.local.toml")


class DatabaseSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dsn: str

    @field_validator("dsn")
    @classmethod
    def validate_dsn(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("database.dsn must be a non-empty PostgreSQL connection string")
        return cleaned


class BatchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_dir: Path = Path("outputs/path_map")
    limit: NonNegativeInt | None = None


class WorkbenchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    open_browser: bool = True
    display_timezone: str = "Asia/Shanghai"

    @field_validator("display_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError(f"Unknown display timezone: {value}") from error
        return value


class ApplicationSettings(BaseSettings):
    graph_path: Path = DEFAULT_GRAPH_PATH
    database: DatabaseSettings
    matching: MatchConfig = Field(default_factory=MatchConfig)
    batch: BatchSettings = Field(default_factory=BatchSettings)
    workbench: WorkbenchSettings = Field(default_factory=WorkbenchSettings)

    model_config = SettingsConfigDict(toml_file=CONFIG_FILE, extra="forbid")

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings,
    ):
        return (TomlConfigSettingsSource(settings_cls),)


def load_settings() -> ApplicationSettings:
    if not CONFIG_FILE.is_file():
        raise ValueError(
            "Missing config.local.toml. Copy config.example.toml and set [database].path."
        )
    return ApplicationSettings()
