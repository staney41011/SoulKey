const OWNER = "staney41011";
const REPO = "SoulKey";
const REF = "main";

const WORKFLOW = "kaggle_run_bridge_test.yml";
const WORKFLOW_WEB_WORKER_SETUP = "kaggle_web_worker_setup.yml";
const WORKFLOW_WEB_WORKER_SECRET_TEST = "kaggle_web_worker_secret_test.yml";
const WORKFLOW_WEB_JOB = "kaggle_web_job.yml";

const CONTROL_SHEET_ID = "1AwPqTqZSzW7Q-gLW4J5d-28dQZwVksyDnvsxNRF2uu8";
const ROOT_DRIVE_FOLDER_ID = "1lw-B6c4zZFVMDr01iMOQR2ijH4oEXrTO";

const TASK_SHEET_NAME = "任務佇列";
const PERIOD_SHEET_NAME = "期數設定";
const STATUS_SHEET_NAME = "執行狀態";
const LANGUAGE_SHEET_NAME = "語言設定";
const LANGUAGE_PLAN_SHEET_NAME = "語言任務設定";

const TASK_BASE_COLUMNS = 20;
const TASK_TOTAL_COLUMNS = 26;
const TASK_COL = {
  course_uid: 20,
  schedule_status: 21,
  original_period: 22,
  original_lesson: 23,
  rescheduled_at: 24,
  schedule_note: 25
};

const MACHINE_STAGES = [
  "zh", "metadata", "asr", "polish", "vernacular", "en", "multi", "tts", "finish", "cc", "batch"
];
const RUNTIME_TTL_MS = 8 * 60 * 60 * 1000;
const BRIDGE_PROTOCOL_VERSION = 9;

function doGet(e) {
  const view = String((e && e.parameter && e.parameter.view) || "").trim();
  if (view === "client") return bridgeClientHtml_();

  const action = String((e && e.parameter && e.parameter.action) || "").trim();

  if (action === "worker_runtime") {
    const nonce = String((e && e.parameter && e.parameter.nonce) || "").trim();
    return json_(workerRuntime_(nonce));
  }

  const callback = String((e && e.parameter && e.parameter.callback) || "").trim();
  const jsonpActions = [
    "status_health",
    "status",
    "status_batch",
    "language_settings",
    "language_plan_get",
    "tasks_get",
    "review_load",
    "youtube_capture_files",
    "course_files"
  ];

  if (callback && jsonpActions.indexOf(action) >= 0) {
    const request = {
      action: action,
      bridge_key: String((e && e.parameter && e.parameter.bridge_key) || "").trim(),
      task_id: String((e && e.parameter && e.parameter.task_id) || "").trim(),
      task_ids: String((e && e.parameter && e.parameter.task_ids) || "").trim(),
      kind: String((e && e.parameter && e.parameter.kind) || "").trim(),
      chunk_index: String((e && e.parameter && e.parameter.chunk_index) || "0").trim()
    };
    return jsonp_(callback, bridgeRequest(request));
  }

  return json_({
    ok: true,
    service: "SoulKey Studio Bridge",
    message: "bridge-ready",
    status_sheet: STATUS_SHEET_NAME,
    web_job_workflow: WORKFLOW_WEB_JOB,
    bridge_protocol: BRIDGE_PROTOCOL_VERSION
  });
}

function doPost(e) {
  try {
    const action = String((e && e.parameter && e.parameter.action) || "").trim();

    if (action === "worker_report") {
      const nonce = String((e && e.parameter && e.parameter.nonce) || "").trim();
      const status = String((e && e.parameter && e.parameter.status) || "").trim();
      const message = String((e && e.parameter && e.parameter.message) || "").trim();
      return json_(workerReport_(nonce, status, message));
    }

    if (action === "worker_review_publish") {
      const nonce = String((e && e.parameter && e.parameter.nonce) || "").trim();
      const taskId = String((e && e.parameter && e.parameter.task_id) || "").trim();
      const contentB64 = String((e && e.parameter && e.parameter.content_b64) || "").trim();
      return json_(workerReviewPublish_(nonce, taskId, contentB64));
    }

    if (action === "worker_english_cache_seed") {
      const nonce = String((e && e.parameter && e.parameter.nonce) || "").trim();
      const taskId = String((e && e.parameter && e.parameter.task_id) || "").trim();
      return json_(workerEnglishCacheSeed_(nonce, taskId));
    }

    if (action === "worker_translation_checkpoint_publish") {
      const nonce = String((e && e.parameter && e.parameter.nonce) || "").trim();
      const taskId = String((e && e.parameter && e.parameter.task_id) || "").trim();
      const contentB64 = String((e && e.parameter && e.parameter.content_b64) || "").trim();
      return json_(workerTranslationCheckpointPublish_(nonce, taskId, contentB64));
    }

    const props = PropertiesService.getScriptProperties();
    const expectedKey = String(props.getProperty("BRIDGE_KEY") || "").trim();
    const githubToken = String(props.getProperty("GITHUB_TOKEN") || "").trim();

    const bridgeKey = String((e && e.parameter && e.parameter.bridge_key) || "").trim();

    if (!expectedKey) {
      return responseForAction_(action, {
        ok: false,
        error: "server_not_configured",
        message: "BRIDGE_KEY 尚未設定"
      });
    }

    if (!bridgeKey || bridgeKey !== expectedKey) {
      return responseForAction_(action, {
        ok: false,
        error: "unauthorized",
        message: "Bridge Key 不正確"
      });
    }

    if (action === "review_share_draft_save") {
      const taskId = String((e && e.parameter && e.parameter.task_id) || "").trim();
      const payloadJson = String((e && e.parameter && e.parameter.payload_json) || "").trim();
      return postMessage_(reviewShareDraftSave_(taskId, payloadJson));
    }

    if (action === "review_en_draft_save") {
      const taskId = String((e && e.parameter && e.parameter.task_id) || "").trim();
      const payloadJson = String((e && e.parameter && e.parameter.payload_json) || "").trim();
      return postMessage_(reviewEnglishDraftSave_(taskId, payloadJson));
    }

    if (action === "review_share_finalize") {
      const taskId = String((e && e.parameter && e.parameter.task_id) || "").trim();
      const segmentsJson = String((e && e.parameter && e.parameter.segments_json) || "").trim();
      const payloadJson = String((e && e.parameter && e.parameter.payload_json) || "").trim();
      return postMessage_(
        reviewShareFinalize_(taskId, segmentsJson, payloadJson)
      );
    }

    if (action === "review_share_finalize_en") {
      const taskId = String((e && e.parameter && e.parameter.task_id) || "").trim();
      const segmentsJson = String((e && e.parameter && e.parameter.segments_json) || "").trim();
      const payloadJson = String((e && e.parameter && e.parameter.payload_json) || "").trim();
      return postMessage_(
        reviewShareFinalizeEnglish_(taskId, segmentsJson, payloadJson)
      );
    }

    if (action === "review_finish") {
      const taskId = String((e && e.parameter && e.parameter.task_id) || "").trim();
      const planJson = String((e && e.parameter && e.parameter.plan_json) || "").trim();
      return postMessage_(reviewFinish_(taskId, planJson));
    }

    if (action === "smoke") {
      if (!githubToken) {
        return json_({
          ok: false,
          error: "server_not_configured",
          message: "GITHUB_TOKEN 尚未設定"
        });
      }
      return dispatchSmoke_(githubToken);
    }

    if (action === "worker_setup") {
      return postMessage_(
        workflowDispatchResponse_(githubToken, WORKFLOW_WEB_WORKER_SETUP, {}, "worker_setup")
      );
    }

    if (action === "worker_secret_test") {
      return postMessage_(
        workflowDispatchResponse_(githubToken, WORKFLOW_WEB_WORKER_SECRET_TEST, {}, "worker_secret_test")
      );
    }

    if (action === "run_stage") {
      const taskId = String((e && e.parameter && e.parameter.task_id) || "").trim();
      const stage = String((e && e.parameter && e.parameter.stage) || "").trim();
      const lang = String((e && e.parameter && e.parameter.lang) || "").trim();
      const langs = String((e && e.parameter && e.parameter.langs) || "").trim();

      if (!taskId || MACHINE_STAGES.indexOf(stage) < 0) {
        return postMessage_({
          source: "soulkey-bridge",
          type: "run_stage",
          ok: false,
          error: "invalid_job",
          message: "task_id 或 stage 不正確"
        });
      }

      if (!readTasks_().some(function(item) { return item.id === taskId; })) {
        return postMessage_({
          source: "soulkey-bridge",
          type: "run_stage",
          ok: false,
          error: "task_not_registered",
          message: "此課程尚未成功建立在 Google Sheets 中央任務佇列。請先重新儲存課程，確認同步後再執行。"
        });
      }

      if (!githubToken) {
        return postMessage_({
          source: "soulkey-bridge",
          type: "run_stage",
          ok: false,
          error: "server_not_configured",
          message: "GITHUB_TOKEN 尚未設定"
        });
      }

      const nonce = createRuntimeJob_(taskId, stage, lang, langs);
      const bridgeUrl = ScriptApp.getService().getUrl();
      const dispatch = dispatchWorkflow_(
        githubToken,
        WORKFLOW_WEB_JOB,
        {
          task_id: taskId,
          stage: stage,
          lang: lang,
          langs: langs,
          runtime_nonce: nonce,
          bridge_url: bridgeUrl
        }
      );

      if (!dispatch.ok) {
        PropertiesService.getScriptProperties().deleteProperty("JOB_" + nonce);
        return postMessage_({
          source: "soulkey-bridge",
          type: "run_stage",
          ok: false,
          error: dispatch.error || "dispatch_failed",
          message: "GitHub Actions 工作送出失敗",
          github_status: dispatch.github_status || null
        });
      }

      appendExecutionStatus_(
        taskId,
        stage,
        "queued",
        String(dispatch.workflow_run_id || nonce.slice(0, 12)),
        0,
        "已送出 GitHub Actions，等待 Kaggle",
        "",
        "",
        "",
        "",
        "",
        ""
      );

      return postMessage_({
        source: "soulkey-bridge",
        type: "run_stage",
        ok: true,
        task_id: taskId,
        stage: stage,
        workflow_run_id: dispatch.workflow_run_id || null,
        html_url: dispatch.html_url || null,
        message: "已送出 Kaggle Web Job"
      });
    }

    if (action === "review_cache_seed") {
      const taskId = String((e && e.parameter && e.parameter.task_id) || "").trim();
      const result = seedReviewCache_(taskId, githubToken);
      result.source = "soulkey-bridge";
      result.type = "review_cache_seeded";
      return postMessage_(result);
    }

    if (action === "review_cache_seed_en") {
      const taskId = String((e && e.parameter && e.parameter.task_id) || "").trim();
      const result = seedEnglishReviewCache_(taskId);
      result.source = "soulkey-bridge";
      result.type = "english_cache_seeded";
      return postMessage_(result);
    }

    if (action === "tasks_upsert") {
      const raw = String((e && e.parameter && e.parameter.tasks_json) || "").trim();
      let items = [];
      try {
        items = JSON.parse(raw);
      } catch (_) {
        return postMessage_({
          source: "soulkey-bridge",
          type: "tasks_saved",
          ok: false,
          error: "invalid_tasks_json"
        });
      }

      const saved = upsertTasks_(items);
      return postMessage_({
        source: "soulkey-bridge",
        type: "tasks_saved",
        ok: true,
        tasks: saved
      });
    }

    if (action === "review_save") {
      const taskId = String((e && e.parameter && e.parameter.task_id) || "").trim();
      const kind = String((e && e.parameter && e.parameter.kind) || "").trim();
      const segmentsJson = String((e && e.parameter && e.parameter.segments_json) || "").trim();
      const termsJson = String((e && e.parameter && e.parameter.terms_json) || "[]").trim();

      let segments = [];
      let learnedTerms = [];
      try {
        segments = JSON.parse(segmentsJson);
        learnedTerms = JSON.parse(termsJson);
      } catch (_) {
        return postMessage_({
          source: "soulkey-bridge",
          type: "review_saved",
          ok: false,
          error: "invalid_review_json"
        });
      }

      const result = saveReview_(taskId, kind, segments, learnedTerms);
      result.source = "soulkey-bridge";
      result.type = "review_saved";
      return postMessage_(result);
    }

    if (action === "language_plan_save") {
      const taskId = String((e && e.parameter && e.parameter.task_id) || "").trim();
      const planJson = String((e && e.parameter && e.parameter.plan_json) || "").trim();

      let plan = [];
      try {
        plan = JSON.parse(planJson);
      } catch (_) {
        return postMessage_({
          source: "soulkey-bridge",
          type: "language_plan_saved",
          ok: false,
          error: "invalid_plan_json"
        });
      }

      const planChanges = saveLanguagePlan_(taskId, plan);
      return postMessage_({
        source: "soulkey-bridge",
        type: "language_plan_saved",
        ok: true,
        task_id: taskId,
        plan: readLanguagePlan_(taskId),
        translation_changed: !!planChanges.translation_changed,
        audio_changed: !!planChanges.audio_changed,
        server_time: new Date().toISOString()
      });
    }

    if (action === "period_reorder") {
      const period = Number((e && e.parameter && e.parameter.period) || 0);
      const rawOrder = String((e && e.parameter && e.parameter.ordered_task_ids) || "").trim();
      const orderedTaskIds = rawOrder.split(",").map(function(x) {
        return String(x || "").trim();
      }).filter(Boolean);
      const result = reorderPeriodTasks_(period, orderedTaskIds);
      result.source = "soulkey-bridge";
      result.type = "period_reordered";
      return postMessage_(result);
    }

    if (action === "task_reschedule") {
      const taskId = String((e && e.parameter && e.parameter.task_id) || "").trim();
      const newPeriod = Number((e && e.parameter && e.parameter.new_period) || 0);
      const newLesson = Number(
        String((e && e.parameter && e.parameter.new_lesson) || "")
          .replace(/[^0-9]/g, "")
      );
      const result = rescheduleTask_(taskId, newPeriod, newLesson);
      result.source = "soulkey-bridge";
      result.type = "task_rescheduled";
      return postMessage_(result);
    }

    if (action === "drive_names_migrate") {
      const taskId = String((e && e.parameter && e.parameter.task_id) || "").trim();
      const result = migrateFormalDriveNames_(taskId);
      result.source = "soulkey-bridge";
      result.type = "drive_names_migrated";
      return postMessage_(result);
    }

    if (action === "status_health") {
      const sheet = getStatusSheet_();
      return postMessage_({
        source: "soulkey-bridge",
        type: "status_health",
        ok: true,
        sheet: STATUS_SHEET_NAME,
        rows: Math.max(0, sheet.getLastRow() - 1),
        youtube_cookies_configured: !!props.getProperty("YOUTUBE_COOKIES_B64"),
        bridge_protocol: BRIDGE_PROTOCOL_VERSION,
        server_time: new Date().toISOString()
      });
    }

    if (action === "language_settings") {
      return postMessage_({
        source: "soulkey-bridge",
        type: "language_settings",
        ok: true,
        languages: readLanguageSettings_(),
        server_time: new Date().toISOString()
      });
    }

    if (action === "language_plan_get") {
      const taskId = String((e && e.parameter && e.parameter.task_id) || "").trim();
      return postMessage_({
        source: "soulkey-bridge",
        type: "language_plan",
        ok: !!taskId,
        task_id: taskId,
        plan: taskId ? readLanguagePlan_(taskId) : []
      });
    }

    if (action === "status" || action === "status_batch") {
      const raw = String(
        (e && e.parameter && (e.parameter.task_ids || e.parameter.task_id)) || ""
      ).trim();
      const taskIds = raw.split(",").map(function(x) { return x.trim(); }).filter(Boolean).slice(0, 20);

      return postMessage_({
        source: "soulkey-bridge",
        type: "status_result",
        ok: !!taskIds.length,
        tasks: taskIds.length ? readLatestStatuses_(taskIds) : {},
        server_time: new Date().toISOString()
      });
    }

    return responseForAction_(action, {
      ok: false,
      error: "unsupported_action",
      message: "不支援的 action: " + action
    });

  } catch (err) {
    return responseForAction_(
      String((e && e.parameter && e.parameter.action) || ""),
      {
        ok: false,
        error: "bridge_exception",
        message: String(err && err.message ? err.message : err)
      }
    );
  }
}

function bridgeRequest(request) {
  try {
    request = request || {};

    const props = PropertiesService.getScriptProperties();
    const expectedKey = String(props.getProperty("BRIDGE_KEY") || "").trim();
    const bridgeKey = String(request.bridge_key || "").trim();
    const action = String(request.action || "").trim();

    if (!expectedKey || !bridgeKey || bridgeKey !== expectedKey) {
      return {
        source: "soulkey-bridge",
        type: action === "status_health" ? "status_health" : "bridge_error",
        ok: false,
        error: "unauthorized",
        message: "Bridge Key 不正確"
      };
    }

    if (action === "status_health") {
      const sheet = getStatusSheet_();
      return {
        source: "soulkey-bridge",
        type: "status_health",
        ok: true,
        sheet: STATUS_SHEET_NAME,
        rows: Math.max(0, sheet.getLastRow() - 1),
        youtube_cookies_configured: !!props.getProperty("YOUTUBE_COOKIES_B64"),
        bridge_protocol: BRIDGE_PROTOCOL_VERSION,
        server_time: new Date().toISOString()
      };
    }

    if (action === "status" || action === "status_batch") {
      const raw = String(request.task_ids || request.task_id || "").trim();
      const taskIds = raw.split(",").map(function(x) { return x.trim(); }).filter(Boolean).slice(0, 20);
      return {
        source: "soulkey-bridge",
        type: "status_result",
        ok: !!taskIds.length,
        tasks: taskIds.length ? readLatestStatuses_(taskIds) : {},
        server_time: new Date().toISOString()
      };
    }

    if (action === "tasks_get") {
      return {
        source: "soulkey-bridge",
        type: "tasks_result",
        ok: true,
        tasks: readTasks_(),
        server_time: new Date().toISOString()
      };
    }

    if (action === "language_settings") {
      return {
        source: "soulkey-bridge",
        type: "language_settings",
        ok: true,
        languages: readLanguageSettings_(),
        server_time: new Date().toISOString()
      };
    }

    if (action === "language_plan_get") {
      const taskId = String(request.task_id || "").trim();
      return {
        source: "soulkey-bridge",
        type: "language_plan",
        ok: !!taskId,
        task_id: taskId,
        plan: taskId ? readLanguagePlan_(taskId) : []
      };
    }

    if (action === "youtube_capture_files") {
      const taskId = String(request.task_id || "").trim();
      const payload = youtubeCaptureFiles_(taskId);
      payload.source = "soulkey-bridge";
      payload.type = "youtube_capture_files";
      return payload;
    }

    if (action === "course_files") {
      const taskId = String(request.task_id || "").trim();
      const payload = courseFilesOverview_(taskId);
      payload.source = "soulkey-bridge";
      payload.type = "course_files";
      return payload;
    }

    if (action === "review_load") {
      const taskId = String(request.task_id || "").trim();
      const kind = String(request.kind || "").trim();
      const chunkIndex = Math.max(0, Number(request.chunk_index || 0) || 0);
      const payload = loadReview_(taskId, kind, chunkIndex);
      payload.source = "soulkey-bridge";
      payload.type = "review_data";
      return payload;
    }

    return {
      source: "soulkey-bridge",
      type: "bridge_error",
      ok: false,
      error: "unsupported_action",
      message: "不支援的 action: " + action
    };

  } catch (err) {
    return {
      source: "soulkey-bridge",
      type: "bridge_error",
      ok: false,
      error: "bridge_exception",
      message: String(err && err.message ? err.message : err)
    };
  }
}

function authorizeSoulKeyBridge() {
  const ss = SpreadsheetApp.openById(CONTROL_SHEET_ID);
  const root = DriveApp.getFolderById(ROOT_DRIVE_FOLDER_ID);

  // 主動呼叫 UrlFetchApp，讓 Apps Script 在更換 GCP Project 後
  // 一次要求 script.external_request 權限；正式 Bridge 觸發 GitHub Actions 會用到。
  const probe = UrlFetchApp.fetch("https://api.github.com/zen", {
    method: "get",
    muteHttpExceptions: true,
    headers: {
      Accept: "application/vnd.github+json"
    }
  });

  const token = ScriptApp.getOAuthToken();

  Logger.log("Spreadsheet: " + ss.getName());
  Logger.log("Drive root: " + root.getName());
  Logger.log("External request status: " + probe.getResponseCode());
  Logger.log("OAuth token available: " + (!!token));
}

function cleanupSoulKeyExpiredProperties() {
  const props = PropertiesService.getScriptProperties();
  const all = props.getProperties();
  const now = Date.now();
  const keysToDelete = [];

  Object.keys(all).forEach(function(key) {
    if (key.indexOf("JOB_") !== 0) return;

    let payload = null;
    try {
      payload = JSON.parse(String(all[key] || ""));
    } catch (_) {
      keysToDelete.push(key);
      return;
    }

    const expiresAt = payload && payload.expires_at
      ? new Date(payload.expires_at).getTime()
      : NaN;

    if (!isFinite(expiresAt) || expiresAt < now) {
      keysToDelete.push(key);
    }
  });

  if (keysToDelete.length) {
    keysToDelete.forEach(function(key) {
      props.deleteProperty(key);
    });
  }

  Logger.log(
    "SoulKey runtime cleanup: deleted=" +
    keysToDelete.length +
    ", remaining=" +
    Object.keys(props.getProperties()).length
  );

  return {
    deleted: keysToDelete.length,
    remaining: Object.keys(props.getProperties()).length
  };
}

function createRuntimeJob_(taskId, stage, lang, langs) {
  // Keep Script Properties from filling up with expired one-time runtime jobs.
  cleanupSoulKeyExpiredProperties();

  const bytes = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    Utilities.getUuid() + "|" + Utilities.getUuid() + "|" + new Date().getTime()
  );
  const nonce = "job_" + Utilities.base64EncodeWebSafe(bytes).replace(/=+$/g, "");

  const payload = {
    task_id: taskId,
    stage: stage,
    lang: lang || "",
    langs: langs || "",
    created_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + RUNTIME_TTL_MS).toISOString()
  };

  PropertiesService
    .getScriptProperties()
    .setProperty("JOB_" + nonce, JSON.stringify(payload));

  return nonce;
}

function getRuntimeJob_(nonce) {
  if (!nonce) return null;

  const props = PropertiesService.getScriptProperties();
  const key = "JOB_" + nonce;
  const raw = props.getProperty(key);
  if (!raw) return null;

  let payload = null;
  try {
    payload = JSON.parse(raw);
  } catch (_) {
    props.deleteProperty(key);
    return null;
  }

  if (!payload.expires_at || new Date(payload.expires_at).getTime() < Date.now()) {
    props.deleteProperty(key);
    return null;
  }

  return payload;
}

function workerRuntime_(nonce) {
  const job = getRuntimeJob_(nonce);
  if (!job) {
    return {
      ok: false,
      error: "invalid_or_expired_nonce",
      message: "Runtime nonce 不存在或已過期"
    };
  }

  const props = PropertiesService.getScriptProperties();

  return {
    ok: true,
    task_id: job.task_id,
    stage: job.stage,
    google_access_token: ScriptApp.getOAuthToken(),
    gemini_api_key: String(props.getProperty("GEMINI_API_KEY") || ""),
    nvidia_api_key: String(props.getProperty("NVIDIA_API_KEY") || ""),
    youtube_cookies_b64: String(props.getProperty("YOUTUBE_COOKIES_B64") || ""),
    bridge_protocol: BRIDGE_PROTOCOL_VERSION,
    expires_at: job.expires_at
  };
}

function workerReport_(nonce, status, message) {
  const job = getRuntimeJob_(nonce);
  if (!job) {
    return {
      ok: false,
      error: "invalid_or_expired_nonce"
    };
  }

  const normalized = String(status || "").trim().toLowerCase();
  if (["running", "needs_review", "done", "error"].indexOf(normalized) < 0) {
    return {
      ok: false,
      error: "unsupported_worker_status"
    };
  }

  appendExecutionStatus_(
    job.task_id,
    job.stage,
    normalized,
    "web-" + nonce.slice(0, 12),
    normalized === "running" ? 1 : (normalized === "needs_review" ? 95 : (normalized === "done" ? 100 : "")),
    message || "",
    normalized === "running" ? nowText_() : "",
    ["needs_review", "done", "error"].indexOf(normalized) >= 0 ? nowText_() : "",
    normalized === "error" ? "web_worker_error" : "",
    normalized === "error" ? message || "" : "",
    "",
    ""
  );

  return {
    ok: true,
    task_id: job.task_id,
    stage: job.stage,
    status: normalized
  };
}

function reviewShareTokenKey_(token) {
  return "REVIEW_SHARE_TOKEN_" + String(token || "");
}

function reviewShareTaskKey_(taskId) {
  return "REVIEW_SHARE_TASK_" + String(taskId || "");
}

function createReviewShare_(taskId) {
  const normalizedTaskId = String(taskId || "").trim();
  if (!/^P\d+-L\d+$/i.test(normalizedTaskId)) {
    return {
      ok: false,
      error: "invalid_task_id",
      message: "task_id 格式不正確"
    };
  }

  const props = PropertiesService.getScriptProperties();
  const oldToken = String(
    props.getProperty(reviewShareTaskKey_(normalizedTaskId)) || ""
  ).trim();

  if (oldToken) {
    props.deleteProperty(reviewShareTokenKey_(oldToken));
  }

  const token = (
    Utilities.getUuid().replace(/-/g, "") +
    Utilities.getUuid().replace(/-/g, "")
  ).slice(0, 48);
  const createdAt = new Date();
  const expiresAt = new Date(createdAt.getTime() + 7 * 24 * 60 * 60 * 1000);

  props.setProperty(
    reviewShareTokenKey_(token),
    JSON.stringify({
      task_id: normalizedTaskId,
      created_at: createdAt.toISOString(),
      expires_at: expiresAt.toISOString()
    })
  );
  props.setProperty(reviewShareTaskKey_(normalizedTaskId), token);

  return {
    ok: true,
    task_id: normalizedTaskId,
    token: token,
    expires_at: expiresAt.toISOString()
  };
}

function validateReviewShare_(token, taskId) {
  const normalizedTaskId = String(taskId || "").trim();
  const normalizedToken = String(token || "").trim();

  if (!normalizedToken || !normalizedTaskId) {
    return { ok: false, error: "missing_share_token" };
  }

  const props = PropertiesService.getScriptProperties();
  const activeToken = String(
    props.getProperty(reviewShareTaskKey_(normalizedTaskId)) || ""
  ).trim();

  if (!activeToken || activeToken !== normalizedToken) {
    return {
      ok: false,
      error: "share_token_invalid",
      message: "這個編輯連結已失效，請向管理者取得新的連結。"
    };
  }

  const raw = String(
    props.getProperty(reviewShareTokenKey_(normalizedToken)) || ""
  ).trim();
  if (!raw) {
    return {
      ok: false,
      error: "share_token_invalid",
      message: "這個編輯連結已失效。"
    };
  }

  let grant = null;
  try {
    grant = JSON.parse(raw);
  } catch (_) {
    return { ok: false, error: "share_token_corrupt" };
  }

  if (String(grant.task_id || "") !== normalizedTaskId) {
    return { ok: false, error: "share_task_mismatch" };
  }

  const expires = new Date(String(grant.expires_at || "")).getTime();
  if (!expires || expires <= Date.now()) {
    props.deleteProperty(reviewShareTokenKey_(normalizedToken));
    props.deleteProperty(reviewShareTaskKey_(normalizedTaskId));
    return {
      ok: false,
      error: "share_token_expired",
      message: "這個編輯連結已過期，請向管理者取得新的連結。"
    };
  }

  return { ok: true, grant: grant };
}

function normalizedReviewSharePayload_(taskId, payloadJson) {
  let payload = null;
  try {
    payload = JSON.parse(String(payloadJson || ""));
  } catch (_) {
    return { ok: false, error: "invalid_payload_json" };
  }

  if (!payload || !Array.isArray(payload.segments) || !payload.segments.length) {
    return { ok: false, error: "empty_segments" };
  }

  if (payload.segments.length > 5000) {
    return { ok: false, error: "too_many_segments" };
  }

  const segments = payload.segments.map(function(x, i) {
    const start = Number(x.start || 0);
    const end = Number(x.end || start);
    return {
      id: Number(x.id !== undefined ? x.id : i),
      start: start,
      end: Math.max(start, end),
      time: String(x.time || formatPlainTime_(start)),
      raw: String(x.raw || ""),
      text: String(x.text || ""),
      flags: Array.isArray(x.flags)
        ? x.flags.map(function(v) { return String(v || ""); }).filter(Boolean)
        : [],
      confirmed: x.confirmed === true,
      source_en: String(x.source_en || ""),
      en_text: String(x.en_text || x.source_en || ""),
      en_confirmed: x.en_confirmed === true
    };
  });

  return {
    ok: true,
    payload: {
      version: 5,
      task_id: String(taskId || "").trim(),
      draft_saved_at: new Date().toISOString(),
      zh_finalized_at: String(payload.zh_finalized_at || payload.finalized_at || ""),
      en_finalized_at: String(payload.en_finalized_at || ""),
      english_cc_available: payload.english_cc_available === true,
      english_cc_language: String(payload.english_cc_language || ""),
      english_cc_source: String(payload.english_cc_source || ""),
      total_segments: segments.length,
      segments: segments
    }
  };
}

function publishReviewSharePayload_(taskId, payload) {
  const props = PropertiesService.getScriptProperties();
  const githubToken = String(props.getProperty("GITHUB_TOKEN") || "").trim();
  if (!githubToken) {
    return {
      ok: false,
      error: "github_token_missing",
      message: "GITHUB_TOKEN 尚未設定"
    };
  }

  const path = "studio-review-cache/" + taskId + "/zh.json";
  const contentB64 = Utilities.base64Encode(
    JSON.stringify(payload),
    Utilities.Charset.UTF_8
  );
  return githubUpsertBase64_(
    githubToken,
    path,
    contentB64,
    "Save shared review draft for " + taskId
  );
}

function reviewShareDraftSave_(taskId, payloadJson) {
  const normalizedTaskId = String(taskId || "").trim();
  if (!/^P\d+-L\d+$/i.test(normalizedTaskId)) {
    return {
      source: "soulkey-bridge",
      type: "review_share_draft_saved",
      ok: false,
      error: "invalid_task_id",
      message: "task_id 格式不正確"
    };
  }

  try {
    taskInfo_(normalizedTaskId);
  } catch (err) {
    return {
      source: "soulkey-bridge",
      type: "review_share_draft_saved",
      ok: false,
      error: "task_not_found",
      message: String(err && err.message ? err.message : err)
    };
  }

  const normalized = normalizedReviewSharePayload_(
    normalizedTaskId,
    payloadJson
  );
  if (!normalized.ok) {
    normalized.source = "soulkey-bridge";
    normalized.type = "review_share_draft_saved";
    return normalized;
  }

  const published = publishReviewSharePayload_(
    normalizedTaskId,
    normalized.payload
  );
  return {
    source: "soulkey-bridge",
    type: "review_share_draft_saved",
    ok: !!published.ok,
    task_id: normalizedTaskId,
    saved_at: normalized.payload.draft_saved_at,
    error: published.error || "",
    message: published.ok
      ? "進度已儲存"
      : (published.message || "進度儲存失敗")
  };
}

function reviewEnglishDraftSave_(taskId, payloadJson) {
  const normalizedTaskId = String(taskId || "").trim();
  if (!/^P\d+-L\d+$/i.test(normalizedTaskId)) {
    return {
      source: "soulkey-bridge",
      type: "english_review_draft_saved",
      ok: false,
      error: "invalid_task_id",
      message: "task_id 格式不正確"
    };
  }

  try {
    taskInfo_(normalizedTaskId);
  } catch (err) {
    return {
      source: "soulkey-bridge",
      type: "english_review_draft_saved",
      ok: false,
      error: "task_not_found",
      message: String(err && err.message ? err.message : err)
    };
  }

  const normalized = normalizedReviewSharePayload_(
    normalizedTaskId,
    payloadJson
  );
  if (!normalized.ok) {
    normalized.source = "soulkey-bridge";
    normalized.type = "english_review_draft_saved";
    return normalized;
  }

  const folders = lessonFolders_(normalizedTaskId);
  writeTextFile_(
    folders.translation,
    "en.review.draft.json",
    JSON.stringify(normalized.payload, null, 2),
    "application/json",
    normalizedTaskId
  );

  // English draft must not replace the Chinese sentence cache.
  const published = publishEnglishReviewCachePayload_(
    normalizedTaskId,
    normalized.payload
  );

  return {
    source: "soulkey-bridge",
    type: "english_review_draft_saved",
    ok: !!published.ok,
    task_id: normalizedTaskId,
    saved_at: normalized.payload.draft_saved_at,
    error: published.error || "",
    message: published.ok
      ? "英文確認進度已儲存"
      : (published.message || "英文確認進度儲存失敗")
  };
}

function reviewShareFinalize_(taskId, segmentsJson, payloadJson) {
  const normalizedTaskId = String(taskId || "").trim();
  if (!/^P\d+-L\d+$/i.test(normalizedTaskId)) {
    return {
      source: "soulkey-bridge",
      type: "review_share_finalized",
      ok: false,
      error: "invalid_task_id",
      message: "task_id 格式不正確"
    };
  }

  let segments = [];
  try {
    segments = JSON.parse(String(segmentsJson || ""));
  } catch (_) {
    return {
      source: "soulkey-bridge",
      type: "review_share_finalized",
      ok: false,
      error: "invalid_segments_json"
    };
  }

  const normalized = normalizedReviewSharePayload_(
    normalizedTaskId,
    payloadJson
  );
  if (!normalized.ok) {
    normalized.source = "soulkey-bridge";
    normalized.type = "review_share_finalized";
    return normalized;
  }

  const saved = saveReview_(normalizedTaskId, "zh", segments, []);
  if (!saved.ok) {
    saved.source = "soulkey-bridge";
    saved.type = "review_share_finalized";
    return saved;
  }

  normalized.payload.zh_finalized_at = new Date().toISOString();
  publishReviewSharePayload_(normalizedTaskId, normalized.payload);

  return {
    source: "soulkey-bridge",
    type: "review_share_finalized",
    ok: true,
    task_id: normalizedTaskId,
    segment_count: segments.length,
    finalized_at: normalized.payload.zh_finalized_at,
    message: "中文定稿完成。請進入中英對照，修正 English CC。"
  };
}

function reviewShareFinalizeEnglish_(taskId, segmentsJson, payloadJson) {
  const normalizedTaskId = String(taskId || "").trim();
  if (!/^P\d+-L\d+$/i.test(normalizedTaskId)) {
    return {
      source: "soulkey-bridge",
      type: "review_share_en_finalized",
      ok: false,
      error: "invalid_task_id",
      message: "task_id 格式不正確"
    };
  }

  let segments = [];
  try {
    segments = JSON.parse(String(segmentsJson || ""));
  } catch (_) {
    return {
      source: "soulkey-bridge",
      type: "review_share_en_finalized",
      ok: false,
      error: "invalid_segments_json"
    };
  }

  const normalized = normalizedReviewSharePayload_(
    normalizedTaskId,
    payloadJson
  );
  if (!normalized.ok) {
    normalized.source = "soulkey-bridge";
    normalized.type = "review_share_en_finalized";
    return normalized;
  }

  if (!normalized.payload.zh_finalized_at) {
    return {
      source: "soulkey-bridge",
      type: "review_share_en_finalized",
      ok: false,
      error: "zh_not_finalized",
      message: "請先完成中文定稿。"
    };
  }

  const saved = saveReview_(normalizedTaskId, "en", segments, []);
  if (!saved.ok) {
    saved.source = "soulkey-bridge";
    saved.type = "review_share_en_finalized";
    return saved;
  }

  normalized.payload.en_finalized_at = new Date().toISOString();
  // saveReview_ has already published the authoritative en.final.json cache.
  // Do not overwrite it with an in-flight draft.

  return {
    source: "soulkey-bridge",
    type: "review_share_en_finalized",
    ok: true,
    task_id: normalizedTaskId,
    segment_count: segments.length,
    finalized_at: normalized.payload.en_finalized_at,
    message: "英文定稿完成。接著選擇需要的逐字稿與音檔。"
  };
}

function reviewFinish_(taskId, planJson) {
  const normalizedTaskId = String(taskId || "").trim();
  if (!/^P\d+-L\d+$/i.test(normalizedTaskId)) {
    return {
      source: "soulkey-bridge",
      type: "review_finish_queued",
      ok: false,
      error: "invalid_task_id",
      message: "task_id 格式不正確"
    };
  }

  let plan = [];
  try {
    plan = JSON.parse(String(planJson || "[]"));
  } catch (_) {
    return {
      source: "soulkey-bridge",
      type: "review_finish_queued",
      ok: false,
      error: "invalid_plan_json"
    };
  }

  if (!Array.isArray(plan)) plan = [];

  try {
    taskInfo_(normalizedTaskId);
  } catch (err) {
    return {
      source: "soulkey-bridge",
      type: "review_finish_queued",
      ok: false,
      error: "task_not_found",
      message: String(err && err.message ? err.message : err)
    };
  }

  const folders = lessonFolders_(normalizedTaskId);
  if (!cachedFileId_(folders.translation, "en.final.json")) {
    return {
      source: "soulkey-bridge",
      type: "review_finish_queued",
      ok: false,
      error: "english_final_missing",
      message: "找不到 en.final.json，請先完成英文定稿。"
    };
  }

  const languageSettings = readLanguageSettings_();
  const enabledByCode = {};
  languageSettings.forEach(function(lang) {
    enabledByCode[String(lang.code || "").trim()] = lang;
  });
  const allowed = ["en"].concat(
    languageSettings
      .map(function(lang) { return String(lang.code || "").trim(); })
      .filter(function(code) { return !!code && code !== "en"; })
  );
  const clean = [];
  plan.forEach(function(item) {
    const code = String(item && item.language_code || "").trim();
    if (allowed.indexOf(code) < 0) return;

    const transcriptEnabled = code === "en"
      ? true
      : !!item.transcript_enabled;
    const languageSetting = enabledByCode[code] || null;
    const audioEnabled = !!item.audio_enabled &&
      (code === "en" || !!(languageSetting && languageSetting.can_tts));

    clean.push({
      language_code: code,
      language_name: String(item.language_name || code),
      transcript_enabled: transcriptEnabled || audioEnabled,
      transcript_source: code === "en" ? "human" : "ai",
      audio_enabled: audioEnabled,
      audio_source: audioEnabled ? "tts" : String(item.audio_source || "tts")
    });
  });

  saveLanguagePlan_(normalizedTaskId, clean);

  const translateLangs = clean
    .filter(function(x) {
      return x.language_code !== "en" && x.transcript_enabled;
    })
    .map(function(x) { return x.language_code; });

  const audioLangs = clean
    .filter(function(x) { return x.audio_enabled; })
    .map(function(x) { return x.language_code; });

  if (!translateLangs.length && !audioLangs.length) {
    appendExecutionStatus_(
      normalizedTaskId,
      "finish",
      "done",
      "human-" + new Date().getTime(),
      100,
      "中英文 Final 已完成；沒有勾選額外輸出",
      "",
      nowText_(),
      "",
      "",
      "",
      new Date().toISOString()
    );
    return {
      source: "soulkey-bridge",
      type: "review_finish_queued",
      ok: true,
      task_id: normalizedTaskId,
      translate_langs: [],
      audio_langs: [],
      message: "沒有勾選額外輸出；中英文 Final 已完成。"
    };
  }

  const props = PropertiesService.getScriptProperties();
  const githubToken = String(props.getProperty("GITHUB_TOKEN") || "").trim();
  if (!githubToken) {
    return {
      source: "soulkey-bridge",
      type: "review_finish_queued",
      ok: false,
      error: "github_token_missing",
      message: "GITHUB_TOKEN 尚未設定"
    };
  }

  const nonce = createRuntimeJob_(
    normalizedTaskId,
    "finish",
    audioLangs.join(","),
    translateLangs.join(",")
  );
  const bridgeUrl = ScriptApp.getService().getUrl();
  const dispatch = dispatchWorkflow_(
    githubToken,
    WORKFLOW_WEB_JOB,
    {
      task_id: normalizedTaskId,
      stage: "finish",
      lang: audioLangs.join(","),
      langs: translateLangs.join(","),
      runtime_nonce: nonce,
      bridge_url: bridgeUrl
    }
  );

  if (!dispatch.ok) {
    props.deleteProperty("JOB_" + nonce);
    return {
      source: "soulkey-bridge",
      type: "review_finish_queued",
      ok: false,
      error: dispatch.error || "dispatch_failed",
      message: "輸出工作送出失敗"
    };
  }

  appendExecutionStatus_(
    normalizedTaskId,
    "finish",
    "queued",
    String(dispatch.workflow_run_id || nonce.slice(0, 12)),
    0,
    "已送出最終輸出工作",
    "",
    "",
    "",
    "",
    "",
    ""
  );

  return {
    source: "soulkey-bridge",
    type: "review_finish_queued",
    ok: true,
    task_id: normalizedTaskId,
    translate_langs: translateLangs,
    audio_langs: audioLangs,
    workflow_run_id: dispatch.workflow_run_id || null,
    message: "已送出翻譯與音檔工作。"
  };
}


function githubPathEncode_(path) {
  return String(path || "").split("/").map(function(part) {
    return encodeURIComponent(part);
  }).join("/");
}

function githubUpsertBase64_(githubToken, path, contentB64, message) {
  if (!githubToken) {
    return {
      ok: false,
      error: "github_token_missing",
      message: "GITHUB_TOKEN 尚未設定"
    };
  }

  const encodedPath = githubPathEncode_(path);
  const baseUrl =
    "https://api.github.com/repos/" + OWNER + "/" + REPO +
    "/contents/" + encodedPath;

  let currentSha = "";
  const getResponse = UrlFetchApp.fetch(
    baseUrl + "?ref=" + encodeURIComponent(REF),
    {
      method: "get",
      headers: {
        Authorization: "Bearer " + githubToken,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10"
      },
      muteHttpExceptions: true
    }
  );

  const getStatus = getResponse.getResponseCode();
  if (getStatus === 200) {
    try {
      currentSha = String(JSON.parse(getResponse.getContentText()).sha || "");
    } catch (_) {}
  } else if (getStatus !== 404) {
    return {
      ok: false,
      error: "github_cache_lookup_failed",
      github_status: getStatus,
      github_body: String(getResponse.getContentText() || "").slice(0, 800)
    };
  }

  const body = {
    message: message || ("Update " + path),
    content: contentB64,
    branch: REF
  };
  if (currentSha) body.sha = currentSha;

  const putResponse = UrlFetchApp.fetch(baseUrl, {
    method: "put",
    contentType: "application/json",
    payload: JSON.stringify(body),
    headers: {
      Authorization: "Bearer " + githubToken,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2026-03-10"
    },
    muteHttpExceptions: true
  });

  const status = putResponse.getResponseCode();
  if (status !== 200 && status !== 201) {
    return {
      ok: false,
      error: "github_cache_publish_failed",
      github_status: status,
      github_body: String(putResponse.getContentText() || "").slice(0, 800)
    };
  }

  let result = {};
  try {
    result = JSON.parse(putResponse.getContentText());
  } catch (_) {}

  return {
    ok: true,
    path: path,
    sha: result && result.content ? result.content.sha || "" : "",
    commit_sha: result && result.commit ? result.commit.sha || "" : ""
  };
}

function workerReviewPublish_(nonce, taskId, contentB64) {
  const job = getRuntimeJob_(nonce);
  if (!job) {
    return {
      ok: false,
      error: "invalid_or_expired_nonce",
      message: "Runtime nonce 不存在或已過期"
    };
  }

  const normalizedTaskId = String(taskId || "").trim();
  if (!/^P\d+-L\d+$/i.test(normalizedTaskId)) {
    return {
      ok: false,
      error: "invalid_task_id",
      message: "task_id 格式不正確"
    };
  }

  if (String(job.task_id || "").trim() !== normalizedTaskId) {
    return {
      ok: false,
      error: "task_mismatch",
      message: "Runtime task 與發佈 task 不一致"
    };
  }

  if (!contentB64) {
    return {
      ok: false,
      error: "empty_review_cache",
      message: "沒有可發佈的人工定稿快取內容"
    };
  }

  const props = PropertiesService.getScriptProperties();
  const githubToken = String(props.getProperty("GITHUB_TOKEN") || "").trim();
  const path = "studio-review-cache/" + normalizedTaskId + "/zh.json";

  const result = githubUpsertBase64_(
    githubToken,
    path,
    contentB64,
    "Publish review cache for " + normalizedTaskId
  );

  result.task_id = normalizedTaskId;
  result.raw_url =
    "https://raw.githubusercontent.com/" + OWNER + "/" + REPO + "/" +
    REF + "/" + path;
  return result;
}

function workerTranslationCheckpointPublish_(nonce, taskId, contentB64) {
  const job = getRuntimeJob_(nonce);
  if (!job) {
    return {
      ok: false,
      error: "invalid_or_expired_nonce",
      message: "Runtime nonce 不存在或已過期"
    };
  }

  const normalizedTaskId = String(taskId || "").trim();
  if (!/^P\d+-L\d+$/i.test(normalizedTaskId)) {
    return {
      ok: false,
      error: "invalid_task_id",
      message: "task_id 格式不正確"
    };
  }

  if (String(job.task_id || "").trim() !== normalizedTaskId) {
    return {
      ok: false,
      error: "task_mismatch",
      message: "Runtime task 與 checkpoint task 不一致"
    };
  }

  if (!contentB64) {
    return {
      ok: false,
      error: "empty_translation_checkpoint",
      message: "沒有可發佈的翻譯 checkpoint 內容"
    };
  }

  const props = PropertiesService.getScriptProperties();
  const githubToken = String(props.getProperty("GITHUB_TOKEN") || "").trim();
  const path =
    "translation-shadow-cache/" + normalizedTaskId + "/gemini/checkpoint.json";

  const result = githubUpsertBase64_(
    githubToken,
    path,
    contentB64,
    "Publish Gemini translation checkpoint for " + normalizedTaskId
  );

  result.task_id = normalizedTaskId;
  result.raw_url =
    "https://raw.githubusercontent.com/" + OWNER + "/" + REPO + "/" +
    REF + "/" + path;
  return result;
}

function publishEnglishReviewCachePayload_(taskId, payload) {
  // English passages are grouped separately from the short Chinese segments.
  // NEVER write these rows into /zh.json: doing so would overwrite the
  // 400+ Chinese sentence editor with only ~40 English paragraphs.
  const token = String(
    PropertiesService.getScriptProperties().getProperty("GITHUB_TOKEN") || ""
  ).trim();
  return githubUpsertBase64_(
    token,
    "studio-review-cache/" + taskId + "/en.json",
    Utilities.base64Encode(JSON.stringify(payload), Utilities.Charset.UTF_8),
    "Update fast English review cache for " + taskId
  );
}

/**
 * Automatic bilingual paragraph pairing for every completed Chinese Final.
 * Keep English sentence boundaries while assigning each Chinese Final segment
 * exactly once. This is deterministic and does not invoke any AI/GPU service.
 */
function alignEnglishReviewParagraphs_(chinese, englishCues, metadata) {
  const zh = (chinese || []).filter(function(x) {
    return String(x.text || "").trim() && Number.isFinite(Number(x.start));
  }).slice().sort(function(a,b){ return Number(a.start)-Number(b.start); });
  const cues = (englishCues || []).filter(function(x){
    return String(x.text || "").trim() && Number.isFinite(Number(x.start));
  }).slice().sort(function(a,b){ return Number(a.start)-Number(b.start); });
  if (!zh.length || !cues.length) return null;

  const sentences = [];
  let pending = [];
  function flushSentence() {
    if (!pending.length) return;
    sentences.push({
      start:pending[0].start,
      end:pending[pending.length-1].end,
      text:pending.map(function(x){return x.text;}).join(" ").replace(/\s+/g," ").trim()
    });
    pending=[];
  }
  cues.forEach(function(cue) {
    const text=String(cue.text||"").replace(/\s+/g," ").trim();
    const start=Number(cue.start||0);
    const end=Math.max(start,Number(cue.end||start));
    let from=0;
    // One CC line may contain the end of one English sentence AND the start
    // of the next. Keep both rather than cutting at the subtitle boundary.
    const endings=/[.!?](?=\s|["'”]|$)/g;
    let match;
    while ((match=endings.exec(text))!==null) {
      const to=match.index+1;
      const part=text.slice(from,to).trim();
      if (part) {
        pending.push({
          start:start+(end-start)*(from/text.length),
          end:start+(end-start)*(to/text.length),
          text:part
        });
        flushSentence();
      }
      from=to;
    }
    const rest=text.slice(from).trim();
    if(rest) pending.push({
      start:start+(end-start)*(from/text.length),
      end:end,
      text:rest
    });
  });
  flushSentence();
  if (!sentences.length) return null;

  const paragraphs=[];
  for(let i=0;i<sentences.length;){
    let last=i;
    while (
      last+1<sentences.length &&
      sentences[last].end-sentences[i].start<22 &&
      sentences[last+1].end-sentences[i].start<=35
    ) last++;
    paragraphs.push({
      start:sentences[i].start,
      end:sentences[last].end,
      text:sentences.slice(i,last+1).map(function(x){return x.text;}).join(" ")
    });
    i=last+1;
  }

  if(paragraphs.length>zh.length) return null;
  const rows=[];
  let previous=-1;
  paragraphs.forEach(function(en,g) {
    let boundary=zh.length-1;
    if(g<paragraphs.length-1){
      const remaining=paragraphs.length-g-1;
      let score=Infinity;
      for(let j=previous+1;j<zh.length-remaining;j++){
        const stop=Number(zh[j].end||zh[j].start||0);
        const gap=Math.min(3,Math.max(0,Number(zh[j+1].start||0)-stop));
        const complete=/[。？！.!?]$/.test(String(zh[j].text||"").trim());
        const candidate=Math.abs(stop-en.end)-0.18*gap-(complete?0.5:0);
        if(candidate<score){score=candidate;boundary=j;}
      }
    }
    const chunk=zh.slice(previous+1,boundary+1);
    if(!chunk.length) throw new Error("Chinese alignment group is empty");
    const start=Number(chunk[0].start||0);
    rows.push({
      id:Number(chunk[0].id===undefined?previous+1:chunk[0].id),
      start:start,
      end:Number(chunk[chunk.length-1].end||start),
      time:formatPlainTime_(start),
      text:chunk.map(function(x){return String(x.text||"").trim();}).join(""),
      source_en:en.text,
      en_text:en.text,
      en_confirmed:false,
      pre_aligned:true,
      zh_ids:chunk.map(function(x,j){return Number(x.id===undefined?previous+j+1:x.id);}),
      cc_start:Math.round(en.start*1000)/1000,
      cc_end:Math.round(en.end*1000)/1000
    });
    previous=boundary;
  });

  // A failed alignment must never be published or overwrite human edits.
  const joinedZh=zh.map(function(x){return String(x.text||"").trim();}).join("");
  const outZh=rows.map(function(x){return x.text;}).join("");
  const joinedEn=sentences.map(function(x){return x.text;}).join(" ");
  const outEn=rows.map(function(x){return x.en_text;}).join(" ");
  if(joinedZh!==outZh || joinedEn!==outEn) {
    throw new Error("English alignment content integrity failed");
  }
  return {
    version:6,
    task_id:String(metadata.task_id||""),
    generated_at:new Date().toISOString(),
    alignment_method:"english_sentence_chinese_time_v1",
    source_video_id:String(metadata.video_id||""),
    zh_finalized_at:String(metadata.zh_finalized_at||""),
    english_cc_available:metadata.is_cc===true,
    english_cc_language:"en",
    english_cc_source:metadata.is_cc===true?"youtube_caption":"ai_translation",
    total_segments:rows.length,
    original_zh_segments:zh.length,
    original_en_cc_cues:cues.length,
    segments:rows
  };
}

function workerEnglishCacheSeed_(nonce, taskId) {
  const runtime=getRuntimeJob_(nonce);
  const normalized=String(taskId||"").trim();
  if(!runtime || !/^P\d+-L\d+$/i.test(normalized) ||
     String(runtime.task_id||"")!==normalized) {
    return {ok:false,error:"worker_english_cache_unauthorized"};
  }
  return seedEnglishReviewCache_(normalized);
}

function seedEnglishReviewCache_(taskId) {
  const normalizedTaskId = String(taskId || "").trim();
  if (!/^P\d+-L\d+$/i.test(normalizedTaskId)) {
    return {ok:false,error:"invalid_task_id"};
  }
  const folders = lessonFolders_(normalizedTaskId);
  const chinese = readJsonFile_(folders.transcript, "zh-TW.final.json");
  const englishFinal = readJsonFile_(folders.translation, "en.final.json");
  const englishDraft = readJsonFile_(folders.translation, "en.review.draft.json");
  if (!chinese || !Array.isArray(chinese.segments) || !chinese.segments.length) {
    return {ok:false,error:"review_files_missing",message:"找不到中文人工定稿"};
  }
  if (!englishFinal && !englishDraft) {
    // The Chinese Final button automatically makes an English/Chinese 1:1
    // review cache, using YouTube CC first or Gemini English as fallback.
    const cc=readJsonFile_(folders.source,"youtube.en.json");
    const ai=readJsonFile_(folders.translation,"en.json");
    const source=(cc && Array.isArray(cc.segments) && cc.segments.length) ? cc
      : (ai && Array.isArray(ai.segments) && ai.segments.length ? ai : null);
    if(!source) return {
      ok:false,error:"english_source_not_ready",
      message:"尚無 English CC／AI 英譯；待英文來源完成後建立快取"
    };
    const aligned=alignEnglishReviewParagraphs_(
      chinese.segments,source.segments,{
        task_id:normalizedTaskId,
        zh_finalized_at:String(chinese.finalized_at||""),
        video_id:String(cc && source===cc ? cc.video_id||"" : ""),
        is_cc:source===cc
      }
    );
    if(!aligned) return {ok:false,error:"english_align_empty"};
    return publishEnglishReviewCachePayload_(normalizedTaskId,aligned);
  }
  let segments;
  if (englishFinal && Array.isArray(englishFinal.segments) && englishFinal.segments.length) {
    segments = englishFinal.segments.map(function(item,index){
      const id = Number(item.id !== undefined ? item.id : index);
      const start = Number(item.start || 0);
      const end = Number(item.end !== undefined ? item.end : start);
      const en = String(item.text || "").trim();
      return {
        id:id,start:start,end:end,
        time:formatPlainTime_(start),
        text:chineseFinalForEnglishTimeRange_(chinese.segments || [],start,end,id),
        source_en:en,en_text:en,en_confirmed:true
      };
    });
  } else {
    segments = (englishDraft.segments || []).map(function(item,index){
      const id = Number(item.id !== undefined ? item.id : index);
      const start = Number(item.start || 0);
      const end = Number(item.end !== undefined ? item.end : start);
      return {
        id:id,start:start,end:end,
        time:String(item.time || formatPlainTime_(start)),
        text:String(item.text || "") ||
          chineseFinalForEnglishTimeRange_(chinese.segments || [],start,end,id),
        source_en:String(item.source_en || ""),
        en_text:String(item.en_text || item.source_en || ""),
        en_confirmed:item.en_confirmed===true
      };
    });
  }
  const payload = {
    version:5,task_id:normalizedTaskId,
    generated_at:new Date().toISOString(),
    zh_finalized_at:String(chinese.finalized_at || ""),
    en_finalized_at:englishFinal ? String(englishFinal.finalized_at || "") : "",
    total_segments:segments.length,
    segments:segments
  };
  return publishEnglishReviewCachePayload_(normalizedTaskId,payload);
}

function seedReviewCache_(taskId, githubToken) {
  const normalizedTaskId = String(taskId || "").trim();
  if (!/^P\d+-L\d+$/i.test(normalizedTaskId)) {
    return {
      ok: false,
      error: "invalid_task_id",
      message: "task_id 格式不正確"
    };
  }

  const folders = lessonFolders_(normalizedTaskId);
  const raw = readJsonFile_(folders.transcript, "segments.json");
  const polished = readJsonFile_(folders.transcript, "polish_report.json");
  if (!raw || !polished) {
    return {
      ok: false,
      error: "review_files_missing",
      message: "找不到既有中文校稿檔案"
    };
  }

  let items = zhReviewItems_(raw, polished);
  // A re-seed must never roll back text that a human already finalized.
  // Quick Review can request this action on every opening.
  const chineseFinal = readJsonFile_(folders.transcript, "zh-TW.final.json");
  if(chineseFinal && Array.isArray(chineseFinal.segments) &&
     chineseFinal.segments.length){
    const finalized={};
    chineseFinal.segments.forEach(function(x,i){
      finalized[Number(x.id!==undefined?x.id:i)]=String(x.text||"");
    });
    items=items.map(function(x,i){
      const id=Number(x.id!==undefined?x.id:i);
      return Object.prototype.hasOwnProperty.call(finalized,id)
        ? Object.assign({},x,{text:finalized[id],confirmed:true})
        : x;
    });
  }
  const youtubeCc = readJsonFile_(folders.source, "youtube.en.json");
  if (youtubeCc) {
    items = alignEnglishCcToReviewItems_(items, youtubeCc);
  }
  const payload = JSON.stringify({
    version: 5,
    task_id: normalizedTaskId,
    generated_at: new Date().toISOString(),
    zh_finalized_at: chineseFinal ? String(chineseFinal.finalized_at || "") : "",
    english_cc_available: !!youtubeCc,
    english_cc_language: youtubeCc ? String(youtubeCc.language || "en") : "",
    english_cc_source: youtubeCc ? "youtube_caption" : "",
    total_segments: items.length,
    segments: items
  });
  const contentB64 = Utilities.base64Encode(payload, Utilities.Charset.UTF_8);
  const path = "studio-review-cache/" + normalizedTaskId + "/zh.json";

  const result = githubUpsertBase64_(
    githubToken,
    path,
    contentB64,
    "Seed review cache for " + normalizedTaskId
  );
  result.task_id = normalizedTaskId;
  result.raw_url =
    "https://raw.githubusercontent.com/" + OWNER + "/" + REPO + "/" +
    REF + "/" + path;
  return result;
}


function appendExecutionStatus_(
  taskId,
  stage,
  status,
  runId,
  progress,
  message,
  startedAt,
  finishedAt,
  errorCode,
  errorMessage,
  inputRevision,
  outputRevision
) {
  const sheet = getStatusSheet_();
  sheet.appendRow([
    taskId,
    stage,
    status,
    runId || "",
    progress === undefined ? "" : progress,
    String(message || "").slice(0, 1000),
    startedAt || "",
    finishedAt || "",
    nowText_(),
    errorCode || "",
    String(errorMessage || "").slice(0, 1000),
    inputRevision || "",
    outputRevision || ""
  ]);
}

function nowText_() {
  return Utilities.formatDate(
    new Date(),
    Session.getScriptTimeZone() || "Asia/Taipei",
    "yyyy-MM-dd HH:mm:ss"
  );
}

function workflowDispatchResponse_(githubToken, workflow, inputs, type) {
  if (!githubToken) {
    return {
      source: "soulkey-bridge",
      type: type,
      ok: false,
      error: "server_not_configured",
      message: "GITHUB_TOKEN 尚未設定"
    };
  }

  const result = dispatchWorkflow_(githubToken, workflow, inputs);
  result.source = "soulkey-bridge";
  result.type = type;
  return result;
}

function dispatchWorkflow_(githubToken, workflowFile, inputs) {
  const url =
    "https://api.github.com/repos/" + OWNER + "/" + REPO +
    "/actions/workflows/" + encodeURIComponent(workflowFile) + "/dispatches";

  const payload = { ref: REF };
  if (inputs && Object.keys(inputs).length) payload.inputs = inputs;

  const response = UrlFetchApp.fetch(url, {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    headers: {
      Authorization: "Bearer " + githubToken,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2026-03-10"
    },
    muteHttpExceptions: true
  });

  const status = response.getResponseCode();
  const responseText = String(response.getContentText() || "").trim();

  if (status !== 200 && status !== 204) {
    return {
      ok: false,
      error: "github_dispatch_failed",
      github_status: status,
      github_body: responseText.slice(0, 800)
    };
  }

  let githubResult = {};
  if (responseText) {
    try {
      githubResult = JSON.parse(responseText);
    } catch (_) {}
  }

  return {
    ok: true,
    workflow: workflowFile,
    message: "GitHub Actions workflow dispatched",
    workflow_run_id: githubResult.workflow_run_id || null,
    html_url: githubResult.html_url || null
  };
}

function dispatchSmoke_(githubToken) {
  const result = dispatchWorkflow_(githubToken, WORKFLOW, {});
  result.action = "smoke";
  return json_(result);
}

function getSheetByName_(name) {
  const spreadsheet = SpreadsheetApp.openById(CONTROL_SHEET_ID);
  const sheet = spreadsheet.getSheetByName(name);
  if (!sheet) throw new Error("找不到工作表：" + name);
  return sheet;
}

function ensureTaskIdentitySchema_() {
  const sheet = getSheetByName_(TASK_SHEET_NAME);
  const schemaCache = CacheService.getScriptCache();
  if (schemaCache.get("task-identity-schema-v2") === "ok") return sheet;

  const maxColumns = sheet.getMaxColumns();
  if (maxColumns < TASK_TOTAL_COLUMNS) {
    sheet.insertColumnsAfter(maxColumns, TASK_TOTAL_COLUMNS - maxColumns);
  }

  const headers = [
    "課程UID", "排程狀態", "原始期數", "原始堂次", "上次調課時間", "調課紀錄"
  ];
  sheet.getRange(1, 21, 1, headers.length).setValues([headers]);

  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return sheet;

  const values = sheet.getRange(2, 1, lastRow - 1, TASK_TOTAL_COLUMNS).getValues();
  let maxUid = 0;
  values.forEach(function(row) {
    const m = /^SKC-(\d+)$/i.exec(String(row[TASK_COL.course_uid] || "").trim());
    if (m) maxUid = Math.max(maxUid, Number(m[1]) || 0);
  });

  const updates = [];
  const assignedUids = new Set();
  values.forEach(function(row, index) {
    if (!String(row[0] || "").trim()) return;
    let changed = false;
    let uid = String(row[TASK_COL.course_uid] || "").trim();
    // Keep the first recorded UID; repair duplicates without changing task IDs.
    if (!uid || assignedUids.has(uid)) {
      do {
        maxUid += 1;
        uid = "SKC-" + String(maxUid).padStart(6, "0");
      } while (assignedUids.has(uid));
      row[TASK_COL.course_uid] = uid;
      changed = true;
    }
    assignedUids.add(uid);
    if (!String(row[TASK_COL.schedule_status] || "").trim()) {
      row[TASK_COL.schedule_status] = "已排定";
      changed = true;
    }
    if (!String(row[TASK_COL.original_period] || "").trim()) {
      row[TASK_COL.original_period] = row[1] || "";
      changed = true;
    }
    if (!String(row[TASK_COL.original_lesson] || "").trim()) {
      row[TASK_COL.original_lesson] = row[2] || "";
      changed = true;
    }
    if (changed) updates.push({row: index + 2, values: row});
  });

  updates.forEach(function(item) {
    sheet.getRange(item.row, 1, 1, TASK_TOTAL_COLUMNS).setValues([item.values]);
  });
  schemaCache.put("task-identity-schema-v2", "ok", 21600);
  return sheet;
}

function allocateCourseUid_(sheet) {
  const lastRow = sheet.getLastRow();
  let maxUid = 0;
  if (lastRow >= 2) {
    const values = sheet.getRange(2, 21, lastRow - 1, 1).getDisplayValues();
    values.forEach(function(row) {
      const m = /^SKC-(\d+)$/i.exec(String(row[0] || "").trim());
      if (m) maxUid = Math.max(maxUid, Number(m[1]) || 0);
    });
  }
  return "SKC-" + String(maxUid + 1).padStart(6, "0");
}

function allocateTaskId_(baseId, byId) {
  if (!byId[baseId]) return baseId;
  let n = 2;
  while (byId[baseId + "-R" + n]) n += 1;
  return baseId + "-R" + n;
}

function readTasks_() {
  const sheet = ensureTaskIdentitySchema_();
  const values = sheet.getDataRange().getDisplayValues();
  const result = [];

  for (let r = 1; r < values.length; r++) {
    const row = values[r];
    const id = String(row[0] || "").trim();
    if (!id) continue;

    result.push({
      id: id,
      course_uid: String(row[TASK_COL.course_uid] || "").trim(),
      schedule_status: String(row[TASK_COL.schedule_status] || "").trim(),
      original_period: Number(String(row[TASK_COL.original_period] || "").replace(/[^0-9]/g, "")) || null,
      original_lesson: String(row[TASK_COL.original_lesson] || "").trim(),
      rescheduled_at: String(row[TASK_COL.rescheduled_at] || "").trim(),
      schedule_note: String(row[TASK_COL.schedule_note] || "").trim(),
      period: Number(String(row[1] || "").replace(/[^0-9]/g, "")) || null,
      lesson: String(row[2] || "").trim(),
      title: String(row[3] || "").trim(),
      url: String(row[4] || "").trim(),
      lecturer: String(row[5] || "").trim(),
      source_language: String(row[6] || "").trim(),
      asr: String(row[7] || "").trim(),
      zh_review: String(row[8] || "").trim(),
      en: String(row[9] || "").trim(),
      th: String(row[10] || "").trim(),
      es: String(row[11] || "").trim(),
      id_lang: String(row[12] || "").trim(),
      vi: String(row[13] || "").trim(),
      subtitle: String(row[14] || "").trim(),
      audio: String(row[15] || "").trim(),
      video: String(row[16] || "").trim(),
      progress: String(row[17] || "").trim(),
      updated_at: String(row[18] || "").trim(),
      note: String(row[19] || "").trim()
    });
  }

  return result;
}

function upsertTasks_(items) {
  if (!Array.isArray(items) || !items.length) {
    throw new Error("tasks_json 必須至少包含一個任務");
  }

  // Two Studio tabs may save concurrently. Reserve UIDs under one lock.
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const sheet = ensureTaskIdentitySchema_();
    const values = sheet.getDataRange().getValues();
    const byId = {};
    const uidOwner = {};
    let maxUid = 0;

    for (let r = 1; r < values.length; r++) {
      const id = String(values[r][0] || "").trim();
      if (!id) continue;
      byId[id] = r + 1;
      const uid = String(values[r][TASK_COL.course_uid] || "").trim();
      if (uid) uidOwner[uid] = id;
      const parsed = /^SKC-(\d+)$/i.exec(uid);
      if (parsed) maxUid = Math.max(maxUid, Number(parsed[1]) || 0);
    }

    const allocateUid = function() {
      let uid;
      do {
        maxUid += 1;
        uid = "SKC-" + String(maxUid).padStart(6, "0");
      } while (uidOwner[uid]);
      return uid;
    };

    const saved = [];

    items.slice(0, 20).forEach(function(item) {
    let requestedId = String(item.id || item.task_id || "").trim();
    const period = Number(item.period || 0);
    const lesson = String(item.lesson || "").trim();
    const url = String(item.url || item.youtube_url || "").trim();
    const note = String(item.note || "").trim();

    if (!requestedId || !period || !lesson || !url) {
      throw new Error("任務缺少 id / period / lesson / url");
    }

    // Only provision folders for the requested lesson. New periods must not
    // perform 28 Drive folder calls before their first task can be registered.
    ensurePeriodStructure_(period, Number((lesson.match(/\d+/) || [])[0]) || null);

    let existingRow = byId[requestedId] || null;
    if (existingRow) {
      const existing = sheet.getRange(existingRow, 1, 1, TASK_TOTAL_COLUMNS).getValues()[0];
      const existingPeriod = Number(existing[1] || 0);
      const existingLesson = String(existing[2] || "").trim();
      // If the old task ID has already moved to another schedule slot, a new
      // course created in its former slot must get a fresh legacy ID instead
      // of overwriting the moved course.
      if (
        // A reused legacy task ID must never overwrite a different lesson.
        // Scheduling existing courses is handled by the dedicated move action.
        (existingPeriod !== period || existingLesson !== lesson)
      ) {
        requestedId = allocateTaskId_(requestedId, byId);
        existingRow = null;
      }
    }

    const id = requestedId;
    let row = existingRow
      ? sheet.getRange(existingRow, 1, 1, TASK_TOTAL_COLUMNS).getValues()[0]
      : new Array(TASK_TOTAL_COLUMNS).fill("");

    const previousUrl = String(row[4] || "").trim();
    const sourceChanged = !!(
      existingRow && previousUrl && previousUrl !== url
    );

    if (sourceChanged) {
      row[3] = "";
      row[5] = "";
      for (let idx = 7; idx <= 13; idx++) row[idx] = "";

      ["zh", "en-review", "multi", "tts"].forEach(function(stage) {
        appendStaleIfDone_(
          id,
          stage,
          "YouTube 來源網址已變更；舊輸出不可沿用"
        );
      });
    }

    row[0] = id;
    row[1] = period;
    row[2] = lesson;
    row[4] = url;
    row[6] = row[6] || "zh-TW";
    row[18] = nowText_();
    row[19] = sourceChanged
      ? "YouTube 來源已更新；需從中文 ASR/校稿重新執行"
      : (note || row[19] || "由 SoulKey Studio 建立");

    // Never trust an old course_uid echoed back by browser storage.
    // Only the persisted UID can be reused by its own task.
    const persistedUid = String(row[TASK_COL.course_uid] || "").trim();
    const chosenUid = (
      existingRow && persistedUid &&
      (!uidOwner[persistedUid] || uidOwner[persistedUid] === id)
    ) ? persistedUid : allocateUid();
    row[TASK_COL.course_uid] = chosenUid;
    uidOwner[chosenUid] = id;
    row[TASK_COL.schedule_status] =
      String(row[TASK_COL.schedule_status] || "").trim() || "已排定";
    row[TASK_COL.original_period] =
      String(row[TASK_COL.original_period] || "").trim() || period;
    row[TASK_COL.original_lesson] =
      String(row[TASK_COL.original_lesson] || "").trim() || lesson;

    if (existingRow) {
      sheet.getRange(existingRow, 1, 1, TASK_TOTAL_COLUMNS).setValues([row]);
    } else {
      sheet.appendRow(row);
      byId[id] = sheet.getLastRow();
    }

    saved.push({
      id: id,
      course_uid: row[TASK_COL.course_uid],
      period: period,
      lesson: lesson,
      url: url
    });
    });
    SpreadsheetApp.flush();
    return saved;
  } finally {
    lock.releaseLock();
  }
}

function ensurePeriodStructure_(period, lessonNumber) {
  const sheet = getSheetByName_(PERIOD_SHEET_NAME);
  const values = sheet.getDataRange().getValues();
  let existingUrl = "";

  for (let r = 1; r < values.length; r++) {
    const code = String(values[r][0] || "");
    const name = String(values[r][1] || "");
    // P256 and 第256期 must parse as 256, NOT 256256.
    const codeNumber = Number((code.match(/\d+/) || [])[0] || 0);
    const nameNumber = Number((name.match(/\d+/) || [])[0] || 0);
    const url = String(values[r][5] || "").trim();
    if ((codeNumber === period || nameNumber === period) && url) {
      existingUrl = url;
      break;
    }
  }

  // Historical callers expect the whole period to be ready; existing periods
  // retain their prior full-folder behavior without repeating Drive calls.
  if (existingUrl && !lessonNumber) return existingUrl;

  const root = DriveApp.getFolderById(ROOT_DRIVE_FOLDER_ID);
  const periodName = period + "_第" + period + "期";
  const folderMatch = existingUrl.match(/\/folders\/([A-Za-z0-9_-]+)/);
  let periodFolder = null;
  if (folderMatch) {
    try { periodFolder = DriveApp.getFolderById(folderMatch[1]); } catch (_) {}
  }
  if (!periodFolder) periodFolder = findOrCreateFolder_(root, periodName);

  if (!existingUrl) {
    findOrCreateFolder_(periodFolder, "00_期別設定");
    findOrCreateFolder_(periodFolder, "98_人工檢查");
    findOrCreateFolder_(periodFolder, "99_期末封存");
  }
  const courseFolder = findOrCreateFolder_(periodFolder, "01_課程");
  const subNames = [
    "00_來源資訊", "01_中文逐字稿", "02_翻譯稿", "03_字幕",
    "04_音檔", "05_完成影片", "99_處理紀錄"
  ];
  const requested = Number(lessonNumber || 0);
  const lessonNumbers = requested >= 1 && requested <= 4
    ? [requested] : [1, 2, 3, 4];

  lessonNumbers.forEach(function(number) {
    const lesson = findOrCreateFolder_(
      courseFolder, String(number).padStart(2, "0") + "_第" + number + "堂"
    );
    subNames.forEach(function(name) { findOrCreateFolder_(lesson, name); });
  });

  const url = "https://drive.google.com/drive/folders/" + periodFolder.getId();
  if (!existingUrl) {
    sheet.appendRow([
      "P" + period, "第" + period + "期", "啟用", "", "", url, 4,
      "由 SoulKey Studio 自動建立"
    ]);
  }
  return url;
}

function findOrCreateFolder_(parent, name) {
  const iter = parent.getFoldersByName(name);
  if (iter.hasNext()) return iter.next();
  return parent.createFolder(name);
}

function readLanguageSettings_() {
  const sheet = getSheetByName_(LANGUAGE_SHEET_NAME);
  const values = sheet.getDataRange().getDisplayValues();
  const result = [];

  for (let r = 1; r < values.length; r++) {
    const row = values[r];
    const code = String(row[0] || "").trim();
    const name = String(row[1] || "").trim();
    const enabled = String(row[2] || "").trim().toUpperCase() === "TRUE";
    const translationModel = String(row[3] || "").trim();
    const ttsModel = String(row[4] || "").trim();

    if (!code || !enabled) continue;

    result.push({
      code: code,
      name: name || code,
      translation_model: translationModel,
      tts_model: ttsModel,
      can_ai_translate: !!translationModel,
      can_tts: !!ttsModel
    });
  }

  return result;
}

function readLanguagePlan_(taskId) {
  const sheet = getSheetByName_(LANGUAGE_PLAN_SHEET_NAME);
  const values = sheet.getDataRange().getDisplayValues();
  const result = [];

  for (let r = 1; r < values.length; r++) {
    const row = values[r];
    if (String(row[0] || "").trim() !== taskId) continue;

    result.push({
      task_id: taskId,
      language_code: String(row[1] || "").trim(),
      language_name: String(row[2] || "").trim(),
      transcript_enabled: String(row[3] || "").trim().toUpperCase() === "TRUE",
      transcript_source: String(row[4] || "").trim(),
      audio_enabled: String(row[5] || "").trim().toUpperCase() === "TRUE",
      audio_source: String(row[6] || "").trim(),
      status: String(row[7] || "").trim(),
      updated_at: String(row[8] || "").trim(),
      note: String(row[9] || "").trim()
    });
  }

  return result;
}

function canonicalLanguagePlan_(plan) {
  return (Array.isArray(plan) ? plan : [])
    .map(function(item) {
      const code = String(item.language_code || item.code || "").trim();
      if (!code) return null;
      const transcriptEnabled = !!item.transcript_enabled;
      const audioEnabled = !!item.audio_enabled;
      return {
        code: code,
        transcript_enabled: transcriptEnabled,
        transcript_source: transcriptEnabled
          ? String(item.transcript_source || "ai").trim()
          : "skip",
        audio_enabled: audioEnabled,
        audio_source: audioEnabled
          ? String(item.audio_source || "tts").trim()
          : "skip"
      };
    })
    .filter(Boolean)
    .sort(function(a, b) { return a.code.localeCompare(b.code); });
}

function languagePlanSignatures_(plan) {
  const normalized = canonicalLanguagePlan_(plan);
  return {
    translation: JSON.stringify(normalized.map(function(x) {
      return [x.code, x.transcript_enabled, x.transcript_source];
    })),
    audio: JSON.stringify(normalized.map(function(x) {
      return [x.code, x.audio_enabled, x.audio_source];
    }))
  };
}

function appendStaleIfDone_(taskId, stage, message) {
  const latest = readLatestStatuses_([taskId]);
  const item = latest[taskId] && latest[taskId].stages
    ? latest[taskId].stages[stage]
    : null;
  if (!item || String(item.status || "") !== "done") return false;

  appendExecutionStatus_(
    taskId,
    stage,
    "stale",
    "invalidate-" + new Date().getTime(),
    "",
    message,
    "",
    nowText_(),
    "upstream_changed",
    message,
    String(item.output_revision || ""),
    ""
  );
  return true;
}

function invalidateDownstreamAfterHumanFinal_(taskId, kind) {
  if (kind === "zh") {
    appendStaleIfDone_(
      taskId,
      "en-review",
      "中文 Final 已更新；英文定稿需重新確認"
    );
    appendStaleIfDone_(
      taskId,
      "multi",
      "中文 Final 已更新；多語翻譯需重新確認"
    );
    appendStaleIfDone_(
      taskId,
      "tts",
      "中文 Final 已更新；音檔需在下游文字更新後重新確認"
    );
  } else if (kind === "en") {
    appendStaleIfDone_(
      taskId,
      "multi",
      "English Final 已更新；多語翻譯需重跑"
    );
    appendStaleIfDone_(
      taskId,
      "tts",
      "English Final 已更新；音檔需在翻譯更新後重跑"
    );
  }
}

function saveLanguagePlan_(taskId, plan) {
  if (!Array.isArray(plan)) throw new Error("plan 必須是陣列");

  const previous = readLanguagePlan_(taskId);
  const previousSig = languagePlanSignatures_(previous);
  const nextSig = languagePlanSignatures_(plan);
  const hadPrevious = previous.length > 0;

  const sheet = getSheetByName_(LANGUAGE_PLAN_SHEET_NAME);
  const values = sheet.getDataRange().getDisplayValues();

  for (let r = values.length - 1; r >= 1; r--) {
    if (String(values[r][0] || "").trim() === taskId) {
      sheet.deleteRow(r + 1);
    }
  }

  const rows = [];
  canonicalLanguagePlan_(plan).slice(0, 50).forEach(function(item) {
    rows.push([
      taskId,
      item.code,
      String(
        (plan.find(function(x) {
          return String(x.language_code || x.code || "").trim() === item.code;
        }) || {}).language_name ||
        (plan.find(function(x) {
          return String(x.language_code || x.code || "").trim() === item.code;
        }) || {}).name ||
        item.code
      ).trim(),
      item.transcript_enabled,
      item.transcript_source,
      item.audio_enabled,
      item.audio_source,
      "planned",
      nowText_(),
      ""
    ]);
  });

  if (rows.length) {
    sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, 10).setValues(rows);
  }

  if (hadPrevious && previousSig.translation !== nextSig.translation) {
    appendStaleIfDone_(
      taskId,
      "multi",
      "語言輸出設定已變更；多語翻譯需依新設定重新執行"
    );
    appendStaleIfDone_(
      taskId,
      "tts",
      "語言輸出設定已變更；音檔需依新翻譯重新確認"
    );
  } else if (hadPrevious && previousSig.audio !== nextSig.audio) {
    appendStaleIfDone_(
      taskId,
      "tts",
      "音檔語言設定已變更；TTS 需依新設定重新執行"
    );
  }

  return {
    translation_changed:
      hadPrevious && previousSig.translation !== nextSig.translation,
    audio_changed:
      hadPrevious && previousSig.audio !== nextSig.audio
  };
}

function getStatusSheet_() {
  return getSheetByName_(STATUS_SHEET_NAME);
}

function isGenericWorkerError_(errorCode, errorMessage, message) {
  const code = String(errorCode || "").trim();
  const text = [
    String(errorMessage || "").trim(),
    String(message || "").trim()
  ].filter(Boolean).join("｜");

  return (
    code === "web_worker_error" ||
    /CalledProcessError/.test(text) ||
    /Kaggle Kernel 執行失敗/.test(text)
  );
}

function readLatestStatuses_(taskIds) {
  const sheet = getStatusSheet_();
  const values = sheet.getDataRange().getDisplayValues();
  if (values.length < 2) return {};

  const headers = values[0];
  const col = {};
  headers.forEach(function(name, index) {
    col[String(name || "").trim()] = index;
  });

  const wanted = {};
  taskIds.forEach(function(id) { wanted[id] = true; });

  const result = {};

  for (let r = 1; r < values.length; r++) {
    const row = values[r];
    const taskId = String(row[col.task_id] || "").trim();
    const stage = String(row[col.stage] || "").trim();

    if (!wanted[taskId] || !stage) continue;
    if (!result[taskId]) result[taskId] = { stages: {} };

    const status = String(row[col.status] || "").trim();
    const errorCode = String(row[col.error_code] || "").trim();
    const errorMessage = String(row[col.error_message] || "").trim();
    const message = String(row[col.message] || "").trim();
    const prior = result[taskId].stages[stage] || null;

    let rootErrorCode = "";
    let rootErrorMessage = "";

    if (status === "error") {
      const generic = isGenericWorkerError_(errorCode, errorMessage, message);

      if (!generic) {
        rootErrorCode = errorCode;
        rootErrorMessage = errorMessage || message;
      } else if (prior && prior.status === "error") {
        rootErrorCode = String(
          prior.root_error_code ||
          (!isGenericWorkerError_(
            prior.error_code,
            prior.error_message,
            prior.message
          ) ? prior.error_code : "")
        ).trim();
        rootErrorMessage = String(
          prior.root_error_message ||
          (!isGenericWorkerError_(
            prior.error_code,
            prior.error_message,
            prior.message
          ) ? (prior.error_message || prior.message) : "")
        ).trim();
      }
    }

    result[taskId].stages[stage] = {
      task_id: taskId,
      stage: stage,
      status: status,
      run_id: String(row[col.run_id] || "").trim(),
      progress: String(row[col.progress] || "").trim(),
      message: message,
      started_at: String(row[col.started_at] || "").trim(),
      finished_at: String(row[col.finished_at] || "").trim(),
      updated_at: String(row[col.updated_at] || "").trim(),
      error_code: errorCode,
      error_message: errorMessage,
      root_error_code: rootErrorCode,
      root_error_message: rootErrorMessage,
      input_revision: String(row[col.input_revision] || "").trim(),
      output_revision: String(row[col.output_revision] || "").trim()
    };
  }

  return result;
}

function taskInfo_(taskId) {
  const cache = CacheService.getScriptCache();
  const cacheKey = "task-info-v5:" + String(taskId || "").trim();
  const cached = cache.get(cacheKey);
  if (cached) {
    try { return JSON.parse(cached); } catch (_) {}
  }

  const sheet = ensureTaskIdentitySchema_();
  const values = sheet.getDataRange().getDisplayValues();

  for (let r = 1; r < values.length; r++) {
    if (String(values[r][0] || "").trim() === taskId) {
      const result = {
        row: r + 1,
        id: taskId,
        course_uid: String(values[r][TASK_COL.course_uid] || "").trim(),
        schedule_status: String(values[r][TASK_COL.schedule_status] || "").trim(),
        original_period: Number(String(values[r][TASK_COL.original_period] || "").replace(/[^0-9]/g, "")) || null,
        original_lesson: String(values[r][TASK_COL.original_lesson] || "").trim(),
        rescheduled_at: String(values[r][TASK_COL.rescheduled_at] || "").trim(),
        schedule_note: String(values[r][TASK_COL.schedule_note] || "").trim(),
        period: Number(String(values[r][1] || "").replace(/[^0-9]/g, "")),
        lesson: String(values[r][2] || "").trim(),
        title: String(values[r][3] || "").trim(),
        youtube_url: String(values[r][4] || "").trim(),
        lecturer: String(values[r][5] || "").trim()
      };
      cache.put(cacheKey, JSON.stringify(result), 21600);
      return result;
    }
  }

  throw new Error("找不到任務：" + taskId);
}

function ensureTaskNamingMetadata_(taskId) {
  let task = taskInfo_(taskId);
  if (String(task.title || "").trim()) return task;

  const url = String(task.youtube_url || "").trim();
  if (!url) return task;

  try {
    const endpoint =
      "https://www.youtube.com/oembed?format=json&url=" +
      encodeURIComponent(url);
    const response = UrlFetchApp.fetch(endpoint, {
      muteHttpExceptions: true,
      followRedirects: true
    });
    if (response.getResponseCode() < 200 || response.getResponseCode() >= 300) {
      return task;
    }

    const payload = JSON.parse(response.getContentText() || "{}");
    const title = String(payload.title || "").trim();
    if (!title) return task;

    const parts = title.split(/[|｜丨]/)
      .map(function(x) { return String(x || "").trim(); })
      .filter(Boolean);
    const lecturer = String(
      parts.length >= 2
        ? parts[1]
        : (payload.author_name || task.lecturer || "")
    ).trim();

    const sheet = getSheetByName_(TASK_SHEET_NAME);
    sheet.getRange(task.row, 4).setValue(title);
    if (lecturer) sheet.getRange(task.row, 6).setValue(lecturer);

    CacheService.getScriptCache().remove(
      "task-info-v5:" + String(taskId || "").trim()
    );
    task = taskInfo_(taskId);
    return task;
  } catch (_) {
    return task;
  }
}


function periodFolderId_(period) {
  const cache = CacheService.getScriptCache();
  const targetPeriod = Number(period);
  const cacheKey = "period-folder-v3:" + String(targetPeriod);
  const cached = cache.get(cacheKey);
  if (cached) return cached;

  const periodSheet = getSheetByName_(PERIOD_SHEET_NAME);
  const rows = periodSheet.getDataRange().getDisplayValues();

  for (let r = 1; r < rows.length; r++) {
    // 不可把「P254」與「第254期」直接串接，否則會變成 254254。
    // 優先以期數代碼欄判斷，期數名稱只作 fallback。
    const codeText = String(rows[r][0] || "").trim();
    const nameText = String(rows[r][1] || "").trim();

    const codeMatch = codeText.match(/(\d+)/);
    const nameMatch = nameText.match(/(\d+)/);
    const codePeriod = codeMatch ? Number(codeMatch[1]) : NaN;
    const namePeriod = nameMatch ? Number(nameMatch[1]) : NaN;

    if (codePeriod !== targetPeriod && namePeriod !== targetPeriod) {
      continue;
    }

    const folderValue = String(rows[r][5] || "").trim();
    const folderMatch =
      folderValue.match(/\/folders\/([A-Za-z0-9_-]+)/) ||
      folderValue.match(/[?&]id=([A-Za-z0-9_-]+)/) ||
      (/^[A-Za-z0-9_-]{10,}$/.test(folderValue)
        ? [folderValue, folderValue]
        : null);

    if (folderMatch && folderMatch[1]) {
      cache.put(cacheKey, folderMatch[1], 21600);
      return folderMatch[1];
    }
  }

  throw new Error(
    "期數設定找不到第" + targetPeriod +
    "期的資料夾 URL，請確認「期數設定」的資料夾URL欄位"
  );
}

function cachedChildFolder_(parent, name) {
  const cache = CacheService.getScriptCache();
  const cacheKey = "folder-id-v2:" + parent.getId() + ":" + name;
  const cachedId = cache.get(cacheKey);

  if (cachedId) {
    try {
      return DriveApp.getFolderById(cachedId);
    } catch (_) {
      cache.remove(cacheKey);
    }
  }

  const iter = parent.getFoldersByName(name);
  if (!iter.hasNext()) throw new Error("找不到資料夾：" + name);
  const folder = iter.next();
  cache.put(cacheKey, folder.getId(), 21600);
  return folder;
}

function lessonNumberFromLabel_(value) {
  const match = String(value || "").match(/(\d+)/);
  return match ? Number(match[1]) : 0;
}

function courseFolderForPeriod_(period) {
  const periodFolder = DriveApp.getFolderById(periodFolderId_(period));
  return cachedChildFolder_(periodFolder, "01_課程");
}

function lessonFolderForPosition_(period, lessonNumber) {
  const courseFolder = courseFolderForPeriod_(period);
  const name =
    String(Number(lessonNumber)).padStart(2, "0") +
    "_第" + Number(lessonNumber) + "堂";
  return {
    course: courseFolder,
    lesson: cachedChildFolder_(courseFolder, name),
    name: name
  };
}

function clearScheduleCaches_(taskIds, positions) {
  const cache = CacheService.getScriptCache();
  (taskIds || []).filter(Boolean).forEach(function(taskId) {
    cache.remove("task-info-v5:" + taskId);
    cache.remove("lesson-folders-v3:" + taskId);
  });

  (positions || []).forEach(function(pos) {
    try {
      const course = courseFolderForPeriod_(pos.period);
      const name =
        String(Number(pos.lesson)).padStart(2, "0") +
        "_第" + Number(pos.lesson) + "堂";
      cache.remove("folder-id-v2:" + course.getId() + ":" + name);
    } catch (_) {}
  });
}

function swapLessonFolderPositions_(oldPeriod, oldLesson, newPeriod, newLesson) {
  ensurePeriodStructure_(oldPeriod);
  ensurePeriodStructure_(newPeriod);

  const source = lessonFolderForPosition_(oldPeriod, oldLesson);
  const destination = lessonFolderForPosition_(newPeriod, newLesson);

  if (source.lesson.getId() === destination.lesson.getId()) return;

  const token = Utilities.getUuid().replace(/-/g, "").slice(0, 12);
  const sourceTemp = "__SOULKEY_MOVE_A_" + token;
  const destinationTemp = "__SOULKEY_MOVE_B_" + token;

  let sourceRenamed = false;
  let destinationRenamed = false;
  try {
    source.lesson.setName(sourceTemp);
    sourceRenamed = true;
    destination.lesson.setName(destinationTemp);
    destinationRenamed = true;

    if (source.course.getId() !== destination.course.getId()) {
      source.lesson.moveTo(destination.course);
      destination.lesson.moveTo(source.course);
    }
    source.lesson.setName(destination.name);
    destination.lesson.setName(source.name);
  } catch (err) {
    // Best-effort rollback. Folder IDs remain intact even when a rename or
    // cross-period move fails halfway.
    try {
      if (source.course.getId() !== destination.course.getId()) {
        source.lesson.moveTo(source.course);
        destination.lesson.moveTo(destination.course);
      }
    } catch (_) {}
    if (sourceRenamed) {
      try { source.lesson.setName(source.name); } catch (_) {}
    }
    if (destinationRenamed) {
      try { destination.lesson.setName(destination.name); } catch (_) {}
    }
    throw err;
  }
}

function reorderPeriodTasks_(period, orderedTaskIds) {
  period = Number(period || 0);
  orderedTaskIds = (orderedTaskIds || []).map(function(x) {
    return String(x || "").trim();
  }).filter(Boolean);

  if (!period || !orderedTaskIds.length) {
    throw new Error("期內排序需要 period 與 ordered_task_ids");
  }
  if (new Set(orderedTaskIds).size !== orderedTaskIds.length) {
    throw new Error("期內排序包含重複課程");
  }

  const lock = LockService.getScriptLock();
  lock.waitLock(30000);

  try {
    const sheet = ensureTaskIdentitySchema_();
    const rowCount = Math.max(0, sheet.getLastRow() - 1);
    const values = rowCount
      ? sheet.getRange(2, 1, rowCount, TASK_TOTAL_COLUMNS).getValues()
      : [];

    const periodItems = [];
    values.forEach(function(row, index) {
      const rowPeriod = Number(String(row[1] || "").replace(/[^0-9]/g, ""));
      const status = String(row[TASK_COL.schedule_status] || "").trim();
      const id = String(row[0] || "").trim();
      const lesson = lessonNumberFromLabel_(row[2]);
      if (id && rowPeriod === period && status !== "已取消" && lesson) {
        periodItems.push({
          id: id,
          rowIndex: index,
          lesson: lesson,
          row: row.slice()
        });
      }
    });

    periodItems.sort(function(a, b) { return a.lesson - b.lesson; });

    const existingIds = periodItems.map(function(x) { return x.id; }).sort();
    const requestedIds = orderedTaskIds.slice().sort();
    if (
      existingIds.length !== requestedIds.length ||
      existingIds.join("|") !== requestedIds.join("|")
    ) {
      throw new Error(
        "新順序必須包含第" + period + "期目前全部課程，不能缺少或加入其他期課程"
      );
    }

    const currentOrder = periodItems.map(function(x) { return x.id; });
    if (currentOrder.join("|") === orderedTaskIds.join("|")) {
      return {
        ok: true,
        period: period,
        changed: false,
        ordered_task_ids: orderedTaskIds,
        message: "課程順序沒有變更"
      };
    }

    const courseFolder = courseFolderForPeriod_(period);
    const byId = {};
    const foldersByTask = {};
    periodItems.forEach(function(item) {
      byId[item.id] = item;
      const folderName =
        String(item.lesson).padStart(2, "0") + "_第" + item.lesson + "堂";
      foldersByTask[item.id] = cachedChildFolder_(courseFolder, folderName);
    });

    const token = Utilities.getUuid().replace(/-/g, "").slice(0, 12);
    const originalNames = {};
    const renamedToTemp = [];

    try {
      // Phase 1: free every lesson name in one pass. Folder IDs and contents
      // stay untouched; only the names under the same parent change.
      periodItems.forEach(function(item, index) {
        const folder = foldersByTask[item.id];
        originalNames[item.id] = folder.getName();
        folder.setName(
          "__SOULKEY_REORDER_" + token + "_" + String(index + 1).padStart(2, "0")
        );
        renamedToTemp.push(item.id);
      });

      const timestamp = nowText_();
      const updatedRows = [];

      // Phase 2: assign the requested schedule in the sheet.
      orderedTaskIds.forEach(function(taskId, positionIndex) {
        const item = byId[taskId];
        const newLesson = positionIndex + 1;
        const oldLesson = item.lesson;
        const row = item.row.slice();

        row[1] = period;
        row[2] = "第" + newLesson + "堂";
        row[TASK_COL.schedule_status] =
          oldLesson === newLesson ? (row[TASK_COL.schedule_status] || "已排定") : "已調課";
        if (oldLesson !== newLesson) {
          row[TASK_COL.rescheduled_at] = timestamp;
          row[TASK_COL.schedule_note] =
            "第" + period + "期整批排序：第" + oldLesson +
            "堂 → 第" + newLesson + "堂";
        }
        row[18] = timestamp;
        updatedRows.push({
          sheetRow: item.rowIndex + 2,
          values: row,
          id: taskId,
          oldLesson: oldLesson,
          newLesson: newLesson
        });
      });

      updatedRows.forEach(function(item) {
        sheet.getRange(item.sheetRow, 1, 1, TASK_TOTAL_COLUMNS)
          .setValues([item.values]);
      });

      // Phase 3: map the exact same lesson folders to their new slot names.
      orderedTaskIds.forEach(function(taskId, positionIndex) {
        const newLesson = positionIndex + 1;
        foldersByTask[taskId].setName(
          String(newLesson).padStart(2, "0") + "_第" + newLesson + "堂"
        );
      });

      clearScheduleCaches_(
        orderedTaskIds,
        orderedTaskIds.map(function(_, index) {
          return {period: period, lesson: index + 1};
        })
      );

      // Formal filenames are updated once per moved course, after the schedule
      // is already final. This is much faster than chaining pairwise swaps.
      const renamed = [];
      updatedRows.forEach(function(item) {
        if (item.oldLesson === item.newLesson) return;
        try {
          renamed.push(migrateOneLessonFormalNames_(item.id));
        } catch (err) {
          renamed.push({
            task_id: item.id,
            warning: String(err && err.message ? err.message : err)
          });
        }
      });

      return {
        ok: true,
        period: period,
        changed: true,
        previous_order: currentOrder,
        ordered_task_ids: orderedTaskIds,
        moved_count: updatedRows.filter(function(x) {
          return x.oldLesson !== x.newLesson;
        }).length,
        renamed: renamed,
        message:
          "第" + period + "期排序完成：" +
          orderedTaskIds.map(function(id, i) {
            return "第" + (i + 1) + "堂=" + id;
          }).join("、")
      };

    } catch (err) {
      // Restore both sheet rows and folder names. No file bytes are touched.
      periodItems.forEach(function(item) {
        try {
          sheet.getRange(item.rowIndex + 2, 1, 1, TASK_TOTAL_COLUMNS)
            .setValues([item.row]);
        } catch (_) {}
      });

      renamedToTemp.forEach(function(taskId) {
        try {
          foldersByTask[taskId].setName(originalNames[taskId]);
        } catch (_) {}
      });

      clearScheduleCaches_(
        orderedTaskIds,
        periodItems.map(function(item) {
          return {period: period, lesson: item.lesson};
        })
      );

      throw new Error(
        "第" + period + "期整批排序失敗，已嘗試復原：" +
        String(err && err.message ? err.message : err)
      );
    }
  } finally {
    lock.releaseLock();
  }
}


function rescheduleTask_(taskId, newPeriod, newLesson) {
  const normalizedId = String(taskId || "").trim();
  newPeriod = Number(newPeriod || 0);
  newLesson = Number(newLesson || 0);

  if (!normalizedId || !newPeriod || !newLesson) {
    throw new Error("調課需要 task_id、新期數與新堂次");
  }

  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const sheet = ensureTaskIdentitySchema_();
    const values = sheet.getRange(
      2, 1, Math.max(0, sheet.getLastRow() - 1), TASK_TOTAL_COLUMNS
    ).getValues();

    let sourceIndex = -1;
    let destinationIndex = -1;

    for (let i = 0; i < values.length; i++) {
      const rowId = String(values[i][0] || "").trim();
      if (rowId === normalizedId) sourceIndex = i;

      const p = Number(String(values[i][1] || "").replace(/[^0-9]/g, ""));
      const l = lessonNumberFromLabel_(values[i][2]);
      const scheduleStatus = String(values[i][TASK_COL.schedule_status] || "").trim();
      if (
        rowId && rowId !== normalizedId &&
        p === newPeriod && l === newLesson &&
        scheduleStatus !== "已取消"
      ) {
        destinationIndex = i;
      }
    }

    if (sourceIndex < 0) throw new Error("找不到要調整的課程：" + normalizedId);

    const sourceRow = values[sourceIndex].slice();
    const oldPeriod = Number(String(sourceRow[1] || "").replace(/[^0-9]/g, ""));
    const oldLesson = lessonNumberFromLabel_(sourceRow[2]);
    if (!oldPeriod || !oldLesson) throw new Error("原課程期數／堂次不完整");

    if (oldPeriod === newPeriod && oldLesson === newLesson) {
      return {
        ok: true,
        task_id: normalizedId,
        course_uid: String(sourceRow[TASK_COL.course_uid] || ""),
        changed: false,
        message: "課程已經在指定位置"
      };
    }

    const destinationRow =
      destinationIndex >= 0 ? values[destinationIndex].slice() : null;
    const destinationTaskId =
      destinationRow ? String(destinationRow[0] || "").trim() : "";

    const timestamp = nowText_();
    const sourceHistory =
      "由第" + oldPeriod + "期第" + oldLesson + "堂 → " +
      "第" + newPeriod + "期第" + newLesson + "堂";

    sourceRow[1] = newPeriod;
    sourceRow[2] = "第" + newLesson + "堂";
    sourceRow[TASK_COL.schedule_status] = "已調課";
    sourceRow[TASK_COL.rescheduled_at] = timestamp;
    sourceRow[TASK_COL.schedule_note] = sourceHistory;
    sourceRow[18] = timestamp;

    if (destinationRow) {
      const destinationHistory =
        "因 " + normalizedId + " 調課交換：由第" +
        newPeriod + "期第" + newLesson + "堂 → 第" +
        oldPeriod + "期第" + oldLesson + "堂";
      destinationRow[1] = oldPeriod;
      destinationRow[2] = "第" + oldLesson + "堂";
      destinationRow[TASK_COL.schedule_status] = "已調課";
      destinationRow[TASK_COL.rescheduled_at] = timestamp;
      destinationRow[TASK_COL.schedule_note] = destinationHistory;
      destinationRow[18] = timestamp;
    }

    // Write schedule first, then move the whole lesson folders. If Drive fails,
    // restore the original sheet rows so there is never a silent mismatch.
    sheet.getRange(sourceIndex + 2, 1, 1, TASK_TOTAL_COLUMNS).setValues([sourceRow]);
    if (destinationRow) {
      sheet.getRange(destinationIndex + 2, 1, 1, TASK_TOTAL_COLUMNS)
        .setValues([destinationRow]);
    }

    clearScheduleCaches_(
      [normalizedId, destinationTaskId],
      [
        {period: oldPeriod, lesson: oldLesson},
        {period: newPeriod, lesson: newLesson}
      ]
    );

    try {
      swapLessonFolderPositions_(oldPeriod, oldLesson, newPeriod, newLesson);
    } catch (err) {
      sheet.getRange(sourceIndex + 2, 1, 1, TASK_TOTAL_COLUMNS)
        .setValues([values[sourceIndex]]);
      if (destinationIndex >= 0) {
        sheet.getRange(destinationIndex + 2, 1, 1, TASK_TOTAL_COLUMNS)
          .setValues([values[destinationIndex]]);
      }
      clearScheduleCaches_(
        [normalizedId, destinationTaskId],
        [
          {period: oldPeriod, lesson: oldLesson},
          {period: newPeriod, lesson: newLesson}
        ]
      );
      throw new Error(
        "Drive 課程資料夾移動失敗，控制表已自動復原：" +
        String(err && err.message ? err.message : err)
      );
    }

    clearScheduleCaches_(
      [normalizedId, destinationTaskId],
      [
        {period: oldPeriod, lesson: oldLesson},
        {period: newPeriod, lesson: newLesson}
      ]
    );

    // Renaming is non-destructive and keeps every Drive file ID.
    const renamed = [];
    [normalizedId, destinationTaskId].filter(Boolean).forEach(function(id) {
      try { renamed.push(migrateOneLessonFormalNames_(id)); } catch (_) {}
    });

    return {
      ok: true,
      task_id: normalizedId,
      course_uid: String(sourceRow[TASK_COL.course_uid] || ""),
      changed: true,
      old_period: oldPeriod,
      old_lesson: "第" + oldLesson + "堂",
      new_period: newPeriod,
      new_lesson: "第" + newLesson + "堂",
      swapped_with: destinationTaskId || null,
      renamed: renamed,
      message: destinationTaskId
        ? "調課完成，已與 " + destinationTaskId + " 交換"
        : "調課完成"
    };
  } finally {
    lock.releaseLock();
  }
}

function lessonFolders_(taskId) {
  // task_id is a stable legacy execution key. Schedule position must always
  // come from the control sheet so a rescheduled course does not jump back to
  // the slot encoded in P255-L03.
  const task = taskInfo_(taskId);
  const lessonNumber = Number(String(task.lesson || "").replace(/[^0-9]/g, ""));
  if (!task.period || !lessonNumber) {
    throw new Error("任務缺少目前期數或堂次：" + taskId);
  }

  const cache = CacheService.getScriptCache();
  const cacheKey = "lesson-folders-v3:" + String(taskId || "").trim();
  const cached = cache.get(cacheKey);

  if (cached) {
    try {
      const ids = JSON.parse(cached);
      return {
        task: task,
        lesson: DriveApp.getFolderById(ids.lesson),
        source: DriveApp.getFolderById(ids.source),
        transcript: DriveApp.getFolderById(ids.transcript),
        translation: DriveApp.getFolderById(ids.translation)
      };
    } catch (_) {
      cache.remove(cacheKey);
    }
  }

  const periodFolder = DriveApp.getFolderById(periodFolderId_(task.period));
  const courseFolder = cachedChildFolder_(periodFolder, "01_課程");
  const lessonFolder = cachedChildFolder_(
    courseFolder,
    String(lessonNumber).padStart(2, "0") + "_第" + lessonNumber + "堂"
  );
  const source = cachedChildFolder_(lessonFolder, "00_來源資訊");
  const transcript = cachedChildFolder_(lessonFolder, "01_中文逐字稿");
  const translation = cachedChildFolder_(lessonFolder, "02_翻譯稿");

  cache.put(
    cacheKey,
    JSON.stringify({
      lesson: lessonFolder.getId(),
      source: source.getId(),
      transcript: transcript.getId(),
      translation: translation.getId()
    }),
    21600
  );

  return {
    task: task,
    lesson: lessonFolder,
    source: source,
    transcript: transcript,
    translation: translation
  };
}

function youtubeCaptureFiles_(taskId) {
  const normalizedTaskId = String(taskId || "").trim();
  if (!normalizedTaskId) {
    return {
      ok: false,
      task_id: normalizedTaskId,
      error: "missing_task_id",
      message: "缺少 task_id",
      cc_files: [],
      audio_files: []
    };
  }

  const task = ensureTaskNamingMetadata_(normalizedTaskId);
  const lessonNumber = Number(String(task.lesson || "").replace(/[^0-9]/g, ""));
  const resolved = lessonFolders_(normalizedTaskId);
  const lessonFolder = resolved.lesson;
  const sourceFolder = resolved.source;
  const transcriptFolder = resolved.transcript;
  const audioFolder = cachedChildFolder_(lessonFolder, "04_音檔");

  function fileInfo_(file, kind) {
    const name = String(file.getName() || "");
    const canonical =
      canonicalFromDescription_(file.getDescription()) ||
      (formalizableCanonicalName_(name) ? name : "");
    return {
      kind: kind,
      id: file.getId(),
      name: name,
      display_name:
        canonical && String(task.title || "").trim()
          ? formalDriveName_(normalizedTaskId, canonical)
          : name,
      url: file.getUrl(),
      size: Number(file.getSize() || 0),
      updated_at: file.getLastUpdated()
        ? file.getLastUpdated().toISOString()
        : ""
    };
  }

  const ccFiles = [];
  const sourceFiles = sourceFolder.getFiles();
  while (sourceFiles.hasNext()) {
    const file = sourceFiles.next();
    const name = String(file.getName() || "");
    if (
      (
        /^youtube\.[^.]+\.(json|txt|srt|transcript\.txt)$/i.test(name) &&
        !/^youtube\.zh(?:-|\.)/i.test(name)
      ) ||
      /_(英文|泰文|西班牙文|印尼文|越南文|信德文|泰米爾文|日文|韓文)CC(資料\.json|時間軸\.txt|純逐字稿\.txt|字幕\.srt)$/i.test(name)
    ) {
      ccFiles.push(fileInfo_(file, "cc"));
    }
  }

  const asrFiles = [];
  const transcriptFiles = transcriptFolder.getFiles();
  const asrNames = {
    "segments.json": true,
    "zh-TW.txt": true,
    "zh-TW.transcript.txt": true,
    "zh-TW.srt": true
  };
  while (transcriptFiles.hasNext()) {
    const file = transcriptFiles.next();
    const name = String(file.getName() || "");
    if (
      asrNames[name] ||
      /_(中文ASR資料\.json|中文ASR時間軸\.txt|中文純逐字稿\.txt|中文ASR字幕\.srt)$/i.test(name)
    ) {
      asrFiles.push(fileInfo_(file, "asr"));
    }
  }

  const audioFiles = [];
  const audioIter = audioFolder.getFiles();
  while (audioIter.hasNext()) {
    const file = audioIter.next();
    const name = String(file.getName() || "");
    if (
      /^youtube\..+\.mp3$/i.test(name) ||
      name === "youtube-audio-manifest.json" ||
      /_(中文|英文|泰文|西班牙文|印尼文|越南文|信德文|泰米爾文|日文|韓文)YouTube音軌\.mp3$/i.test(name) ||
      /_YouTube音軌清單\.json$/i.test(name)
    ) {
      audioFiles.push(fileInfo_(file, "audio"));
    }
  }

  function byName_(a, b) {
    return String(a.name || "").localeCompare(String(b.name || ""));
  }
  ccFiles.sort(byName_);
  asrFiles.sort(byName_);
  audioFiles.sort(byName_);

  return {
    ok: true,
    task_id: normalizedTaskId,
    period: Number(task.period || 0),
    lesson: "第" + lessonNumber + "堂",
    source_folder_url:
      "https://drive.google.com/drive/folders/" + sourceFolder.getId(),
    transcript_folder_url:
      "https://drive.google.com/drive/folders/" + transcriptFolder.getId(),
    audio_folder_url:
      "https://drive.google.com/drive/folders/" + audioFolder.getId(),
    cc_files: ccFiles,
    asr_files: asrFiles,
    audio_files: audioFiles,
    server_time: new Date().toISOString()
  };
}


function courseFilesOverview_(taskId) {
  const normalizedTaskId = String(taskId || "").trim();
  if (!normalizedTaskId) {
    return {
      ok: false,
      task_id: normalizedTaskId,
      error: "missing_task_id",
      message: "缺少 task_id",
      groups: [],
      total_files: 0
    };
  }

  const task = ensureTaskNamingMetadata_(normalizedTaskId);
  const resolved = lessonFolders_(normalizedTaskId);
  const lessonFolder = resolved.lesson;
  const audioFolder = cachedChildFolder_(lessonFolder, "04_音檔");
  const videoFolder = cachedChildFolder_(lessonFolder, "05_完成影片");

  function fileInfo_(file, groupKey, groupLabel) {
    const actualName = String(file.getName() || "");
    const canonical =
      canonicalFromDescription_(file.getDescription()) ||
      (formalizableCanonicalName_(actualName) ? actualName : "");
    const displayName =
      canonical && String(task.title || "").trim()
        ? formalDriveName_(normalizedTaskId, canonical)
        : actualName;

    return {
      id: file.getId(),
      name: actualName,
      canonical_name: canonical,
      display_name: displayName,
      url: file.getUrl(),
      size: Number(file.getSize() || 0),
      updated_at: file.getLastUpdated()
        ? file.getLastUpdated().toISOString()
        : "",
      group_key: groupKey,
      group_label: groupLabel
    };
  }

  function collectFolder_(folder, groupKey, groupLabel) {
    const out = [];
    const iter = folder.getFiles();
    while (iter.hasNext()) {
      out.push(fileInfo_(iter.next(), groupKey, groupLabel));
    }
    return out;
  }

  function canonicalName_(item) {
    return String(item.canonical_name || item.name || "").trim();
  }

  function transcriptChoice_(items, language) {
    const lang = String(language || "").trim();
    const candidates = [];

    items.forEach(function(item) {
      const name = canonicalName_(item);
      let priority = 0;

      if (lang === "zh-TW") {
        if (name === "zh-TW.final.txt") priority = 100;
        else if (name === "zh-TW.readable.txt") priority = 80;
        else if (name === "zh-TW.transcript.txt") priority = 60;
      } else if (lang === "en") {
        if (name === "en.final.txt") priority = 100;
        else if (name === "en.txt") priority = 80;
        else if (name === "youtube.en.transcript.txt") priority = 60;
      } else {
        if (name === lang + ".final.txt") priority = 100;
        else if (name === lang + ".txt") priority = 80;
      }

      if (priority) {
        candidates.push({priority: priority, item: item});
      }
    });

    candidates.sort(function(a, b) {
      if (b.priority !== a.priority) return b.priority - a.priority;
      return String(b.item.updated_at || "").localeCompare(
        String(a.item.updated_at || "")
      );
    });

    return candidates.length ? candidates[0].item : null;
  }

  // File overview is intentionally a deliverables view, not a raw Drive browser.
  // JSON / manifests / checkpoints / QA / WAV / ZIP / SRT / intermediate
  // timeline files remain in Drive for the pipeline but are hidden here.
  const transcriptPool = []
    .concat(collectFolder_(resolved.source, "transcript", "逐字稿"))
    .concat(collectFolder_(resolved.transcript, "transcript", "逐字稿"))
    .concat(collectFolder_(resolved.translation, "transcript", "逐字稿"));

  const transcriptLanguages = ["zh-TW", "en", "th", "es", "id", "vi", "hi", "ta", "ja", "ko"];
  const transcriptFiles = transcriptLanguages
    .map(function(lang) { return transcriptChoice_(transcriptPool, lang); })
    .filter(Boolean);

  const audioPool = collectFolder_(audioFolder, "audio", "音檔")
    .filter(function(item) {
      const name = canonicalName_(item);
      return /\.mp3$/i.test(name || item.name || "");
    });

  function audioBaseLang_(name) {
    const value = String(name || "").trim();
    let m = /^([A-Za-z-]+)\.preview\.mp3$/i.exec(value);
    if (m) return String(m[1] || "").toLowerCase().split("-")[0];
    m = /^youtube\.([A-Za-z-]+)\.mp3$/i.exec(value);
    if (m) return String(m[1] || "").toLowerCase().split("-")[0];
    m = /^([A-Za-z-]+)\.mp3$/i.exec(value);
    if (m) return String(m[1] || "").toLowerCase().split("-")[0];
    return "";
  }

  function audioChoice_(items, lang) {
    const wanted = String(lang || "").toLowerCase().split("-")[0];
    const candidates = [];

    items.forEach(function(item) {
      const name = canonicalName_(item);
      if (audioBaseLang_(name) !== wanted) return;

      let priority = 0;
      if (/^[A-Za-z-]+\.mp3$/i.test(name)) priority = 100;
      else if (/^youtube\.[A-Za-z-]+\.mp3$/i.test(name)) priority = 40;

      if (priority) {
        candidates.push({priority: priority, item: item});
      }
    });

    candidates.sort(function(a, b) {
      if (b.priority !== a.priority) return b.priority - a.priority;
      return String(b.item.updated_at || "").localeCompare(
        String(a.item.updated_at || "")
      );
    });

    return candidates.length ? candidates[0].item : null;
  }

  const audioLanguages = ["en", "th", "es", "id", "vi", "hi", "ta", "ja", "ko"];
  const canonicalAudioFiles = audioLanguages
    .map(function(lang) { return audioChoice_(audioPool, lang); })
    .filter(Boolean);

  // Show one preferred MP3 per language. If a natural narration did not
  // fit the source video, expose its FULL preview rather than showing no file.
  // When canonical audio exists, hide the redundant preview from the overview
  // (never delete it from Drive or silently claim the preview is time-aligned).
  const formalLangs = {};
  canonicalAudioFiles.forEach(function(file) {
    const name = canonicalName_(file);
    if (/^[A-Za-z-]+\.mp3$/i.test(name)) {
      formalLangs[audioBaseLang_(name)] = true;
    }
  });
  const previewAudioFiles = audioLanguages
    .filter(function(lang) { return !formalLangs[lang]; })
    .map(function(lang) {
      const item=audioPool.find(function(file) {
        return canonicalName_(file) === lang + ".preview.mp3";
      });
      if (!item) return null;
      return Object.assign({},item,{
        display_name: formalLangLabel_(lang) +
          "自然語音完整版（尚未完成影片對時）.mp3",
        needs_timing_review: true
      });
    })
    .filter(Boolean);

  const audioFiles = canonicalAudioFiles.concat(previewAudioFiles);

  const videoFiles = collectFolder_(videoFolder, "video", "完成影片")
    .filter(function(item) {
      const name = canonicalName_(item);
      return /\.(mp4|mkv|webm)$/i.test(name || item.name || "");
    });

  function sortFiles_(files) {
    files.sort(function(a, b) {
      return String(a.display_name || a.name || "")
        .localeCompare(String(b.display_name || b.name || ""));
    });
    return files;
  }

  const groups = [
    {
      key: "transcript",
      label: "逐字稿",
      folder_url: "",
      files: sortFiles_(transcriptFiles)
    },
    {
      key: "audio",
      label: "音檔",
      folder_url:
        "https://drive.google.com/drive/folders/" + audioFolder.getId(),
      files: sortFiles_(audioFiles)
    },
    {
      key: "video",
      label: "完成影片",
      folder_url:
        "https://drive.google.com/drive/folders/" + videoFolder.getId(),
      files: sortFiles_(videoFiles)
    }
  ];

  const totalFiles = groups.reduce(function(total, group) {
    return total + group.files.length;
  }, 0);

  return {
    ok: true,
    task_id: normalizedTaskId,
    lesson_folder_url:
      "https://drive.google.com/drive/folders/" + lessonFolder.getId(),
    total_files: totalFiles,
    groups: groups,
    server_time: new Date().toISOString()
  };
}

function formalizableCanonicalName_(name) {
  const value = String(name || "").trim();
  if (!value) return false;

  const fixed = {
    "source_info.json": true,
    "segments.json": true,
    "zh-TW.txt": true,
    "zh-TW.transcript.txt": true,
    "zh-TW.srt": true,
    "zh-TW.polished.json": true,
    "zh-TW.polished.txt": true,
    "zh-TW.polished.srt": true,
    "zh-TW.readable.txt": true,
    "polish_report.json": true,
    "zh-TW.final.json": true,
    "zh-TW.final.txt": true,
    "zh-TW.final.srt": true,
    "zh-TW.vernacular.json": true,
    "zh-TW.vernacular.txt": true,
    "zh-TW.vernacular.srt": true,
    "zh-TW.vernacular.final.json": true,
    "zh-TW.vernacular.final.txt": true,
    "zh-TW.vernacular.final.srt": true,
    "youtube-audio-manifest.json": true,
    "subtitle_manifest.json": true,
    "gemini.qa.json": true,
    "gemini-shadow-checkpoint.json": true,
    "zh-TW.review.manifest.json": true
  };
  if (fixed[value]) return true;

  return (
    /^youtube\.[^.]+\.(json|txt|srt|mp3)$/.test(value) ||
    /^youtube\.[^.]+\.transcript\.txt$/.test(value) ||
    /^[A-Za-z-]+\.final\.(json|txt|srt)$/.test(value) ||
    /^[A-Za-z-]+\.(json|txt|srt|mp3|wav)$/.test(value) ||
    /^[A-Za-z-]+\.tts_manifest\.json$/.test(value) ||
    /^[A-Za-z-]+\.segments\.zip$/.test(value) ||
    /^zh-TW\.review\.\d+\.json$/.test(value) ||
    /\.(mp4|mkv|webm)$/i.test(value)
  );
}

function migrateOneLessonFormalNames_(taskId) {
  const folders = lessonFolders_(taskId);
  const folderList = [
    folders.source,
    folders.transcript,
    folders.translation
  ];

  // The current lesson folder comes from the control sheet, not task_id.
  const lessonFolder = folders.lesson;
  ["03_字幕", "04_音檔", "05_完成影片"].forEach(function(name) {
    try { folderList.push(cachedChildFolder_(lessonFolder, name)); } catch (_) {}
  });

  let renamed = 0;
  let marked = 0;
  let skipped = 0;

  folderList.forEach(function(folder) {
    const files = folder.getFiles();
    while (files.hasNext()) {
      const file = files.next();
      const currentName = String(file.getName() || "");
      let canonical = canonicalFromDescription_(file.getDescription());

      if (!canonical) {
        if (!formalizableCanonicalName_(currentName)) {
          skipped += 1;
          continue;
        }
        canonical = currentName;
      }

      const desired = formalDriveName_(taskId, canonical);
      if (currentName !== desired) {
        file.setName(desired);
        renamed += 1;
      }

      const marker = "SOULKEY_CANONICAL_NAME:" + canonical;
      if (String(file.getDescription() || "") !== marker) {
        file.setDescription(marker);
        marked += 1;
      }

      const cacheKey = "file-id-v2:" + folder.getId() + ":" + canonical;
      CacheService.getScriptCache().put(cacheKey, file.getId(), 21600);
    }
  });

  return {
    task_id: taskId,
    renamed: renamed,
    marked: marked,
    skipped: skipped
  };
}

function migrateFormalDriveNames_(taskId) {
  const requested = String(taskId || "").trim();
  const tasks = readTasks_();
  const ids = requested
    ? [requested]
    : tasks.map(function(x) { return String(x.id || x.task_id || "").trim(); })
        .filter(Boolean);

  const results = [];
  let renamed = 0;
  let marked = 0;
  let skipped = 0;

  ids.forEach(function(id) {
    try {
      const item = migrateOneLessonFormalNames_(id);
      results.push(item);
      renamed += Number(item.renamed || 0);
      marked += Number(item.marked || 0);
      skipped += Number(item.skipped || 0);
    } catch (err) {
      results.push({
        task_id: id,
        error: String(err && err.message ? err.message : err)
      });
    }
  });

  return {
    ok: true,
    task_id: requested,
    task_count: ids.length,
    renamed: renamed,
    marked: marked,
    skipped: skipped,
    results: results,
    server_time: new Date().toISOString()
  };
}


function requireFolder_(parent, name) {
  return cachedChildFolder_(parent, name);
}

function formalNameClean_(value, fallback) {
  let text = String(value || "").trim() || String(fallback || "");
  text = text.replace(/[\\/:*?"<>|]+/g, " ");
  text = text.replace(/\s+/g, " ").replace(/^[ ._-]+|[ ._-]+$/g, "");
  return text || String(fallback || "");
}

function formalLangLabel_(code) {
  const labels = {
    "zh-Hant": "中文", "zh-TW": "中文", "zh": "中文",
    "en": "英文", "en-US": "英文", "en-GB": "英文",
    "th": "泰文", "es": "西班牙文", "es-419": "西班牙文",
    "id": "印尼文", "vi": "越南文", "hi": "印地語", "ta": "泰米爾文",
    "ja": "日文", "ko": "韓文"
  };
  const raw = String(code || "");
  return labels[raw] || labels[raw.split("-")[0]] || raw || "未知語言";
}

function formalOutputLabel_(canonicalName) {
  const name = String(canonicalName || "").trim();
  const fixed = {
    "source_info.json": "來源資訊.json",
    "segments.json": "中文ASR資料.json",
    "zh-TW.txt": "中文ASR時間軸.txt",
    "zh-TW.transcript.txt": "中文純逐字稿.txt",
    "zh-TW.srt": "中文ASR字幕.srt",
    "zh-TW.polished.json": "中文潤稿資料.json",
    "zh-TW.polished.txt": "中文潤稿時間軸.txt",
    "zh-TW.polished.srt": "中文潤稿字幕.srt",
    "zh-TW.readable.txt": "中文潤稿純逐字稿.txt",
    "polish_report.json": "中文潤稿報告.json",
    "zh-TW.final.json": "中文人工定稿資料.json",
    "zh-TW.final.txt": "中文人工定稿時間軸.txt",
    "zh-TW.final.srt": "中文人工定稿字幕.srt",
    "zh-TW.vernacular.json": "白話文稿資料.json",
    "zh-TW.vernacular.txt": "白話文稿時間軸.txt",
    "zh-TW.vernacular.srt": "白話文稿字幕.srt",
    "zh-TW.vernacular.final.json": "白話文人工定稿資料.json",
    "zh-TW.vernacular.final.txt": "白話文人工定稿時間軸.txt",
    "zh-TW.vernacular.final.srt": "白話文人工定稿字幕.srt",
    "youtube-audio-manifest.json": "YouTube音軌清單.json",
    "subtitle_manifest.json": "字幕清單.json",
    "gemini.qa.json": "多語翻譯QA報告.json",
    "gemini-shadow-checkpoint.json": "多語翻譯檢查點.json",
    "zh-TW.review.manifest.json": "中文人工校稿清單.json"
  };
  if (fixed[name]) return fixed[name];

  let m = /^youtube\.([^.]+)\.(transcript\.txt|json|txt|srt|mp3)$/.exec(name);
  if (m) {
    const labels = {
      "json": "CC資料.json",
      "txt": "CC時間軸.txt",
      "transcript.txt": "CC純逐字稿.txt",
      "srt": "CC字幕.srt",
      "mp3": "YouTube音軌.mp3"
    };
    return formalLangLabel_(m[1]) + labels[m[2]];
  }

  m = /^([A-Za-z-]+)\.final\.(json|txt|srt)$/.exec(name);
  if (m) {
    const labels = {
      "json": "人工定稿資料.json",
      "txt": "人工定稿時間軸.txt",
      "srt": "人工定稿字幕.srt"
    };
    return formalLangLabel_(m[1]) + labels[m[2]];
  }

  m = /^([A-Za-z-]+)\.(json|txt|srt)$/.exec(name);
  if (m) {
    const labels = {
      "json": "翻譯稿資料.json",
      "txt": "翻譯稿時間軸.txt",
      "srt": "翻譯稿字幕.srt"
    };
    return formalLangLabel_(m[1]) + labels[m[2]];
  }

  m = /^([A-Za-z-]+)\.(mp3|wav)$/.exec(name);
  if (m) return formalLangLabel_(m[1]) + "TTS音檔." + m[2];

  m = /^([A-Za-z-]+)\.tts_manifest\.json$/.exec(name);
  if (m) return formalLangLabel_(m[1]) + "TTS清單.json";

  m = /^([A-Za-z-]+)\.segments\.zip$/.exec(name);
  if (m) return formalLangLabel_(m[1]) + "TTS分段音檔.zip";

  m = /^zh-TW\.review\.(\d+)\.json$/.exec(name);
  if (m) return "中文人工校稿第" + Number(m[1]) + "段.json";

  return formalNameClean_(name, "輸出檔案");
}

function formalDriveName_(taskId, canonicalName) {
  const task = ensureTaskNamingMetadata_(taskId);
  const titleParts = String(task.title || "").split(/[|｜丨]/)
    .map(function(x) { return x.trim(); })
    .filter(Boolean);
  const course = formalNameClean_(titleParts[0] || task.title, "未命名課程");
  const lecturer = formalNameClean_(
    titleParts.length >= 2 ? titleParts[1] : task.lecturer,
    "未標示講師"
  );
  const lessonMatch = String(task.lesson || "").match(/(\d+)/);
  const lesson = lessonMatch ? Number(lessonMatch[1]) : 0;
  return (
    "第" + Number(task.period || 0) + "期_" +
    "第" + lesson + "堂課_" +
    course + "_" + lecturer + "_" +
    formalOutputLabel_(canonicalName)
  );
}

function canonicalFromDescription_(description) {
  const m = /(?:^|\n)SOULKEY_CANONICAL_NAME:([^\n]+)/.exec(String(description || ""));
  return m ? String(m[1] || "").trim() : "";
}

function cachedFileId_(folder, name) {
  const cache = CacheService.getScriptCache();
  const cacheKey = "file-id-v2:" + folder.getId() + ":" + name;
  const cachedId = cache.get(cacheKey);

  if (cachedId) {
    try {
      DriveApp.getFileById(cachedId).getName();
      return cachedId;
    } catch (_) {
      cache.remove(cacheKey);
    }
  }

  const iter = folder.getFilesByName(name);
  if (iter.hasNext()) {
    const file = iter.next();
    cache.put(cacheKey, file.getId(), 21600);
    return file.getId();
  }

  const suffix = "_" + formalOutputLabel_(name);
  const files = folder.getFiles();
  while (files.hasNext()) {
    const file = files.next();
    if (
      canonicalFromDescription_(file.getDescription()) === name ||
      String(file.getName() || "").endsWith(suffix)
    ) {
      cache.put(cacheKey, file.getId(), 21600);
      return file.getId();
    }
  }
  return null;
}

function readJsonFile_(folder, name) {
  const fileId = cachedFileId_(folder, name);
  if (!fileId) return null;

  try {
    return JSON.parse(
      DriveApp.getFileById(fileId).getBlob().getDataAsString("UTF-8")
    );
  } catch (err) {
    // 檔案若被刪除後重建，清掉舊 ID 再找一次。
    const cache = CacheService.getScriptCache();
    const cacheKey = "file-id-v2:" + folder.getId() + ":" + name;
    cache.remove(cacheKey);

    const retryId = cachedFileId_(folder, name);
    if (!retryId) return null;
    return JSON.parse(
      DriveApp.getFileById(retryId).getBlob().getDataAsString("UTF-8")
    );
  }
}

function writeTextFile_(folder, name, content, mimeType, taskId) {
  const cache = CacheService.getScriptCache();
  const cacheKey = "file-id-v2:" + folder.getId() + ":" + name;
  const fileId = cachedFileId_(folder, name);
  const displayName = taskId ? formalDriveName_(taskId, name) : name;
  const description = "SOULKEY_CANONICAL_NAME:" + name;

  if (fileId) {
    try {
      const file = DriveApp.getFileById(fileId);
      file.setContent(content);
      if (taskId) file.setName(displayName);
      file.setDescription(description);
      return;
    } catch (_) {
      cache.remove(cacheKey);
    }
  }

  const file = folder.createFile(
    displayName,
    content,
    mimeType || "text/plain"
  );
  file.setDescription(description);
  cache.put(cacheKey, file.getId(), 21600);
}

function formatPlainTime_(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds || 0)));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map(function(x) { return String(x).padStart(2, "0"); }).join(":");
}

function formatSrtTime_(seconds) {
  const ms = Math.max(0, Math.round(Number(seconds || 0) * 1000));
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  const rem = ms % 1000;
  return String(h).padStart(2, "0") + ":" +
    String(m).padStart(2, "0") + ":" +
    String(s).padStart(2, "0") + "," +
    String(rem).padStart(3, "0");
}

function buildTxt_(segments) {
  return segments.map(function(x) {
    return "[" + formatPlainTime_(x.start) + " - " + formatPlainTime_(x.end) + "] " + x.text;
  }).join("\n") + "\n";
}

function buildSrt_(segments) {
  const out = [];
  segments.forEach(function(x, i) {
    out.push(String(i + 1));
    out.push(formatSrtTime_(x.start) + " --> " + formatSrtTime_(x.end));
    out.push(String(x.text || ""));
    out.push("");
  });
  return out.join("\n");
}

function zhReviewItems_(raw, polished) {
  const rawSegments = (raw && raw.segments) || [];
  const polishedSegments = (polished && polished.segments) || [];
  const uncertain = {};
  ((polished && polished.uncertain) || []).forEach(function(x) {
    uncertain[Number(x.id)] = true;
  });

  return polishedSegments.map(function(x, i) {
    const rawText = rawSegments[i] ? String(rawSegments[i].text || "") : "";
    const flags = [];
    if (rawText !== String(x.text || "")) flags.push("changed");
    if (uncertain[i]) flags.push("uncertain");
    return {
      id: i,
      start: Number(x.start || 0),
      end: Number(x.end || 0),
      time: formatPlainTime_(x.start),
      raw: rawText,
      text: String(x.text || ""),
      flags: flags
    };
  });
}

function englishOverlapTokenKey_(token) {
  return String(token || "")
    .toLowerCase()
    .replace(/^[^a-z0-9]+|[^a-z0-9]+$/g, "");
}

function englishLeadingOverlapCount_(previousText, nextText) {
  const previous = String(previousText || "").replace(/\s+/g, " ").trim().split(" ").filter(Boolean);
  const next = String(nextText || "").replace(/\s+/g, " ").trim().split(" ").filter(Boolean);
  const max = Math.min(previous.length, next.length, 40);

  for (let size = max; size >= 3; size--) {
    const left = previous.slice(previous.length - size).map(englishOverlapTokenKey_);
    const right = next.slice(0, size).map(englishOverlapTokenKey_);
    if (left.some(function(x) { return !x; }) || right.some(function(x) { return !x; })) continue;
    const phrase = left.join(" ");
    if (phrase.length < 12) continue;
    if (phrase === right.join(" ")) return size;
  }
  return 0;
}

function trimLeadingEnglishOverlap_(previousText, nextText) {
  const text = String(nextText || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  const tokens = text.split(" ").filter(Boolean);
  const overlap = englishLeadingOverlapCount_(previousText, text);
  return overlap ? tokens.slice(overlap).join(" ").trim() : text;
}

function mergeEnglishRollingParts_(parts) {
  let merged = "";
  (parts || []).forEach(function(part) {
    const cleaned = trimLeadingEnglishOverlap_(merged, part);
    if (!cleaned) return;
    merged = (merged ? merged + " " : "") + cleaned;
  });
  return merged.replace(/\s+([,.;:!?])/g, "$1").trim();
}

function alignEnglishCcToReviewItems_(items, ccPayload) {
  const cues = (ccPayload && ccPayload.segments) || [];
  if (!Array.isArray(items) || !Array.isArray(cues) || !cues.length) {
    return items || [];
  }

  let englishHistory = "";
  return items.map(function(item) {
    const start = Number(item.start || 0);
    const end = Number(item.end || start);
    const matched = [];
    const seen = {};

    cues.forEach(function(cue) {
      const cueStart = Number(cue.start || 0);
      const cueEnd = Number(cue.end || cueStart);
      if (cueEnd <= start || cueStart >= end) return;
      const text = String(cue.text || "").replace(/\s+/g, " ").trim();
      if (!text || seen[text]) return;
      seen[text] = true;
      matched.push(text);
    });

    const mergedMatched = mergeEnglishRollingParts_(matched);
    const sourceEn = trimLeadingEnglishOverlap_(englishHistory, mergedMatched);
    if (sourceEn) {
      englishHistory = mergeEnglishRollingParts_([englishHistory, sourceEn]);
    }
    return Object.assign({}, item, {
      source_en: sourceEn,
      en_text: sourceEn,
      en_confirmed: item.en_confirmed === true
    });
  });
}


function buildZhReviewManifest_(folder, raw, polished) {
  const chunkSize = 50;
  const items = zhReviewItems_(raw, polished);
  const chunkCount = Math.max(1, Math.ceil(items.length / chunkSize));

  for (let chunkIndex = 1; chunkIndex < chunkCount; chunkIndex++) {
    const start = chunkIndex * chunkSize;
    const chunk = items.slice(start, start + chunkSize);
    writeTextFile_(
      folder,
      "zh-TW.review." + String(chunkIndex).padStart(3, "0") + ".json",
      JSON.stringify({
        version: 1,
        chunk_index: chunkIndex,
        segments: chunk
      }),
      "application/json"
    );
  }

  const manifest = {
    version: 1,
    total_segments: items.length,
    chunk_size: chunkSize,
    chunk_count: chunkCount,
    generated_at: new Date().toISOString(),
    first_chunk: items.slice(0, chunkSize)
  };

  writeTextFile_(
    folder,
    "zh-TW.review.manifest.json",
    JSON.stringify(manifest),
    "application/json"
  );

  return manifest;
}

function loadZhReviewChunk_(folders, taskId, chunkIndex, startedAt) {
  let manifest = readJsonFile_(folders.transcript, "zh-TW.review.manifest.json");

  // 舊任務第一次開啟時，才由既有 ASR + polish_report 建立一次分塊快取。
  if (!manifest || !Array.isArray(manifest.first_chunk)) {
    const raw = readJsonFile_(folders.transcript, "segments.json");
    const polished = readJsonFile_(folders.transcript, "polish_report.json");
    if (!raw || !polished) {
      return {
        ok: false,
        error: "review_files_missing",
        message: "找不到中文校稿檔案"
      };
    }
    manifest = buildZhReviewManifest_(folders.transcript, raw, polished);
  }

  const chunkCount = Math.max(1, Number(manifest.chunk_count || 1));
  const safeIndex = Math.max(0, Math.min(Number(chunkIndex || 0), chunkCount - 1));
  let segments = [];

  if (safeIndex === 0) {
    segments = Array.isArray(manifest.first_chunk) ? manifest.first_chunk : [];
  } else {
    const chunk = readJsonFile_(
      folders.transcript,
      "zh-TW.review." + String(safeIndex).padStart(3, "0") + ".json"
    );
    segments = chunk && Array.isArray(chunk.segments) ? chunk.segments : [];
  }

  return {
    ok: true,
    task_id: taskId,
    kind: "zh",
    load_ms: Date.now() - startedAt,
    chunk_index: safeIndex,
    chunk_count: chunkCount,
    total_segments: Number(manifest.total_segments || segments.length),
    has_more: safeIndex + 1 < chunkCount,
    segments: segments
  };
}

/**
 * English Final groups many short Chinese ASR sentences into one passage.
 * Segment IDs refer to different segmentation schemes and CANNOT be joined
 * one-to-one. Time overlap is authoritative; ID is a legacy fallback only.
 */
function chineseFinalForEnglishTimeRange_(segments, start, end, id) {
  const source = Array.isArray(segments) ? segments : [];
  const begin = Number(start);
  const finish = Number(end);
  if (Number.isFinite(begin) && Number.isFinite(finish) && finish > begin) {
    const matched = source.filter(function(item) {
      const from = Number(item.start || 0);
      const to = Number(item.end !== undefined ? item.end : from);
      return to > begin && from < finish;
    }).map(function(item) {
      return String(item.text || "").trim();
    }).filter(Boolean);
    if (matched.length) return matched.join("");
  }

  const exact = source.find(function(item, index) {
    return Number(item.id !== undefined ? item.id : index) === Number(id);
  });
  return exact ? String(exact.text || "").trim() : "";
}

function loadReview_(taskId, kind, chunkIndex) {
  const startedAt = Date.now();
  if (!taskId) return { ok: false, error: "missing_task_id" };
  const folders = lessonFolders_(taskId);

  if (kind === "zh") {
    return loadZhReviewChunk_(folders, taskId, chunkIndex, startedAt);
  }

  if (kind === "vernacular") {
    const original =
      readJsonFile_(folders.transcript, "zh-TW.final.json") ||
      readJsonFile_(folders.transcript, "polish_report.json");
    const draft = readJsonFile_(folders.translation, "zh-TW.vernacular.json");
    if (!original || !draft) {
      return { ok: false, error: "review_files_missing", message: "找不到白話文校正檔案" };
    }

    const sourceSegments = original.segments || [];
    const draftSegments = draft.segments || [];
    return {
      ok: true,
      task_id: taskId,
      kind: kind,
      load_ms: Date.now() - startedAt,
      segments: draftSegments.map(function(x, i) {
        return {
          id: Number(x.id !== undefined ? x.id : i),
          start: Number(x.start || 0),
          end: Number(x.end || 0),
          time: formatPlainTime_(x.start),
          original: sourceSegments[i] ? String(sourceSegments[i].text || "") : String(x.source_text || ""),
          vernacular: String(x.text || "")
        };
      })
    };
  }

  if (kind === "en") {
    const original = readJsonFile_(folders.transcript, "zh-TW.final.json");
    const englishFinal = readJsonFile_(folders.translation, "en.final.json");
    const englishDraft = readJsonFile_(folders.translation, "en.review.draft.json");
    const english = readJsonFile_(folders.translation, "en.json");
    const youtubeCc = readJsonFile_(folders.source, "youtube.en.json");

    if (!original) {
      return {
        ok: false,
        error: "review_files_missing",
        message: "找不到中文 Final"
      };
    }

    const glossary = getSheetByName_("專有名詞庫").getDataRange().getDisplayValues();
    const terms = glossary.slice(1).map(function(row) {
      return { zh: String(row[0] || "").trim(), en: String(row[3] || "").trim() };
    }).filter(function(x) { return x.zh; });

    const originalSegments = original.segments || [];

    function zhForRange(start, end, id) {
      return chineseFinalForEnglishTimeRange_(originalSegments, start, end, id);
    }

    function termsFor(text) {
      return terms.filter(function(t) {
        return String(text || "").indexOf(t.zh) >= 0;
      });
    }

    if (
      englishFinal &&
      Array.isArray(englishFinal.segments) &&
      englishFinal.segments.length
    ) {
      return {
        ok: true,
        task_id: taskId,
        kind: kind,
        source: "en.final.json",
        finalized_at: String(englishFinal.finalized_at || ""),
        load_ms: Date.now() - startedAt,
        segments: englishFinal.segments.map(function(x, i) {
          const start = Number(x.start || 0);
          const end = Number(x.end || start);
          const id = Number(x.id !== undefined ? x.id : i);
          const zhText = zhForRange(start, end, id);
          return {
            id: id,
            start: start,
            end: end,
            time: formatPlainTime_(start),
            original: zhText,
            vernacular: "",
            en: String(x.text || ""),
            en_confirmed: true,
            terms: termsFor(zhText)
          };
        })
      };
    }

    if (
      englishDraft &&
      Array.isArray(englishDraft.segments) &&
      englishDraft.segments.length
    ) {
      return {
        ok: true,
        task_id: taskId,
        kind: kind,
        source: "en.review.draft.json",
        draft_saved_at: String(englishDraft.draft_saved_at || ""),
        load_ms: Date.now() - startedAt,
        segments: englishDraft.segments.map(function(x, i) {
          const start = Number(x.start || 0);
          const end = Number(x.end || start);
          const id = Number(x.id !== undefined ? x.id : i);
          const zhText = String(x.text || "") || zhForRange(start, end, id);
          return {
            id: id,
            start: start,
            end: end,
            time: String(x.time || formatPlainTime_(start)),
            original: zhText,
            vernacular: "",
            en: String(x.en_text || x.source_en || ""),
            source_en: String(x.source_en || ""),
            en_confirmed: x.en_confirmed === true,
            terms: termsFor(zhText)
          };
        })
      };
    }

    let englishSegments = [];

    if (english && Array.isArray(english.segments) && english.segments.length) {
      englishSegments = english.segments.map(function(x, i) {
        return {
          id: Number(x.id !== undefined ? x.id : i),
          start: Number(x.start || 0),
          end: Number(x.end || 0),
          text: String(x.text || "")
        };
      });
    } else if (youtubeCc && Array.isArray(youtubeCc.segments)) {
      const aligned = alignEnglishCcToReviewItems_(
        originalSegments.map(function(x, i) {
          return {
            id: Number(x.id !== undefined ? x.id : i),
            start: Number(x.start || 0),
            end: Number(x.end || 0),
            text: String(x.text || "")
          };
        }),
        youtubeCc
      );
      englishSegments = aligned.map(function(x) {
        return {
          id: Number(x.id),
          start: Number(x.start || 0),
          end: Number(x.end || 0),
          text: String(x.source_en || "")
        };
      });
    }

    if (!englishSegments.length || !englishSegments.some(function(x) {
      return String(x.text || "").trim();
    })) {
      return {
        ok: false,
        error: "review_files_missing",
        message: "找不到英文 Final、英文草稿、AI 稿或可對齊的 YouTube English CC"
      };
    }

    const englishById = {};
    englishSegments.forEach(function(x, i) {
      englishById[Number(x.id !== undefined ? x.id : i)] = x;
    });

    return {
      ok: true,
      task_id: taskId,
      kind: kind,
      source: english ? "en.json" : "youtube.en.json",
      load_ms: Date.now() - startedAt,
      segments: originalSegments.map(function(src, i) {
        const sid = Number(src.id !== undefined ? src.id : i);
        const x = englishById[sid] || {};
        const zhText = String(src.text || "");
        return {
          id: sid,
          start: Number(src.start || 0),
          end: Number(src.end || 0),
          time: formatPlainTime_(src.start),
          original: zhText,
          vernacular: "",
          en: String(x.text || ""),
          en_confirmed: false,
          terms: termsFor(zhText)
        };
      })
    };
  }

  return { ok: false, error: "unsupported_review_kind" };
}

function saveReview_(taskId, kind, segments, learnedTerms) {
  if (!Array.isArray(segments) || !segments.length) {
    return { ok: false, error: "empty_segments" };
  }

  const folders = lessonFolders_(taskId);
  let normalized = segments.map(function(x, i) {
    return {
      id: Number(x.id !== undefined ? x.id : i),
      start: Number(x.start || 0),
      end: Number(x.end || 0),
      text: String(x.text || "").trim()
    };
  });

  let targetFolder = null;
  let code = "";
  let language = "";
  let statusStage = "";
  let taskColumn = null;

  if (kind === "zh") {
    targetFolder = folders.transcript;
    code = "zh-TW.final";
    language = "Traditional Chinese Final";
    statusStage = "zh";
    taskColumn = 9;
  } else if (kind === "vernacular") {
    targetFolder = folders.translation;
    code = "zh-TW.vernacular.final";
    language = "Traditional Chinese Vernacular Final";
    statusStage = "vernacular-review";
  } else if (kind === "en") {
    targetFolder = folders.translation;
    code = "en.final";
    language = "English Final";
    statusStage = "en-review";
    taskColumn = 10;
  } else {
    return { ok: false, error: "unsupported_review_kind" };
  }

  if (kind === "en") {
    let englishHistory = "";
    normalized = normalized.map(function(item) {
      const cleaned = trimLeadingEnglishOverlap_(englishHistory, item.text);
      if (cleaned) {
        englishHistory = mergeEnglishRollingParts_([englishHistory, cleaned]);
      }
      return Object.assign({}, item, { text: cleaned });
    }).filter(function(item) {
      return !!String(item.text || "").trim();
    });
  }

  const payload = JSON.stringify({
    language: language,
    finalized_at: new Date().toISOString(),
    segments: normalized
  }, null, 2);

  writeTextFile_(targetFolder, code + ".json", payload, "application/json", taskId);
  writeTextFile_(targetFolder, code + ".txt", buildTxt_(normalized), "text/plain", taskId);
  writeTextFile_(targetFolder, code + ".srt", buildSrt_(normalized), "text/plain", taskId);

  const task = taskInfo_(taskId);
  const taskSheet = getSheetByName_(TASK_SHEET_NAME);
  if (taskColumn) {
    taskSheet.getRange(task.row, taskColumn).setValue("完成");
  }
  taskSheet.getRange(task.row, 19).setValue(nowText_());
  taskSheet.getRange(task.row, 20).setValue(
    kind === "zh" ? "中文人工定稿完成" :
    kind === "vernacular" ? "白話文人工定稿完成" :
    "英文人工定稿完成"
  );

  if (kind === "en" && Array.isArray(learnedTerms) && learnedTerms.length) {
    learnEnglishTerms_(learnedTerms);
  }

  appendExecutionStatus_(
    taskId,
    statusStage,
    "done",
    "human-" + new Date().getTime(),
    100,
    "人工定稿完成",
    "",
    nowText_(),
    "",
    "",
    "",
    new Date().toISOString()
  );

  invalidateDownstreamAfterHumanFinal_(taskId, kind);

  if (kind === "zh") {
    // Publish before the user first opens English review; no Kaggle startup.
    // Human English drafts/finals take precedence and are never overwritten.
    try {
      const cache=seedEnglishReviewCache_(taskId);
      if (!cache.ok) Logger.log("Automatic English align pending: "+cache.error);
    } catch (err) {
      Logger.log("Automatic English align deferred: "+String(err));
    }
  }

  if (kind === "en") {
    // Formal Drive files and "done" status are already committed. Publishing
    // GitHub is an optional acceleration, NEVER grounds for save failure.
    try {
      const cache = seedEnglishReviewCache_(taskId);
      if (!cache.ok) Logger.log("English fast cache pending: " + cache.error);
    } catch (err) {
      Logger.log("English fast cache deferred: " + String(err));
    }
  }

  return {
    ok: true,
    task_id: taskId,
    kind: kind,
    segment_count: normalized.length
  };
}

function learnEnglishTerms_(pairs) {
  const sheet = getSheetByName_("專有名詞庫");
  const values = sheet.getDataRange().getValues();
  const rowByZh = {};

  for (let r = 1; r < values.length; r++) {
    const zh = String(values[r][0] || "").trim();
    if (zh) rowByZh[zh] = r + 1;
  }

  pairs.slice(0, 100).forEach(function(pair) {
    const zh = String(pair.zh || "").trim();
    const en = String(pair.en || "").trim();
    if (!zh || !en) return;

    if (rowByZh[zh]) {
      sheet.getRange(rowByZh[zh], 4).setValue(en);
      sheet.getRange(rowByZh[zh], 9).setValue(true);
      sheet.getRange(rowByZh[zh], 10).setValue("由人工英文定稿學習");
    } else {
      sheet.appendRow([
        zh,
        "宗教術語",
        "",
        en,
        "",
        "",
        "",
        "",
        true,
        "由人工英文定稿學習"
      ]);
      rowByZh[zh] = sheet.getLastRow();
    }
  });
}

function bridgeClientHtml_() {
  const html = `
<!doctype html>
<html>
<head><meta charset="utf-8"><title>SoulKey Bridge Client</title></head>
<body>
<script>
(function(){
  function send(payload){
    try { window.parent.postMessage(payload, "*"); } catch (e) {}
  }

  send({source: "soulkey-bridge-client", type: "ready"});

  window.addEventListener("message", function(event){
    var data = event.data || {};
    if (data.source !== "soulkey-studio" || data.type !== "bridge_request") return;

    google.script.run
      .withSuccessHandler(function(result){
        send(result || {
          source: "soulkey-bridge",
          type: "bridge_error",
          ok: false,
          error: "empty_response"
        });
      })
      .withFailureHandler(function(err){
        send({
          source: "soulkey-bridge",
          type: "bridge_error",
          ok: false,
          error: "script_run_failed",
          message: String(err && err.message ? err.message : err)
        });
      })
      .bridgeRequest(data.request || {});
  });
})();
</script>
</body>
</html>`;

  return HtmlService
    .createHtmlOutput(html)
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function responseForAction_(action, payload) {
  const mapped = {
    status: "status_result",
    status_batch: "status_result",
    status_health: "status_health",
    language_settings: "language_settings",
    language_plan_get: "language_plan",
    language_plan_save: "language_plan_saved",
    tasks_upsert: "tasks_saved",
    task_reschedule: "task_rescheduled",
    period_reorder: "period_reordered",
    run_stage: "run_stage",
    review_save: "review_saved",
    review_share_create: "review_share_created",
    youtube_capture_files: "youtube_capture_files",
    drive_names_migrate: "drive_names_migrated"
  };

  if (mapped[action]) {
    payload.source = "soulkey-bridge";
    payload.type = mapped[action];
    return postMessage_(payload);
  }

  return json_(payload);
}

function postMessage_(payload) {
  const safe = JSON.stringify(payload).replace(/</g, "\\u003c");
  const html =
    "<!doctype html><meta charset='utf-8'>" +
    "<body style='font-family:sans-serif;font-size:12px'>" +
    "SoulKey response" +
    "<script>" +
    "(function(){" +
      "var data=" + safe + ";" +
      "try{window.parent.postMessage(data,'*');}catch(e){}" +
      "try{window.top.postMessage(data,'*');}catch(e){}" +
    "})();" +
    "<\/script>" +
    "</body>";

  return HtmlService
    .createHtmlOutput(html)
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function jsonp_(callback, payload) {
  const safeCallback = /^[A-Za-z_$][0-9A-Za-z_$]*(?:\.[A-Za-z_$][0-9A-Za-z_$]*)*$/.test(callback)
    ? callback
    : "";

  if (!safeCallback) {
    return ContentService
      .createTextOutput("/* invalid callback */")
      .setMimeType(ContentService.MimeType.JAVASCRIPT);
  }

  const body = safeCallback + "(" + JSON.stringify(payload).replace(/</g, "\\u003c") + ");";
  return ContentService
    .createTextOutput(body)
    .setMimeType(ContentService.MimeType.JAVASCRIPT);
}

function json_(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
