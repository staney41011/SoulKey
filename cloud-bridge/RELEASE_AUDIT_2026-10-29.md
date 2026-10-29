# SoulKey Cloud Run migration — feature parity and release audit

Audit date: 2026-10-29. Source of truth: `staney41011/SoulKey`, current Google Sheet
`全球翻譯控制中心`, the original `bridge/apps-script/Code.gs`, and
`cloud-bridge/server.js`.

## Incident evidence

- The central Sheet still contains the original P253–P259 tasks (27 course records).
- P259-L01, L02 and L03 each have a queued multi-language translation job, with
  no `claimed_at` or `finished_at`. Do **not** delete them or re-enqueue them.
- `多語翻譯結果` has its header but no verified new-architecture translation rows.
- Before redeployment, there are no `YouTube CC 任務` and `YouTube CC 成果` tabs.
- P259-L04 has its Chinese stage, but the English draft/review is unresolved.
- Older periods used the legacy GitHub/Kaggle worker route and have recorded
  actual `running`, `done` and TTS histories. The new backend is not function-complete.

## Source-code repairs committed to main

1. UI prevents re-submission of queued/running/delayed tasks and distinguishes an
   unclaimed queue from a Kaggle run. Missing Cloud Run stages are disabled.
2. Multi-language translation can upload bounded, idempotent, source-revision
   checked chunks; `done` is recorded only after all language/segment rows are
   verified in the central Google Sheet. A legacy worker path is retained.
3. CC has its own independent GitHub Actions schedule, avoiding contention with
   the 150-minute text translation worker.
4. OIDC worker authentication is bound to the exact repository, main branch,
   workflow and separate translation/CC lanes.
5. `status_health` probes actual central queue initialization and includes
   queue backlog diagnostics and a deployed build identifier.
6. Central course creation and language plan writes are restored conservatively,
   with readback and a strict no-video-replacement guard.
7. Regression test coverage exists for source validation, idempotent queue
   management, chunk completeness, OIDC isolation, task creation, and language plans.

## Remaining gaps (do not label these as restored)

| Feature | Source status | Required operational validation |
|---|---|---|
| Existing task/lesson status read | Implemented | Refresh all P253–P259 cards, same state as Sheet |
| Course creation and language settings | Source repaired | Deploy then create a disposable new lesson and save/read back |
| Chinese original ASR/polish dispatch | **Not restored** in Cloud Run | Port safe legacy GitHub/Kaggle dispatch before using on a new lesson |
| Chinese incremental draft sync to GitHub | **Not restored** | Central draft recovery and readback |
| Chinese formal Final save to central Sheet | Implemented | Save, re-open, preserve ID/timing/source |
| English draft from YouTube CC or AI | **Not completely restored** | Generate an actual matching lesson draft; do not copy another lesson |
| English formal Final & backup | Implemented | Edit, save, verify timeline, revision and source |
| Multi-language translation queue | Source repaired | Deploy, observe claim, verify all required language segments |
| YouTube CC capture | Source repaired | Deploy, verify source-bound caption text and missing languages |
| YouTube audio-track capture | **Not restored** | True original audio acquisition, source isolation and Drive storage |
| New TTS MP3 creation / synchronization | **Not restored** | Production pipeline, full-duration QA and verified Drive MP3 |
| Existing Drive transcript / TTS links | Read only | Validate file exists in each individual lesson folder |
| Automated Drive publish of Final / audio | **Not fully restored** | Google Drive owner permissions, write and readback |
| Course reorder / lesson reschedule | **Not restored** | Atomic schedule, UID and Drive folder reconciliation |
| Drive canonical filename migration | **Not restored** | Safe preview and idempotent migration |
| GitHub review cache seed/status | **Not restored** | Reconnect auth and actual write/receipt |
| Worker setup, secret tests and smoke controls | **Not restored** | Replace unsafe legacy admin controls with authenticated diagnostics |

## Release checklist — do not declare production recovered until all pass

1. From an authorized Google Cloud Shell at repository HEAD:
   `bash cloud-bridge/deploy-from-cloud-shell.sh`.
2. Verify Cloud Run public root reports the exact deployed commit SHA.
3. Reconnect existing six-digit Bridge Key; verify status health reports
   `youtube_cc_queue_enabled=true` and `translation_queue_enabled=true`.
4. Check `翻譯工作佇列` P259-L01/02/03 change from `queued` to
   `running`, then `done` **only** with actual output rows.
5. For each job, verify all five requested languages (th/es/id/vi/km),
   all source segment IDs, matching `input_revision`, and per-lesson output.
6. Verify P259-L04 receives its own English draft before English Final.
7. Validate YouTube CC on P259-L04 by checking actual YouTube-sourced text;
   only languages actually present may be shown as complete.
8. Validate both task creation and language settings by round-trip readback.
9. Validate older P258 actual MP3 Drive links remain reachable.
10. Do not activate TTS, ASR, reorder, reschedule, Drive sync or audio capture
    before their missing source handlers are restored and end-to-end tested.

**Non-negotiable:** no invented success, no deletion of prior results,
no duplicate queue claims, no implicit source-video substitution, and
no credentials or Bridge Key committed to GitHub.
