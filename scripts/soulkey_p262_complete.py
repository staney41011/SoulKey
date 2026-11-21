#!/usr/bin/env python3
"""P262 four-lesson idempotent Sheets→Gemma QA→TTS recovery."""
import json
import os
import sys
import time
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

TASKS = ["P262-L01", "P262-L02", "P262-L03", "P262-L04"]
BASE = os.environ.get("SOULKEY_BRIDGE_URL", "").strip()
SECRET = os.environ.get("SOULKEY_AUDIO_RECONCILE_KEY", "").strip()
DEADLINE = time.monotonic() + int(os.environ.get("P262_MAX_SECONDS", "9600"))
QUOTA_MAX = 4500


def log(line):
    print("[P262] " + line, flush=True)


def post(**kwargs):
    payload = {"action": "audio_reconcile", "audio_key": SECRET}
    payload.update(kwargs)
    request = Request(BASE, data=urlencode(payload).encode(), method="POST")
    try:
        with urlopen(request, timeout=325) as resp:
            result = json.load(resp)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("Bridge request failed: " + type(exc).__name__) from exc
    if not isinstance(result, dict):
        raise RuntimeError("Malformed signed Bridge result")
    return result


def sheets(action, task="", lang=""):
    result = post(native_sheets_action=action,
                  native_sheets_task=task,
                  native_sheets_lang=lang)
    if result.get("stage") != "native_sheets":
        raise RuntimeError("Wrong action response from signed bridge")
    return result


def state():
    data = sheets("p262_progress")
    if not data.get("ok"):
        raise RuntimeError("Cannot inspect current period checkpoints")
    rows = {x["task"]: x for x in data.get("status", {}).get("jobs", [])
            if x.get("task") in TASKS}
    lessons = {x["task"]: x for x in data.get("lessons", [])
               if x.get("task") in TASKS}
    if len(rows) != 4 or len(lessons) != 4:
        raise RuntimeError("One or more P262 sources missing")
    return rows, lessons


def totals(rows):
    summary = []
    for task in TASKS:
        completed = int(rows[task].get("translated") or 0)
        required = int(rows[task].get("total") or 0)
        if required <= 0 or completed > required:
            raise RuntimeError("Invalid Sheets checkpoint: " + task)
        summary.append((completed, required))
    return summary


def all_copied(lessons):
    return all(lane.get("formal_copied")
               for lesson in lessons.values()
               for lane in lesson.get("langs", {}).values())


def show(rows, lessons):
    for task in TASKS:
        row = rows[task]
        lanes = lessons[task].get("langs", {})
        verified = sum(lane.get("qa") == "approved_risk_based"
                       for lane in lanes.values())
        copied = sum(bool(lane.get("formal_copied"))
                     for lane in lanes.values())
        log(f"{task} sheets={row['translated']}/{row['total']} "
            f"QA={verified}/{len(lanes)} "
            f"formal_copies={copied}/{len(lanes)}")


def report(message, rows=None, lessons=None):
    output = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as file:
        file.write("### SoulKey 262 專用翻譯補完\n\n" + message + "\n\n")
        if rows and lessons:
            file.write("| Task | Sheets | Gemma4 | Formal MP3 copied |\n"
                       "|---|---:|---:|---:|\n")
            for task in TASKS:
                row = rows[task]
                lanes = list(lessons[task].get("langs", {}).values())
                qa = sum(x.get("qa") == "approved_risk_based" for x in lanes)
                copied = sum(bool(x.get("formal_copied")) for x in lanes)
                file.write(f"|{task}|{row['translated']}/{row['total']}|"
                           f"{qa}/{len(lanes)}|{copied}/{len(lanes)}|\n")


def push_audio(lessons):
    queued = 0
    for task in TASKS:
        for lang, lane in lessons[task].get("langs", {}).items():
            if time.monotonic() > DEADLINE-300:
                return queued
            if lane.get("qa") not in ("approved_risk_based", "approved_english_final") or lane.get("formal_copied"):
                continue
            res = post(native_audio_task=task, native_audio_lang=lang)
            if res.get("stage") != "native_audio":
                raise RuntimeError("Incorrect private audio routing")
            if not res.get("ok"):
                reason = str(res.get("reason") or "unknown")
                if reason == "busy":
                    log(f"{task}/{lang}: audio mutex busy; retry later")
                else:
                    log(f"::warning title=Audio pending::{task}/{lang} {reason[:110]}")
                continue
            queued += int(res.get("queued") or 0)
            log(f"{task}/{lang} audio queued={res.get('queued',0)} "
                f"imported={res.get('imported',0)} "
                f"mirror={res.get('classroom_playback','pending')}")
    return queued


def run():
    if not BASE.startswith("https://script.google.com/macros/s/") or not SECRET:
        raise RuntimeError("Trusted Bridge URL or reconciliation secret missing")
    with urlopen(BASE + "?action=bridge_preflight", timeout=25) as resp:
        if resp.status != 200 or b"bridge-ready" not in resp.read():
            raise RuntimeError("Bridge preflight did not pass")
    rows, lessons = state()
    log("P262 only: private signed translation + QA + audio recovery started")
    show(rows, lessons)
    idle = 0
    while time.monotonic() < DEADLINE-350:
        finished = all(x == y for x,y in totals(rows))
        if finished and all_copied(lessons):
            log("P262_COMPLETE: all four translated, QA-approved and mirrored")
            report("**COMPLETE: all selected non-English MP3s copied.**",
                   rows, lessons)
            return
        translated_this_round = 0
        quota_used = 0
        if not finished:
            for task, (have, need) in zip(TASKS, totals(rows)):
                if have == need or time.monotonic() > DEADLINE-400:
                    continue
                response = sheets("tick", task=task)
                details = response.get("result") or {}
                reason = response.get("reason") or details.get("reason") or ""
                if reason == "busy":
                    log(f"{task} Google script mutex busy")
                    time.sleep(10)
                    continue
                if not response.get("ok") or not details.get("ok"):
                    raise RuntimeError(f"{task} Sheets tick failed: {str(reason)[:100]}")
                if details.get("failed"):
                    raise RuntimeError(f"{task} translator failed: {details['failed']}")
                n = int(details.get("translated") or 0)
                quota_used = int(details.get("quota_used") or 0)
                translated_this_round += n
                log(f"{task} batch translated={n} "
                    f"requested={details.get('requests')} quota={quota_used}")
                for draft in details.get("exported_languages") or []:
                    if draft.get("complete") and draft.get("qa_new_complete"):
                        log(f"{task}/{draft['lang']}: new complete DRAFT exported")
                if quota_used >= QUOTA_MAX:
                    rows, lessons = state()
                    show(rows, lessons)
                    log("Daily quota reached; saved state, scheduled resume")
                    report("Daily translation quota reached; checkpoints saved.",
                           rows, lessons)
                    return
        rows, lessons = state()
        show(rows, lessons)
        if not finished:
            idle = idle+1 if translated_this_round == 0 else 0
            if idle >= 3:
                raise RuntimeError("Three translation rounds had zero progress")
        # Native completion immediately launches one Gemma batch.
        # This fallback drains any additional risk checks or transient failures.
        for task in TASKS:
            if time.monotonic() > DEADLINE-320:
                break
            lanes = lessons[task].get("langs", {})
            if all(x.get("formal_copied") for x in lanes.values()):
                continue
            response = sheets("qa_tick", task=task)
            if not response.get("ok"):
                log(f"::warning title=QA retry::{task} "
                    f"{str(response.get('reason') or 'pending')[:90]}")
        rows, lessons = state()
        count = push_audio(lessons)
        show(rows, lessons)
        if all(x == y for x,y in totals(rows)):
            log(f"Sheets complete; waiting for private TTS + Drive copies "
                f"(new dispatched: {count})")
            time.sleep(90)
        else:
            time.sleep(4)
    rows, lessons = state()
    show(rows, lessons)
    log("Worker time window reached; state is saved and resumable via cron")
    report("Partial progress saved. Automatic scheduled resumption enabled.",
           rows, lessons)


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        if "Bridge request failed: TimeoutError" in str(exc):
            log("::warning title=Bridge transient timeout::" +
                "Apps Script timed out; saved checkpoints retained. "
                "Scheduled retries will resume without regenerating completed MP3.")
            sys.exit(0)
        log("::error title=P262 recovery::" +
            type(exc).__name__ + ": " + str(exc)[:150])
        sys.exit(1)
