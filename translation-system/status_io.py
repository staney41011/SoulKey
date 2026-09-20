import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from config import SPREADSHEET_ID, STATUS_SHEET_NAME, TIMEZONE
from google_io import build_google_services

VALID_STATUSES = {
    "pending",
    "queued",
    "running",
    "needs_review",
    "done",
    "error",
    "stale",
}


def now_text():
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")


def new_run_id(task_id: str, stage: str):
    explicit = str(os.environ.get("SOULKEY_RUN_ID") or "").strip()
    if explicit:
        return explicit
    stamp = datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:8]
    return f"{task_id}-{stage}-{stamp}-{short}"


def append_status(
    task_id: str,
    stage: str,
    status: str,
    *,
    sheets=None,
    run_id: str = "",
    progress=None,
    message: str = "",
    started_at: str = "",
    finished_at: str = "",
    error_code: str = "",
    error_message: str = "",
    input_revision: str = "",
    output_revision: str = "",
):
    status = str(status or "").strip().lower()
    if status not in VALID_STATUSES:
        raise ValueError(f"不支援的 status: {status}")

    task_id = str(task_id or "").strip()
    stage = str(stage or "").strip()
    if not task_id or not stage:
        raise ValueError("task_id / stage 不可為空")

    if sheets is None:
        _, sheets = build_google_services()

    updated_at = now_text()
    if status == "running" and not started_at:
        started_at = updated_at
    if status in {"done", "needs_review", "error", "stale"} and not finished_at:
        finished_at = updated_at

    if progress is None or progress == "":
        progress_value = ""
    else:
        try:
            progress_value = max(0, min(100, int(progress)))
        except Exception:
            progress_value = ""

    values = [[
        task_id,
        stage,
        status,
        run_id,
        progress_value,
        str(message or "")[:1000],
        started_at,
        finished_at,
        updated_at,
        str(error_code or "")[:120],
        str(error_message or "")[:1000],
        str(input_revision or "")[:200],
        str(output_revision or "")[:200],
    ]]

    (
        sheets.spreadsheets()
        .values()
        .append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{STATUS_SHEET_NAME}!A:M",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        )
        .execute()
    )

    print(
        f"[STATUS] {task_id} / {stage} -> {status}"
        + (f" ({progress_value}%)" if progress_value != "" else "")
    )

    return {
        "task_id": task_id,
        "stage": stage,
        "status": status,
        "run_id": run_id,
        "progress": progress_value,
        "message": message,
        "updated_at": updated_at,
    }


def mark_running(task_id, stage, *, sheets=None, run_id="", message="", progress=0):
    return append_status(
        task_id,
        stage,
        "running",
        sheets=sheets,
        run_id=run_id,
        progress=progress,
        message=message,
    )


def mark_done(task_id, stage, *, sheets=None, run_id="", message="", progress=100, output_revision=""):
    return append_status(
        task_id,
        stage,
        "done",
        sheets=sheets,
        run_id=run_id,
        progress=progress,
        message=message,
        output_revision=output_revision,
    )


def mark_needs_review(task_id, stage, *, sheets=None, run_id="", message="", progress=100, output_revision=""):
    return append_status(
        task_id,
        stage,
        "needs_review",
        sheets=sheets,
        run_id=run_id,
        progress=progress,
        message=message,
        output_revision=output_revision,
    )


def mark_error(task_id, stage, *, sheets=None, run_id="", exc=None, message=""):
    error_message = message or (f"{type(exc).__name__}: {exc}" if exc else "")
    return append_status(
        task_id,
        stage,
        "error",
        sheets=sheets,
        run_id=run_id,
        message=error_message,
        error_code=(type(exc).__name__ if exc else "error"),
        error_message=error_message,
    )
