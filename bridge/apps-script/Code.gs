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

const MACHINE_STAGES = [
  "metadata", "asr", "polish", "vernacular", "en", "multi", "tts"
];
const RUNTIME_TTL_MS = 4 * 60 * 60 * 1000;

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
    "review_load"
  ];

  if (callback && jsonpActions.indexOf(action) >= 0) {
    const request = {
      action: action,
      bridge_key: String((e && e.parameter && e.parameter.bridge_key) || "").trim(),
      task_id: String((e && e.parameter && e.parameter.task_id) || "").trim(),
      task_ids: String((e && e.parameter && e.parameter.task_ids) || "").trim(),
      kind: String((e && e.parameter && e.parameter.kind) || "").trim()
    };
    return jsonp_(callback, bridgeRequest(request));
  }

  return json_({
    ok: true,
    service: "SoulKey Studio Bridge",
    message: "bridge-ready",
    status_sheet: STATUS_SHEET_NAME,
    web_job_workflow: WORKFLOW_WEB_JOB
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

      saveLanguagePlan_(taskId, plan);
      return postMessage_({
        source: "soulkey-bridge",
        type: "language_plan_saved",
        ok: true,
        task_id: taskId,
        plan: readLanguagePlan_(taskId),
        server_time: new Date().toISOString()
      });
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

    if (action === "review_load") {
      const taskId = String(request.task_id || "").trim();
      const kind = String(request.kind || "").trim();
      const payload = loadReview_(taskId, kind);
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
  const token = ScriptApp.getOAuthToken();

  Logger.log("Spreadsheet: " + ss.getName());
  Logger.log("Drive root: " + root.getName());
  Logger.log("OAuth token available: " + (!!token));
}

function createRuntimeJob_(taskId, stage, lang, langs) {
  const bytes = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    Utilities.getUuid() + "|" + Utilities.getUuid() + "|" + new Date().getTime()
  );
  const nonce = Utilities.base64EncodeWebSafe(bytes).replace(/=+$/g, "");

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
    youtube_cookies_b64: String(props.getProperty("YOUTUBE_COOKIES_B64") || ""),
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
  if (["running", "error"].indexOf(normalized) < 0) {
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
    normalized === "running" ? 1 : "",
    message || "",
    normalized === "running" ? nowText_() : "",
    normalized === "error" ? nowText_() : "",
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

function readTasks_() {
  const sheet = getSheetByName_(TASK_SHEET_NAME);
  const values = sheet.getDataRange().getDisplayValues();
  const result = [];

  for (let r = 1; r < values.length; r++) {
    const row = values[r];
    const id = String(row[0] || "").trim();
    if (!id) continue;

    result.push({
      id: id,
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

  const sheet = getSheetByName_(TASK_SHEET_NAME);
  const values = sheet.getDataRange().getValues();
  const byId = {};

  for (let r = 1; r < values.length; r++) {
    const id = String(values[r][0] || "").trim();
    if (id) byId[id] = r + 1;
  }

  const saved = [];

  items.slice(0, 20).forEach(function(item) {
    const id = String(item.id || item.task_id || "").trim();
    const period = Number(item.period || 0);
    const lesson = String(item.lesson || "").trim();
    const url = String(item.url || item.youtube_url || "").trim();
    const note = String(item.note || "").trim();

    if (!id || !period || !lesson || !url) {
      throw new Error("任務缺少 id / period / lesson / url");
    }

    ensurePeriodStructure_(period);

    const existingRow = byId[id] || null;
    let row = existingRow
      ? sheet.getRange(existingRow, 1, 1, 20).getValues()[0]
      : new Array(20).fill("");

    row[0] = id;
    row[1] = period;
    row[2] = lesson;
    row[4] = url;
    row[6] = row[6] || "zh-TW";
    row[18] = nowText_();
    row[19] = note || row[19] || "由 SoulKey Studio 建立";

    if (existingRow) {
      sheet.getRange(existingRow, 1, 1, 20).setValues([row]);
    } else {
      sheet.appendRow(row);
      byId[id] = sheet.getLastRow();
    }

    saved.push({
      id: id,
      period: period,
      lesson: lesson,
      url: url
    });
  });

  return saved;
}

function ensurePeriodStructure_(period) {
  const sheet = getSheetByName_(PERIOD_SHEET_NAME);
  const values = sheet.getDataRange().getValues();

  for (let r = 1; r < values.length; r++) {
    const code = String(values[r][0] || "");
    const name = String(values[r][1] || "");
    const n = Number((code + " " + name).replace(/[^0-9]/g, ""));
    if (n === period && String(values[r][5] || "").trim()) {
      return String(values[r][5]).trim();
    }
  }

  const root = DriveApp.getFolderById(ROOT_DRIVE_FOLDER_ID);
  const periodName = period + "_第" + period + "期";
  const periodFolder = findOrCreateFolder_(root, periodName);

  findOrCreateFolder_(periodFolder, "00_期別設定");
  const courseFolder = findOrCreateFolder_(periodFolder, "01_課程");
  findOrCreateFolder_(periodFolder, "98_人工檢查");
  findOrCreateFolder_(periodFolder, "99_期末封存");

  const subNames = [
    "00_來源資訊",
    "01_中文逐字稿",
    "02_翻譯稿",
    "03_字幕",
    "04_音檔",
    "05_完成影片",
    "99_處理紀錄"
  ];

  for (let i = 1; i <= 4; i++) {
    const lesson = findOrCreateFolder_(
      courseFolder,
      String(i).padStart(2, "0") + "_第" + i + "堂"
    );
    subNames.forEach(function(name) {
      findOrCreateFolder_(lesson, name);
    });
  }

  const url = "https://drive.google.com/drive/folders/" + periodFolder.getId();
  sheet.appendRow([
    "P" + period,
    "第" + period + "期",
    "啟用",
    "",
    "",
    url,
    4,
    "由 SoulKey Studio 自動建立"
  ]);

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

function saveLanguagePlan_(taskId, plan) {
  if (!Array.isArray(plan)) throw new Error("plan 必須是陣列");

  const sheet = getSheetByName_(LANGUAGE_PLAN_SHEET_NAME);
  const values = sheet.getDataRange().getDisplayValues();

  for (let r = values.length - 1; r >= 1; r--) {
    if (String(values[r][0] || "").trim() === taskId) {
      sheet.deleteRow(r + 1);
    }
  }

  const rows = [];
  plan.slice(0, 50).forEach(function(item) {
    const code = String(item.language_code || item.code || "").trim();
    if (!code) return;

    const transcriptEnabled = !!item.transcript_enabled;
    const audioEnabled = !!item.audio_enabled;

    rows.push([
      taskId,
      code,
      String(item.language_name || item.name || code).trim(),
      transcriptEnabled,
      transcriptEnabled ? String(item.transcript_source || "ai").trim() : "skip",
      audioEnabled,
      audioEnabled ? String(item.audio_source || "tts").trim() : "skip",
      "planned",
      nowText_(),
      String(item.note || "").slice(0, 500)
    ]);
  });

  if (rows.length) {
    sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, 10).setValues(rows);
  }
}

function getStatusSheet_() {
  return getSheetByName_(STATUS_SHEET_NAME);
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

    result[taskId].stages[stage] = {
      task_id: taskId,
      stage: stage,
      status: String(row[col.status] || "").trim(),
      run_id: String(row[col.run_id] || "").trim(),
      progress: String(row[col.progress] || "").trim(),
      message: String(row[col.message] || "").trim(),
      started_at: String(row[col.started_at] || "").trim(),
      finished_at: String(row[col.finished_at] || "").trim(),
      updated_at: String(row[col.updated_at] || "").trim(),
      error_code: String(row[col.error_code] || "").trim(),
      error_message: String(row[col.error_message] || "").trim(),
      input_revision: String(row[col.input_revision] || "").trim(),
      output_revision: String(row[col.output_revision] || "").trim()
    };
  }

  return result;
}

function taskInfo_(taskId) {
  const sheet = getSheetByName_(TASK_SHEET_NAME);
  const values = sheet.getDataRange().getDisplayValues();

  for (let r = 1; r < values.length; r++) {
    if (String(values[r][0] || "").trim() === taskId) {
      return {
        row: r + 1,
        id: taskId,
        period: Number(String(values[r][1] || "").replace(/[^0-9]/g, "")),
        lesson: String(values[r][2] || "").trim()
      };
    }
  }

  throw new Error("找不到任務：" + taskId);
}

function lessonFolders_(taskId) {
  const task = taskInfo_(taskId);
  const periodSheet = getSheetByName_(PERIOD_SHEET_NAME);
  const rows = periodSheet.getDataRange().getDisplayValues();

  let periodFolderId = "";
  for (let r = 1; r < rows.length; r++) {
    const num = Number((String(rows[r][0] || "") + String(rows[r][1] || "")).replace(/[^0-9]/g, ""));
    if (num === task.period) {
      const match = String(rows[r][5] || "").match(/folders\/([A-Za-z0-9_-]+)/);
      if (match) periodFolderId = match[1];
      break;
    }
  }

  if (!periodFolderId) throw new Error("期數設定找不到資料夾");

  const periodFolder = DriveApp.getFolderById(periodFolderId);
  const courseFolder = requireFolder_(periodFolder, "01_課程");
  const lessonNumber = Number(String(task.lesson).replace(/[^0-9]/g, ""));
  const lessonFolder = requireFolder_(
    courseFolder,
    String(lessonNumber).padStart(2, "0") + "_第" + lessonNumber + "堂"
  );

  return {
    task: task,
    transcript: requireFolder_(lessonFolder, "01_中文逐字稿"),
    translation: requireFolder_(lessonFolder, "02_翻譯稿")
  };
}

function requireFolder_(parent, name) {
  const iter = parent.getFoldersByName(name);
  if (!iter.hasNext()) throw new Error("找不到資料夾：" + name);
  return iter.next();
}

function readJsonFile_(folder, name) {
  const iter = folder.getFilesByName(name);
  if (!iter.hasNext()) return null;
  return JSON.parse(iter.next().getBlob().getDataAsString("UTF-8"));
}

function writeTextFile_(folder, name, content, mimeType) {
  const iter = folder.getFilesByName(name);
  if (iter.hasNext()) {
    iter.next().setContent(content);
  } else {
    folder.createFile(name, content, mimeType || "text/plain");
  }
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

function loadReview_(taskId, kind) {
  if (!taskId) return { ok: false, error: "missing_task_id" };
  const folders = lessonFolders_(taskId);

  if (kind === "zh") {
    const raw = readJsonFile_(folders.transcript, "segments.json");
    const polished = readJsonFile_(folders.transcript, "polish_report.json");
    if (!raw || !polished) {
      return { ok: false, error: "review_files_missing", message: "找不到中文校稿檔案" };
    }

    const rawSegments = raw.segments || [];
    const polishedSegments = polished.segments || [];
    const uncertain = {};
    (polished.uncertain || []).forEach(function(x) {
      uncertain[Number(x.id)] = true;
    });

    return {
      ok: true,
      task_id: taskId,
      kind: kind,
      segments: polishedSegments.map(function(x, i) {
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
      })
    };
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
    const original =
      readJsonFile_(folders.transcript, "zh-TW.final.json") ||
      readJsonFile_(folders.transcript, "polish_report.json");
    const vernacular =
      readJsonFile_(folders.translation, "zh-TW.vernacular.final.json") ||
      readJsonFile_(folders.translation, "zh-TW.vernacular.json");
    const english = readJsonFile_(folders.translation, "en.json");

    if (!original || !vernacular || !english) {
      return { ok: false, error: "review_files_missing", message: "找不到英文定稿檔案" };
    }

    const glossary = getSheetByName_("專有名詞庫").getDataRange().getDisplayValues();
    const terms = glossary.slice(1).map(function(row) {
      return { zh: String(row[0] || "").trim(), en: String(row[3] || "").trim() };
    }).filter(function(x) { return x.zh; });

    const originalSegments = original.segments || [];
    const vernacularSegments = vernacular.segments || [];
    const englishSegments = english.segments || [];

    return {
      ok: true,
      task_id: taskId,
      kind: kind,
      segments: englishSegments.map(function(x, i) {
        const zhText = originalSegments[i] ? String(originalSegments[i].text || "") : "";
        const pairs = terms.filter(function(t) {
          return zhText.indexOf(t.zh) >= 0;
        });
        return {
          id: Number(x.id !== undefined ? x.id : i),
          start: Number(x.start || 0),
          end: Number(x.end || 0),
          time: formatPlainTime_(x.start),
          original: zhText,
          vernacular: vernacularSegments[i] ? String(vernacularSegments[i].text || "") : "",
          en: String(x.text || ""),
          terms: pairs
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
  const normalized = segments.map(function(x, i) {
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
    statusStage = "review";
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

  const payload = JSON.stringify({
    language: language,
    finalized_at: new Date().toISOString(),
    segments: normalized
  }, null, 2);

  writeTextFile_(targetFolder, code + ".json", payload, "application/json");
  writeTextFile_(targetFolder, code + ".txt", buildTxt_(normalized), "text/plain");
  writeTextFile_(targetFolder, code + ".srt", buildSrt_(normalized), "text/plain");

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
    run_stage: "run_stage",
    review_save: "review_saved"
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
    .setMimeType(ContentService."application/json");
}
