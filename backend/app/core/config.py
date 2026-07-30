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
    # Default target for the console's "Save" action: a copy of a finished
    # recording is placed here (the original in RECORDINGS_DIR is never moved).
    SAVED_RECORDINGS_DIR: Path = PROJECT_ROOT / "data" / "saved_recordings"
    EXPORTS_DIR: Path = PROJECT_ROOT / "data" / "exports"
    LOGS_DIR: Path = PROJECT_ROOT / "data" / "logs"
    SESSIONS_DIR: Path = PROJECT_ROOT / "data" / "sessions"
    BACKUPS_DIR: Path = PROJECT_ROOT / "data" / "backups"
    CONFIGS_DIR: Path = PROJECT_ROOT / "configs"

    # Timestamped DB backups: on startup (pre-create_all) and on session
    # completion. Keep the last N copies; backups are non-destructive file copies.
    DB_BACKUP_KEEP: int = 20

    # --- Perception orchestrator (read-only consumer; see perception_integration.md) ---
    # READ-ONLY: the adapter only ever GETs /state/* and /health. It never POSTs
    # or otherwise mutates the orchestrator. OFF by default so dev/CI never poll;
    # the lab server sets PERCEPTION_ENABLED=true.
    PERCEPTION_ENABLED: bool = False
    PERCEPTION_BASE_URL: str = "http://localhost:8000"
    PERCEPTION_POLL_MS_ASR: int = 500
    PERCEPTION_POLL_MS_EMOTION: int = 200  # 5 fps (per study request; doc default was 1000)
    PERCEPTION_POLL_MS_GESTURE: int = 500
    PERCEPTION_HEALTH_MS: int = 5000
    PERCEPTION_HTTP_TIMEOUT_MS: int = 2000
    # Per-task enable flags so a study can log only the streams it needs.
    PERCEPTION_ASR_ENABLED: bool = True
    PERCEPTION_EMOTION_ENABLED: bool = True
    PERCEPTION_GESTURE_ENABLED: bool = True
    # Perception is high-frequency (5-10 Hz). By default we do NOT mirror every
    # reading onto the session timeline (that would bury trials/self-reports under
    # thousands of rows); the timeline carries only outage/recovery transitions.
    # Set true to also emit one timeline event per reading.
    PERCEPTION_TIMELINE_EVERY_READING: bool = False

    # --- A/V recording (P0.8) ---
    # Defaults below ARE the Day-1 verified Brio/NVENC capture command. Recording
    # is OFF by default so dev/CI never spawn ffmpeg; the lab server's .env sets
    # RECORDING_ENABLED=true. Every part of the command is a setting so the lab
    # can swap the device or point at the mounted SSD with no code change, and so
    # dev/CI can use a synthetic lavfi source (RECORDING_USE_TEST_SOURCE=true).
    RECORDING_ENABLED: bool = False
    RECORDING_FFMPEG_BIN: str = "ffmpeg"
    RECORDING_VIDEO_DEVICE: str = "/dev/video0"          # Brio, MJPEG input
    RECORDING_VIDEO_INPUT_FORMAT: str = "v4l2"
    RECORDING_VIDEO_INPUT_PIXEL: str = "mjpeg"           # ffmpeg -input_format
    RECORDING_VIDEO_SIZE: str = "1920x1080"
    RECORDING_FRAMERATE: int = 30
    RECORDING_AUDIO_DEVICE: str = "hw:CARD=BRIO,DEV=0"    # pin by name, not hw:4,0
    RECORDING_AUDIO_INPUT_FORMAT: str = "alsa"
    RECORDING_THREAD_QUEUE_SIZE: int = 1024
    RECORDING_VIDEO_CODEC: str = "h264_nvenc"
    RECORDING_VIDEO_BITRATE: str = "5M"
    RECORDING_PIX_FMT: str = "yuv420p"
    RECORDING_AUDIO_CODEC: str = "aac"
    RECORDING_AUDIO_BITRATE: str = "128k"
    RECORDING_CONTAINER: str = "mp4"
    # ffmpeg 4.4 uses -vsync passthrough; 5.x renamed it to -fps_mode. Configurable
    # so a future ffmpeg upgrade on the server is an .env change, not a code edit.
    RECORDING_VSYNC: str = "passthrough"
    # Settling window after spawn to catch immediate failures (device busy, bad
    # args) so they are logged as a failed recording instead of a silent dead row.
    RECORDING_START_SETTLE_S: float = 0.4
    # Graceful-stop budget: how long to wait for ffmpeg to exit after 'q' before
    # escalating to SIGTERM (still never SIGKILL first).
    RECORDING_STOP_TIMEOUT_S: float = 10.0
    # dev/CI only: synthetic A/V via lavfi (no camera, no GPU). Keeps every encoder
    # flag identical so the wiring under test matches the real command.
    RECORDING_USE_TEST_SOURCE: bool = False

    # --- Pre-session preflight gate (P0.12) ---
    # A session start is blocked when a REQUIRED check fails, unless the operator
    # overrides (which is logged to the timeline). Two pilots ran blind (no audio,
    # no perception) because the old checklist verified nothing; these are the
    # thresholds the real checks use.
    PREFLIGHT_MIN_FREE_GB: float = 5.0  # recordings mount must have at least this free
    PREFLIGHT_TABLET_STALE_S: float = 15.0  # tablet "connected" if it polled within this
    # The camera preflight check does a real 1-frame capture probe (not just a
    # "does /dev/video0 exist" test) so a device HELD by another process -- e.g. a
    # leftover ffmpeg -- is caught. This bounds that probe.
    PREFLIGHT_CAMERA_PROBE_S: float = 8.0

    @property
    def db_path(self) -> Path:
        return _resolve(self.DB_PATH)

    @property
    def recordings_dir(self) -> Path:
        return _resolve(self.RECORDINGS_DIR)

    @property
    def saved_recordings_dir(self) -> Path:
        return _resolve(self.SAVED_RECORDINGS_DIR)

    @property
    def logs_dir(self) -> Path:
        return _resolve(self.LOGS_DIR)

    @property
    def backups_dir(self) -> Path:
        return _resolve(self.BACKUPS_DIR)

    @property
    def exports_dir(self) -> Path:
        return _resolve(self.EXPORTS_DIR)

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
            self.saved_recordings_dir,
            _resolve(self.EXPORTS_DIR),
            _resolve(self.LOGS_DIR),
            _resolve(self.SESSIONS_DIR),
            self.backups_dir,
        ]

    def ensure_directories(self) -> None:
        for d in self.data_dirs:
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
