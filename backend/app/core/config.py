"""Application settings. All paths and ports come from .env (see CLAUDE.md);
nothing here hardcodes localhost or an absolute path. Paths use pathlib so the
app stays portable.

PROJECT_ROOT is resolved relative to this file:
  backend/app/core/config.py -> parents[3] == repo root
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _resolve(p: Path) -> Path:
    """Resolve a possibly-relative configured path against the project root."""
    p = Path(p)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Network ---
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8080
    FRONTEND_ORIGIN: str = "http://localhost:5173"
    PLATFORM_VERSION: str = "0.1.0"

    # --- Storage (repo-relative defaults for dev; absolute on the lab server) ---
    DATA_DIR: Path = PROJECT_ROOT / "data"
    DB_PATH: Path = PROJECT_ROOT / "data" / "bst.db"
    RECORDINGS_DIR: Path = PROJECT_ROOT / "data" / "recordings"
    EXPORTS_DIR: Path = PROJECT_ROOT / "data" / "exports"
    LOGS_DIR: Path = PROJECT_ROOT / "data" / "logs"
    SESSIONS_DIR: Path = PROJECT_ROOT / "data" / "sessions"
    BACKUPS_DIR: Path = PROJECT_ROOT / "data" / "backups"
    CONFIGS_DIR: Path = PROJECT_ROOT / "configs"

    # Timestamped DB backups: on startup (pre-create_all) and on session
    # completion. Keep the last N copies; backups are non-destructive file copies.
    DB_BACKUP_KEEP: int = 20

    # --- Perception orchestrator (read-only; see perception_integration.md) ---
    PERCEPTION_BASE_URL: str = "http://localhost:8000"
    PERCEPTION_POLL_MS_ASR: int = 500
    PERCEPTION_POLL_MS_EMOTION: int = 1000
    PERCEPTION_POLL_MS_GESTURE: int = 500
    PERCEPTION_HEALTH_MS: int = 5000
    PERCEPTION_HTTP_TIMEOUT_MS: int = 2000

    @property
    def db_path(self) -> Path:
        return _resolve(self.DB_PATH)

    @property
    def backups_dir(self) -> Path:
        return _resolve(self.BACKUPS_DIR)

    @property
    def configs_dir(self) -> Path:
        return _resolve(self.CONFIGS_DIR)

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def data_dirs(self) -> list[Path]:
        """Directories the app owns and may create on startup. The recordings
        dir is included for dev; on the server it is a mounted SSD and the
        Day-6 pre-session checklist (P0.12) verifies it is a real mount point
        with free space before any session starts."""
        return [
            _resolve(self.DATA_DIR),
            self.db_path.parent,
            _resolve(self.RECORDINGS_DIR),
            _resolve(self.EXPORTS_DIR),
            _resolve(self.LOGS_DIR),
            _resolve(self.SESSIONS_DIR),
            self.backups_dir,
        ]

    def ensure_directories(self) -> None:
        for d in self.data_dirs:
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
