#!/usr/bin/env python3
"""Fail closed before Kaggle starts if the legacy Apps Script runtime expired.

The worker still obtains a short-lived Google OAuth token from Apps Script.
This check never saves or prints the token, nonce, or response body.
A GitHub job rerun reuses old workflow_dispatch inputs, including the original
nonce; such a rerun must not consume GPU hours when its OAuth lease is stale.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from urllib.request import Request, urlopen


class PreflightError(RuntimeError):
    """Only sanitized, non-secret reason codes are allowed."""


def required_remaining_seconds(stage: str, lang: str = "", langs: str = "") -> int:
    """Reserve enough time to complete the likely Kaggle work before nonce expiry."""
    if lang == "central4":
        return 5 * 3600
    if stage == "batch":
        return 4 * 3600
    if stage in {"multi", "finish"} and langs.strip():
        return 4 * 3600
    if stage in {"zh", "asr", "tts", "finish"}:
        return 2 * 3600
    return 3600


def validate_bridge_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "script.google.com"
            or parsed.username or parsed.password or parsed.port is not None
            or not parsed.path.startswith("/macros/s/")
            or not parsed.path.endswith("/exec")):
        raise PreflightError("invalid_apps_script_bridge_url")


def validate_runtime(payload: object, task_id: str, stage: str,
                     minimum_seconds: int, now: datetime | None = None) -> int:
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise PreflightError("runtime_nonce_invalid_or_expired")
    if payload.get("task_id") != task_id or payload.get("stage") != stage:
        raise PreflightError("runtime_task_or_stage_mismatch")
    if not isinstance(payload.get("google_access_token"), str) or not payload["google_access_token"]:
        raise PreflightError("runtime_google_oauth_unavailable")
    try:
        expires = datetime.fromisoformat(str(payload["expires_at"]).replace("Z", "+00:00"))
        if expires.tzinfo is None:
            raise ValueError("timezone required")
        remaining = int((expires - (now or datetime.now(timezone.utc))).total_seconds())
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise PreflightError("runtime_expiry_invalid") from exc
    if remaining < minimum_seconds:
        raise PreflightError("runtime_too_old_for_safe_kaggle_run")
    return remaining


def check() -> int:
    bridge = os.environ.get("SOULKEY_PREFLIGHT_BRIDGE_URL", "").strip()
    nonce = os.environ.get("SOULKEY_PREFLIGHT_RUNTIME_NONCE", "").strip()
    task = os.environ.get("SOULKEY_PREFLIGHT_TASK_ID", "").strip()
    stage = os.environ.get("SOULKEY_PREFLIGHT_STAGE", "").strip()
    lang = os.environ.get("SOULKEY_PREFLIGHT_LANG", "").strip()
    langs = os.environ.get("SOULKEY_PREFLIGHT_LANGS", "").strip()
    validate_bridge_url(bridge)
    if not nonce or not task or not stage:
        raise PreflightError("missing_task_stage_or_runtime_nonce")
    parsed = urlsplit(bridge)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend([("action", "worker_runtime"), ("nonce", nonce)])
    endpoint = urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                           urlencode(query), ""))
    try:
        with urlopen(Request(endpoint, headers={"Accept": "application/json"}), timeout=30) as res:
            payload = json.loads(res.read(65536).decode("utf-8"))
    except Exception as exc:
        # Do not log the request URL; it contains the short-lived nonce.
        raise PreflightError("apps_script_runtime_endpoint_unavailable") from exc
    remaining = validate_runtime(
        payload, task, stage, required_remaining_seconds(stage, lang, langs))
    print("SOULKEY_LEGACY_RUNTIME_PREFLIGHT_OK", task, stage,
          "safe_minutes_remaining=" + str(remaining // 60), flush=True)
    return remaining


if __name__ == "__main__":
    try:
        check()
    except PreflightError as exc:
        print("::error::SOULKEY_RUNTIME_PREFLIGHT_BLOCKED " + str(exc), flush=True)
        print("Please start a NEW authorized SoulKey Studio job; do not rerun an old GitHub job.", flush=True)
        sys.exit(2)
