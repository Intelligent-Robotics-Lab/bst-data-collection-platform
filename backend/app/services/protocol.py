"""DTT protocol config loading and registration.

Protocol content lives in configs/dtt_protocols/*.yaml and is participant-
independent. On startup we register each config into dtt_protocols + dtt_phases
(provenance: key, version, path, hash). The trial API validates against the
parsed config, loaded fresh from disk (cached by path+hash).
"""

from __future__ import annotations

import hashlib
import json
import logging
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dtt import DttPhase, DttProtocol

logger = logging.getLogger("bst.protocol")


def _protocols_dir() -> Path:
    return settings.configs_dir / "dtt_protocols"


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=32)
def _load_yaml(path: str, file_hash: str) -> dict:
    """Parse a config file. file_hash is part of the cache key so edits to the
    file (new hash) bypass the cache."""
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def register_protocols(db: Session) -> list[DttProtocol]:
    """Idempotently upsert all protocol configs into dtt_protocols + dtt_phases.
    Additive only: never deletes protocols or phases."""
    directory = _protocols_dir()
    registered: list[DttProtocol] = []
    if not directory.exists():
        logger.info("No dtt_protocols config dir at %s", directory)
        return registered

    for path in sorted(directory.glob("*.y*ml")):
        cfg = _load_yaml(str(path), _hash_file(path))
        if not cfg or "protocol_key" not in cfg:
            logger.warning("Skipping protocol config without protocol_key: %s", path)
            continue

        key = cfg["protocol_key"]
        version = str(cfg.get("version", ""))
        file_hash = _hash_file(path)

        proto = db.scalar(
            select(DttProtocol).where(
                DttProtocol.protocol_key == key, DttProtocol.version == version
            )
        )
        if proto is None:
            proto = DttProtocol(
                protocol_key=key,
                version=version,
                title=cfg.get("title"),
                config_path=str(path),
                config_hash=file_hash,
            )
            db.add(proto)
            db.flush()
        else:
            proto.title = cfg.get("title")
            proto.config_path = str(path)
            proto.config_hash = file_hash

        for phase in cfg.get("phases", []):
            existing = db.scalar(
                select(DttPhase).where(
                    DttPhase.protocol_id == proto.protocol_id,
                    DttPhase.phase_key == phase["phase_key"],
                )
            )
            target_skills_json = json.dumps(phase.get("target_skills", []))
            if existing is None:
                db.add(
                    DttPhase(
                        protocol_id=proto.protocol_id,
                        phase_key=phase["phase_key"],
                        phase_label=phase.get("label"),
                        order_index=phase.get("order_index"),
                        target_skills_json=target_skills_json,
                    )
                )
            else:
                existing.phase_label = phase.get("label")
                existing.order_index = phase.get("order_index")
                existing.target_skills_json = target_skills_json

        registered.append(proto)
        logger.info("Registered protocol %s v%s (%s)", key, version, path.name)

    db.commit()
    return registered


def get_protocol_config(db: Session, protocol_id: int) -> dict | None:
    """Return the parsed config for a registered protocol, or None."""
    proto = db.get(DttProtocol, protocol_id)
    if proto is None or not proto.config_path:
        return None
    return _load_yaml(proto.config_path, proto.config_hash or "")
