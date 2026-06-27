"""Config-driven questionnaire engine (P0.4).

Questionnaire content lives in configs/questionnaires/*.yaml and is participant-
independent. On startup we register each config into the ``questionnaires`` table
(provenance: key/version/title/scale_type/item_count/timepoint/path/hash). NO
copyrighted item text is stored in the DB; only stable item_ids are persisted in
responses (the wording lives in the config files, which carry placeholders until
the official instruments are dropped in -- a config edit, no code change).

This module is also the validator: it resolves each item's type and response
scale from the config and turns a raw answer into (response_raw,
response_numeric), raising a clean 422 for anything the config does not allow
(the protocol_id lesson). The engine does NOT score (scoring is post hoc, PRD).
"""

from __future__ import annotations

import hashlib
import json
import logging
from functools import lru_cache
from pathlib import Path

import yaml
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.questionnaire import Questionnaire

logger = logging.getLogger("bst.questionnaire")

# Item types the engine understands. 'likert' uses a numeric scale (item-level
# `scale` or the questionnaire-level `response_scale`); the rest are self-contained.
_NUMERIC_TYPES = {"likert", "integer", "number"}
_CHOICE_TYPES = {"single_choice", "multi_choice"}
_TEXT_TYPES = {"text"}


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _questionnaires_dir() -> Path:
    return settings.configs_dir / "questionnaires"


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=64)
def _load_yaml(path: str, file_hash: str) -> dict:
    """Parse a config file. file_hash is part of the cache key so edits to the
    file (new hash) bypass the cache."""
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def register_questionnaires(db: Session) -> list[Questionnaire]:
    """Idempotently upsert all questionnaire configs into ``questionnaires``.
    Additive only: never deletes a registered questionnaire."""
    directory = _questionnaires_dir()
    registered: list[Questionnaire] = []
    if not directory.exists():
        logger.info("No questionnaires config dir at %s", directory)
        return registered

    for path in sorted(directory.glob("*.y*ml")):
        cfg = _load_yaml(str(path), _hash_file(path))
        if not cfg or "questionnaire_key" not in cfg:
            logger.warning("Skipping questionnaire config without questionnaire_key: %s", path)
            continue

        key = cfg["questionnaire_key"]
        version = str(cfg.get("version", ""))
        file_hash = _hash_file(path)
        items = cfg.get("items", []) or []
        timepoint = cfg.get("timepoint", "na")

        row = db.scalar(
            select(Questionnaire).where(
                Questionnaire.questionnaire_key == key,
                Questionnaire.version == version,
            )
        )
        if row is None:
            row = Questionnaire(
                questionnaire_key=key,
                version=version,
                title=cfg.get("title"),
                scale_type=cfg.get("scale_type"),
                item_count=len(items),
                timepoint=timepoint,
                config_path=str(path),
                config_hash=file_hash,
            )
            db.add(row)
            db.flush()
        else:
            row.title = cfg.get("title")
            row.scale_type = cfg.get("scale_type")
            row.item_count = len(items)
            row.timepoint = timepoint
            row.config_path = str(path)
            row.config_hash = file_hash

        registered.append(row)
        logger.info("Registered questionnaire %s v%s (%s)", key, version, path.name)

    db.commit()
    return registered


def get_questionnaire(
    db: Session, questionnaire_key: str, version: str | None = None
) -> Questionnaire | None:
    """Return the registry row for a key (latest registered if version is None)."""
    stmt = select(Questionnaire).where(Questionnaire.questionnaire_key == questionnaire_key)
    if version is not None:
        stmt = stmt.where(Questionnaire.version == version)
    return db.scalars(stmt.order_by(Questionnaire.id.desc())).first()


def get_questionnaire_config(
    db: Session, questionnaire_key: str, version: str | None = None
) -> dict | None:
    """Return the parsed config for a registered questionnaire, or None."""
    row = get_questionnaire(db, questionnaire_key, version)
    if row is None or not row.config_path:
        return None
    return _load_yaml(row.config_path, row.config_hash or "")


# --- rendering -------------------------------------------------------------


def _item_type(item: dict, config: dict) -> str:
    return item.get("type") or ("likert" if config.get("response_scale") else "text")


def _item_scale(item: dict, config: dict) -> dict | None:
    return item.get("scale") or config.get("response_scale")


def build_render_spec(config: dict) -> dict:
    """A render-ready view of a questionnaire for the tablet: every item carries
    a resolved ``type`` and (for numeric items) a resolved ``scale`` so the
    client never has to know the engine's defaulting rules."""
    items_out = []
    for item in config.get("items", []):
        itype = _item_type(item, config)
        out = {
            "item_id": item["item_id"],
            "index": item.get("index"),
            "type": itype,
            "text": item.get("text", ""),
            "required": item.get("required", True),
        }
        if itype in _NUMERIC_TYPES:
            scale = _item_scale(item, config) if itype == "likert" else None
            if scale is not None:
                out["scale"] = scale
            for bound in ("min", "max"):
                if bound in item:
                    out[bound] = item[bound]
        if itype in _CHOICE_TYPES:
            out["options"] = item.get("options", [])
        items_out.append(out)

    return {
        "questionnaire_key": config["questionnaire_key"],
        "version": str(config.get("version", "")),
        "title": config.get("title"),
        "timepoint": config.get("timepoint", "na"),
        "scale_type": config.get("scale_type"),
        "response_scale": config.get("response_scale"),
        "items": items_out,
    }


# --- validation / normalization -------------------------------------------


def _coerce_numeric(item_id: str, value) -> float:
    if isinstance(value, bool):  # bool is an int subclass; reject it explicitly
        raise _unprocessable(f"item '{item_id}': expected a number, got a boolean")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise _unprocessable(f"item '{item_id}': expected a number, got {value!r}")


def _validate_one(item: dict, config: dict, value) -> tuple[str | None, float | None]:
    """Validate a single answer against its config item. Returns
    (response_raw, response_numeric) or raises 422."""
    item_id = item["item_id"]
    itype = _item_type(item, config)

    if itype == "likert":
        scale = _item_scale(item, config) or {}
        lo, hi = scale.get("min"), scale.get("max")
        num = _coerce_numeric(item_id, value)
        if num != int(num):
            raise _unprocessable(f"item '{item_id}': likert response must be a whole number")
        num = int(num)
        if lo is not None and hi is not None and not (lo <= num <= hi):
            raise _unprocessable(
                f"item '{item_id}': response {num} outside scale [{lo}, {hi}]"
            )
        return str(num), float(num)

    if itype in ("integer", "number"):
        num = _coerce_numeric(item_id, value)
        if itype == "integer":
            if num != int(num):
                raise _unprocessable(f"item '{item_id}': expected a whole number")
            num = float(int(num))
        lo, hi = item.get("min"), item.get("max")
        if lo is not None and num < lo:
            raise _unprocessable(f"item '{item_id}': {num} below minimum {lo}")
        if hi is not None and num > hi:
            raise _unprocessable(f"item '{item_id}': {num} above maximum {hi}")
        raw = str(int(num)) if itype == "integer" else str(num)
        return raw, num

    if itype == "single_choice":
        valid = {o["value"] for o in item.get("options", [])}
        if value not in valid:
            raise _unprocessable(
                f"item '{item_id}': '{value}' not a valid option; valid: {sorted(valid)}"
            )
        return str(value), None

    if itype == "multi_choice":
        valid = {o["value"] for o in item.get("options", [])}
        if not isinstance(value, list):
            raise _unprocessable(f"item '{item_id}': multi_choice expects a list")
        bad = [v for v in value if v not in valid]
        if bad:
            raise _unprocessable(
                f"item '{item_id}': invalid options {bad}; valid: {sorted(valid)}"
            )
        return json.dumps(value), None

    if itype == "text":
        if not isinstance(value, str):
            raise _unprocessable(f"item '{item_id}': text expects a string")
        return value, None

    raise _unprocessable(f"item '{item_id}': unsupported item type '{itype}'")


def normalize_answers(
    config: dict, answers: dict, *, require_required: bool
) -> list[dict]:
    """Validate a {item_id: value} map against the config. Unknown item_ids and
    out-of-range/invalid values raise 422. When ``require_required`` is set
    (final submit), every required item must be present. Returns a list of
    {item_id, item_index, response_raw, response_numeric}."""
    items_by_id = {it["item_id"]: it for it in config.get("items", [])}

    unknown = [k for k in answers if k not in items_by_id]
    if unknown:
        raise _unprocessable(
            f"unknown item_id(s) {sorted(unknown)} for questionnaire "
            f"'{config.get('questionnaire_key')}'"
        )

    if require_required:
        missing = [
            it["item_id"]
            for it in config.get("items", [])
            if it.get("required", True) and it["item_id"] not in answers
        ]
        if missing:
            raise _unprocessable(f"missing required item(s): {sorted(missing)}")

    normalized = []
    for item_id, value in answers.items():
        item = items_by_id[item_id]
        raw, numeric = _validate_one(item, config, value)
        normalized.append(
            {
                "item_id": item_id,
                "item_index": item.get("index"),
                "response_raw": raw,
                "response_numeric": numeric,
            }
        )
    return normalized
