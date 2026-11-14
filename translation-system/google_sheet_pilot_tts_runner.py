#!/usr/bin/env python3
"""Approved Google Sheets translations -> official SoulKey Natural TTS.

Owner requested acceptance of Google Sheets translations as formal speech
source for P260-L01, L02 and L04, without pretending Gemma4 semantic QA passed.
Preserve all existing technically approved official audio and all translation
files. A test/audit trail records exact draft ids and English revision hashes.
"""
import argparse
import hashlib
import json
import os
import sys
import re
import subprocess
from pathlib import Path
from google_io import build_google_services, find_file, download_drive_file, upload_or_replace_file, read_values
from lesson_paths import resolve_lesson_folders
from config import SPREADSHEET_ID, TASK_SHEET_RANGE
from status_io import new_run_id, mark_running, mark_done, mark_needs_review, mark_error
from tts_runner import (LANGUAGE_NAMES, row_to_task, load_source_duration_limit,
                        render_natural_language, segments_fingerprint,
                        upload_natural_outputs, existing_natural_output,
                        verify_uploaded_natural_output, _load_tts_manifest,
                        local_audio_receipt, wav_to_mp3)
from sheets_quality_core import stable_sha
from natural_tts_planner import build_speech_blocks
from natural_tts_drive_cache import DriveTTSBlockCache

ALLOWED={"P260-L01":58,"P260-L02":36,"P260-L03":50,"P260-L04":48}
LANGS="th,es,id,vi,hi,ta,ja,ko,km,bn,ne,lo,my,it,pt"

def sha(text):
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()

def draft_source(drive, folder, task_id, language, work, english_file, english_map, expected):
    name=f"{task_id}-{language}-google-translate-DRAFT.json"
    item=find_file(drive,folder,name)
    if not item:
        raise RuntimeError("Missing Google Sheets export: "+name)
    fp=work/name
    download_drive_file(drive,item["id"],fp)
    value=json.loads(fp.read_text(encoding="utf-8"))
    if (value.get("task_id")!=task_id or value.get("language")!=language
        or value.get("engine")!="LanguageApp.translate"
        or value.get("status")!="pending_Gemma4_QA"
        or value.get("source_file_id")!=english_file):
        raise RuntimeError("Unexpected translation source or revision metadata")
    segments=value.get("segments") or []
    if len(segments)!=expected or len(english_map)!=expected:
        raise RuntimeError(f"Translation/English source count mismatch: {len(segments)}/{len(english_map)} expected {expected}")
    if {int(v["id"]) for v in segments} != set(english_map):
        raise RuntimeError("Segment ids differ from approved English final")
    for row in segments:
        en=english_map[int(row["id"])]
        if not str(row.get("text") or "").strip():
            raise RuntimeError("Empty translated segment")
        if sha(en.get("text")) != str(row.get("source_hash") or ""):
            raise RuntimeError(f"English Final changed for segment {row['id']}")
        if abs(float(row.get("start") or 0)-float(en.get("start") or 0))>0.06:
            raise RuntimeError("Changed timestamp start for "+str(row["id"]))
        if abs(float(row.get("end") or 0)-float(en.get("end") or 0))>0.06:
            raise RuntimeError("Changed timestamp end for "+str(row["id"]))
        if float(row["end"])<=float(row["start"]):
            raise RuntimeError("Malformed translation timestamp")
    return segments,item["id"]

# Preserve every spoken word: an optional minor tempo fit adjusts only
# playback duration, never the translated text or any speech block.
# More severe over-length recordings remain review-only, not formal MP3.
SHEETS_SAFE_TEMPO_MAX = 1.18
SHEETS_SAFE_TEMPO_MARGIN = 1.012


def fit_full_review_without_cutting_content(result, output_dir, source_limit):
    if result["status"] != "needs_review":
        return result
    timeline = dict(result["timeline"])
    natural = float(timeline.get("natural_duration") or 0)
    source_limit = float(source_limit)
    if natural <= source_limit or source_limit <= 0:
        return result
    required = natural / source_limit
    speed = round(required * SHEETS_SAFE_TEMPO_MARGIN, 6)
    if speed > SHEETS_SAFE_TEMPO_MAX:
        print(f"[SHEETS-FIT] needed {required:.3f}x exceeds "
              f"safe full-content limit {SHEETS_SAFE_TEMPO_MAX:.2f}x; "
              "retain preview for review", flush=True)
        return result
    output_dir = Path(output_dir)
    source_mp3 = Path(result["preview_mp3"])
    if not source_mp3.is_file() or source_mp3.stat().st_size < 1024:
        raise RuntimeError("Full spoken preview not available for safe duration fit")
    wav = output_dir / (source_mp3.stem.split(".")[0]+".wav")
    mp3 = output_dir / (source_mp3.stem.split(".")[0]+".mp3")
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source_mp3),
        "-af", f"atempo={speed:.6f}",
        "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le",
        str(wav),
    ], check=True)
    wav_to_mp3(wav, mp3)
    found = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(mp3),
    ], check=True, capture_output=True, text=True)
    encoded_duration = float(found.stdout.strip())
    if encoded_duration > source_limit - min(1.0, source_limit * 0.005):
        print(f"[SHEETS-FIT] encoded {encoded_duration:.2f}s exceeds "
              f"safe limit {source_limit-1.0:.2f}s; retain preview", flush=True)
        wav.unlink(missing_ok=True)
        mp3.unlink(missing_ok=True)
        return result
    timeline.update({
        "final_duration": round(encoded_duration, 3),
        "speech_end": round(encoded_duration, 3),
        "over_source": 0,
        "needs_review": False,
        "applied_speedup": speed,
        "required_speedup": round(required, 6),
        "duration_fit_method": "ffmpeg_atempo_full_content_pitch_preserving",
        "source_speech_retained": True,
        "encoded_mp3_duration": round(encoded_duration, 3),
    })
    manifest_path = Path(result["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "status": "done", "timeline": timeline,
        "duration_fit_revision": "sheets_safe_tempo_full_content_v1",
        "duration_fit_method": "pitch_preserving_tempo_no_text_omissions",
        "max_speedup": SHEETS_SAFE_TEMPO_MAX,
        "audio_receipts": {
            "mp3": local_audio_receipt(mp3),
            "wav": local_audio_receipt(wav),
        },
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    report_path = Path(result["alignment_report"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["timeline"] = timeline
    report["wav"] = {"duration": round(encoded_duration, 3)}
    report["mp3"] = {"duration": round(encoded_duration, 3)}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    result.update({"status": "done", "wav": wav, "mp3": mp3, "timeline": timeline})
    print(f"[SHEETS-FIT] full-content tempo={speed:.3f}x; "
          f"final={encoded_duration:.1f}s limit={source_limit:.1f}s", flush=True)
    return result


def restore_existing_review(drive, audio_folder, lang, workdir, manifest,
                            draft_id, source_fingerprint, duration_limit):
    if not manifest or manifest.get("status") != "needs_review":
        return None
    if (manifest.get("translation_source") != "Google Sheets LanguageApp.translate"
            or manifest.get("translation_source_drive_id") != draft_id
            or manifest.get("source_sha256") != source_fingerprint
            or abs(float(manifest.get("duration_limit_seconds") or 0)
                   - float(duration_limit)) > 0.5):
        return None
    audio = find_file(drive, audio_folder, f"{lang}.preview.mp3")
    report = find_file(drive, audio_folder, f"{lang}.alignment_report.json")
    if not audio or not report:
        return None
    workdir=Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    audio_file=workdir/f"{lang}.preview.mp3"
    report_file=workdir/f"{lang}.alignment_report.json"
    manifest_file=workdir/f"{lang}.tts_manifest.json"
    download_drive_file(drive, audio["id"], audio_file)
    receipt=(manifest.get("audio_receipts") or {}).get("preview_mp3") or {}
    if receipt.get("size") != audio_file.stat().st_size or (
       receipt.get("md5") != local_audio_receipt(audio_file)["md5"]):
        raise RuntimeError("Prior review MP3 MD5 or size mismatch: refusing to publish")
    download_drive_file(drive, report["id"], report_file)
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return {
        "status":"needs_review",
        "preview_mp3":audio_file,
        "wav":workdir/f"{lang}.wav",
        "mp3":workdir/f"{lang}.mp3",
        "manifest":manifest_file,
        "alignment_report":report_file,
        "timeline":manifest["timeline"],
    }


def select_quality_approved_source(drive,translation_folder,lang,work,
                                   english_id,draft_id,draft):
    "Use corrected text only from a current, revision-matched QA result."
    report_item=find_file(drive,translation_folder,f"sheets.qa.{lang}.json")
    approved_item=find_file(drive,translation_folder,f"sheets.qa.approved.{lang}.json")
    if not report_item or not approved_item:
        return draft,None
    report_path=Path(work)/f"sheets.qa.{lang}.json"
    approved_path=Path(work)/f"sheets.qa.approved.{lang}.json"
    download_drive_file(drive,report_item["id"],report_path)
    download_drive_file(drive,approved_item["id"],approved_path)
    report=json.loads(report_path.read_text(encoding="utf-8"))
    approved=json.loads(approved_path.read_text(encoding="utf-8"))
    if (report.get("state")!="approved_risk_based"
        or approved.get("status")!="approved_risk_based"
        or report.get("review_scope")!="all_segments_structural_plus_risk_based_gemma4_sample"
        or approved.get("revision_key")!=report.get("revision_key")
        or report.get("draft_sha")!=stable_sha(draft)
        or approved.get("source_file_id")!=english_id
        or approved.get("draft_file_id")!=draft_id):
        print(f"[SHEETS-QA] {lang}: outdated or incomplete audit; "
              "retaining original draft for preliminary TTS",flush=True)
        return draft,None
    revised=approved.get("segments") or []
    original={int(x["id"]):x for x in draft}
    if len(revised)!=len(draft) or {int(x["id"]) for x in revised}!=set(original):
        raise RuntimeError("Quality-corrected translation has mismatched segments")
    for seg in revised:
        before=original[int(seg["id"])]
        if (seg.get("source_hash")!=before.get("source_hash")
           or abs(float(seg["start"])-float(before["start"]))>.06
           or abs(float(seg["end"])-float(before["end"]))>.06
           or not str(seg.get("text") or "").strip()):
            raise RuntimeError("Quality correction changed English origin/timeline")
    if approved.get("source_sha256")!=segments_fingerprint(revised):
        raise RuntimeError("Quality-corrected revision fingerprint is invalid")
    print(f"[SHEETS-QA] {lang}: approved risk-based revision selected; "
          f"corrected={len(approved.get('corrected_ids') or [])}",flush=True)
    return revised,report.get("revision_key")


def recover_duration_from_english_cc(drive, source_folder, work, video_url):
    """Fallback when early source metadata download was blocked by YouTube.

    Use the actual caption track belonging to this lesson, not an arbitrary
    duration or a previously downloaded track. Keep the official source
    unchanged; return a conservative floor of the last timestamp.
    """
    from urllib.parse import urlparse, parse_qs
    url = str(video_url or "").strip()
    parsed = urlparse(url)
    video_id = ""
    if parsed.netloc.lower().endswith("youtu.be"):
        video_id = parsed.path.strip("/").split("/")[0]
    elif parsed.netloc.lower().endswith("youtube.com"):
        video_id = (parse_qs(parsed.query).get("v") or [""])[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return None
    item = find_file(drive, source_folder, "youtube.en.json")
    if not item:
        return None
    path = Path(work) / "youtube.en.duration-source.json"
    download_drive_file(drive, item["id"], path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if str(payload.get("video_id") or "") != video_id:
        raise RuntimeError("English CC video ID does not match current lesson")
    if not str(payload.get("language") or "").lower().startswith("en"):
        raise RuntimeError("Not a verified English YouTube caption track")
    cues = payload.get("segments") or []
    if not isinstance(cues, list) or len(cues) < 30:
        raise RuntimeError("English CC has insufficient timestamp evidence")
    starts, ends = [], []
    for cue in cues:
        start = float(cue.get("start", -1))
        end = float(cue.get("end", -1))
        if not (0 <= start < end <= 10800):
            raise RuntimeError("English CC has invalid duration intervals")
        starts.append(start)
        ends.append(end)
    if min(starts) > 60 or max(ends) < 300:
        raise RuntimeError("English CC does not cover enough of the lecture")
    duration = int(max(ends))
    print(f"[SHEETS-FORMAL] Original metadata unavailable; verified English CC "
          f"video={video_id} end={duration}s", flush=True)
    return float(duration)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--task-id",required=True)
    ap.add_argument("--langs",required=True)
    a=ap.parse_args()
    task_id=a.task_id
    task_match=re.fullmatch(r"P(\d+)-L(\d+)",task_id)
    if not task_match or int(task_match.group(1))<260:
        ap.error("Only centrally registered P260+ lessons use Sheets-first TTS")
    langs=list(dict.fromkeys(x.strip() for x in a.langs.split(",") if x.strip()))
    if not langs or len(langs)>15 or any(x not in LANGS.split(",") for x in langs):
        ap.error("Selection must be subset of 15 supported Google Sheets translations")
    drive,sheets=build_google_services()
    matching=[row_to_task(raw,i) for i,raw in enumerate(
        read_values(sheets,SPREADSHEET_ID,TASK_SHEET_RANGE),start=2)
        if raw and str(raw[0] or "")==task_id]
    if len(matching)!=1:
        raise RuntimeError("Task is not uniquely registered")
    task=matching[0]
    folders=resolve_lesson_folders(drive,sheets,task["period"],task["lesson"])
    english=find_file(drive,folders["translation"],"en.final.json")
    if not english:
        raise RuntimeError("Approved English Final is missing")
    draft_folder=find_file(drive,folders["translation"],"AppsScript初譯-待QA")
    if not draft_folder or draft_folder.get("mimeType")!="application/vnd.google-apps.folder":
        raise RuntimeError("Google Sheets export folder missing")
    work=Path(os.environ.get("SOULKEY_TTS_WORKDIR","/tmp/soulkey-tts"))/(task_id+"-SHEET-FORMAL")
    work.mkdir(parents=True,exist_ok=True)
    english_file=work/"en.final.json"
    download_drive_file(drive,english["id"],english_file)
    english_payload=json.loads(english_file.read_text(encoding="utf-8"))
    english_segments=english_payload.get("segments") or []
    english_map={int(x["id"]):x for x in english_segments}
    if not english_map or (
            task_id in ALLOWED and len(english_map)!=ALLOWED[task_id]):
        raise RuntimeError("Current English final has incorrect segment count")
    expected_segments=len(english_map)
    video_duration,basis=load_source_duration_limit(
        drive,folders["source"],work,youtube_url=task.get("youtube_url"))
    if not video_duration:
        raise RuntimeError(
            "Missing independently verified original YouTube video duration; "
            "do not replace it with an English CC last timestamp. "
            "Re-ingest source_info.json or add a verified video-ID record.")
    from source_integrity import check_english_coverage, compare_manuscript_to_video
    coverage=check_english_coverage(english_segments,video_duration)
    print("[SOURCE-INTEGRITY] %s video=%.1fs English end=%.1fs coverage=%.1f%%" %
          (task_id,video_duration,coverage["english_end"],
           coverage["coverage_ratio"]*100),flush=True)
    # Chinese and English are independently compared with the original video,
    # not with each other's final subtitle cue. Preserve approved manuscripts.
    zh_item=find_file(drive,folders["transcript"],"zh-TW.final.json")
    if zh_item:
        try:
            zh_path=work/"zh-TW.source-integrity.json"
            download_drive_file(drive,zh_item["id"],zh_path)
            zh_payload=json.loads(zh_path.read_text(encoding="utf-8"))
            audit=compare_manuscript_to_video(
                zh_payload.get("segments") or [],video_duration)
            if audit["needs_review"]:
                msg=("中文逐字稿時間碼須依原始影片校正；影片原長 %.1fs、"
                     "中文字稿結尾 %.1fs、超出 %.1fs（%s）。"
                     "保留人工定稿不刪字；英文錨定的多語配音照影片原長執行。" %
                     (video_duration,audit["manuscript_end"],
                      audit["overrun_seconds"],audit["reason"]))
                print("[SOURCE-INTEGRITY] "+msg,flush=True)
                mark_needs_review(task_id,"source_integrity",sheets=sheets,
                                  run_id=new_run_id(task_id,"source_integrity"),
                                  message=msg)
        except Exception as exc:
            print("[SOURCE-INTEGRITY] Chinese audit unavailable: "+
                  type(exc).__name__+": "+str(exc)[:180],flush=True)
    print("[SHEETS-FORMAL] task=%s langs=%s original_video_limit=%.2fs basis=%s" %
          (task_id,",".join(langs),video_duration,basis),flush=True)
    audio_folder=folders["audio"]
    print("[SHEETS-FORMAL] task=%s langs=%s original_limit=%.2fs"%
          (task_id,",".join(langs),video_duration),flush=True)
    results=[]
    for lang in langs:
        run_id=new_run_id(task_id,"tts:"+lang)
        try:
            segments,draft_id=draft_source(
                drive,draft_folder["id"],task_id,lang,work,english["id"],
                english_map,expected_segments)
            segments,quality_key=select_quality_approved_source(
                drive,folders["translation"],lang,work,english["id"],
                draft_id,segments)
            fingerprint=segments_fingerprint(segments)
            per_language_work=work/lang
            per_language_work.mkdir(parents=True,exist_ok=True)
            # IMPORTANT: preserve any already-passed production audio even if
            # it came from another translated text revision/provider.
            old=_load_tts_manifest(drive,audio_folder,lang,per_language_work)
            if old and old.get("status")=="done" and (
                    str(old.get("source_sha256") or "")==fingerprint):
                official_state=verify_uploaded_natural_output(
                    drive,audio_folder,lang,fingerprint,
                    video_duration,per_language_work)
                if official_state=="done":
                    print("[SHEETS-FORMAL] %s existing approved audio retained"%lang,flush=True)
                    results.append({"lang":lang,"state":"existing_formal_preserved"})
                    continue
            mark_running(task_id,"tts:"+lang,sheets=sheets,run_id=run_id,
                         message="Google Sheets approved source -> formal Natural TTS generating")
            result=restore_existing_review(
                drive, audio_folder, lang, per_language_work, old,
                draft_id, fingerprint, video_duration)
            if result is None:
                # Changed QA sentence invalidates only the affected speech
                # blocks. Verified unchanged MP3 blocks are restored from
                # Drive's cache before the replacement recording is assembled.
                blocks,_=build_speech_blocks(segments,lang)
                block_store=DriveTTSBlockCache(
                    drive,audio_folder,lang,fingerprint,blocks,
                    per_language_work/"drive-block-cache")
                result=render_natural_language(
                    segments,lang,per_language_work,
                    source_duration=video_duration,duration_limit_basis=basis,
                    checkpoint_store=block_store,
                    smart_fit_pilot=False,
                )
            result=fit_full_review_without_cutting_content(
                result, per_language_work, video_duration)
            manifest_path=Path(result["manifest"])
            manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["translation_source"]=(
                "Google Sheets + Gemma4 reviewed correction"
                if quality_key else "Google Sheets LanguageApp.translate")
            manifest["sheets_qa_revision_key"]=quality_key or ""
            manifest["sheets_qa_review_scope"]=(
                "risk_based_not_full_semantic_review" if quality_key
                else "not_yet_reviewed")
            manifest["translation_source_drive_id"]=draft_id
            manifest["english_final_drive_id"]=english["id"]
            manifest["english_final_segments_sha256"]=segments_fingerprint(english_segments)
            manifest["translation_semantic_qa"]=(
                "passed_risk_based_not_full" if quality_key
                else "not_passed_through_Gemma4")
            manifest["formal_audio_source_authorization"]="user_requested_2026-11-05"
            manifest["note"]="Official audio only when technical timing and Drive binary validation pass. Translation source: Google Sheets unreviewed draft."
            manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
            # Only normal official audio folder. Over-length stays clearly
            # needs_review as *.preview.mp3, not a published *.mp3.
            upload_natural_outputs(drive,audio_folder,result,task)
            verified=verify_uploaded_natural_output(
                drive,audio_folder,lang,fingerprint,video_duration,per_language_work)
            if verified != result["status"]:
                raise RuntimeError("Drive binary/timing validation mismatch: "+verified)
            timeline=result["timeline"]
            if verified=="done":
                mark_done(task_id,"tts:"+lang,sheets=sheets,run_id=run_id,
                    message=("Google Sheets 來源正式音檔完成（未做 Gemma4 文字QA）；"
                             f"時長={timeline.get('final_duration',0):.1f}s；"
                             f"影片上限={video_duration:.1f}s；"
                             f"語速={timeline.get('applied_speedup',1):.3f}x"))
            else:
                mark_needs_review(task_id,"tts:"+lang,sheets=sheets,run_id=run_id,
                    message="Google Sheets來源試聽音檔已生成，因超過影片時長仍未驗收為正式 MP3")
            results.append({
                "lang":lang,"state":verified,"source":"GoogleSheets",
                "draft_id":draft_id,
                "duration_seconds":round(float(timeline.get("final_duration") or 0),1),
                "required_speedup":float(timeline.get("required_speedup") or 1)
            })
            print("[SHEETS-FORMAL] %s=%s"% (lang,verified),flush=True)
        except Exception as exc:
            print("[SHEETS-FORMAL] %s failed %s: %s"%(
                lang,type(exc).__name__,str(exc)[:200]),file=sys.stderr,flush=True)
            try: mark_error(task_id,"tts:"+lang,sheets=sheets,run_id=run_id,exc=exc)
            except Exception: pass
            results.append({"lang":lang,"state":"error","error":str(exc)[:260]})
    status_path=work/("GoogleSheets正式音檔來源紀錄-"+task_id+".json")
    status_path.write_text(json.dumps({
        "task_id":task_id,"formal_audio":True,
        "translation_source":"Google Sheets LanguageApp.translate",
        "translation_semantic_QA":"Gemma4 QA not done for these sourced texts",
        "provenance":"English source segment SHA256 verified against current approved English Final",
        "results":results
    },ensure_ascii=False,indent=2),encoding="utf-8")
    upload_or_replace_file(drive,audio_folder,status_path,status_path.name)
    print("[SHEETS-FORMAL] results "+json.dumps(results,ensure_ascii=False),flush=True)
    # Publish gate must be recalculated after corrected speech is uploaded.
    try:
        from sheets_quality_runner import release_gate
        from sheets_quality_core import LANG_CODES
        gate=release_gate(drive,folders,task_id,list(LANG_CODES),work,sheets=sheets)
        print("[SHEETS-FORMAL] release_gate="+
              ("ready" if gate["can_release"] else "blocked"),flush=True)
    except Exception as exc:
        print("[SHEETS-FORMAL] QA release gate refresh deferred: "+
              f"{type(exc).__name__}: {str(exc)[:160]}",flush=True)
    # A batch is not "done" when even one requested language still
    # needs a timing revision or failed delivery; keep the others committed.
    states=[x["state"] for x in results]
    if all(x=="error" for x in states):
        return 2
    if any(x in ("needs_review","error") for x in states):
        return 3
    return 0

if __name__=="__main__":
    raise SystemExit(main())
