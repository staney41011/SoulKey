const OWNER = "staney41011";
const REPO = "SoulKey";
const WORKFLOW = "kaggle_run_bridge_test.yml";
const REF = "main";

const CONTROL_SHEET_ID = "1AwPqTqZSzW7Q-gLW4J5d-28dQZwVksyDnvsxNRF2uu8";
const STATUS_SHEET_NAME = "執行狀態";
const LANGUAGE_SHEET_NAME = "語言設定";
const LANGUAGE_PLAN_SHEET_NAME = "語言任務設定";

function doGet(e) {
  const view = String((e && e.parameter && e.parameter.view) || "").trim();

  if (view === "client") {
    return bridgeClientHtml_();
  }

  return json_({
    ok: true,
    service: "SoulKey Studio Bridge",
    message: "bridge-ready",
    status_sheet: STATUS_SHEET_NAME
  });
}

function doPost(e) {
  try {
    const props = PropertiesService.getScriptProperties();
    const expectedKey = String(props.getProperty("BRIDGE_KEY") || "").trim();
    const githubToken = String(props.getProperty("GITHUB_TOKEN") || "").trim();

    const action = String((e && e.parameter && e.parameter.action) || "").trim();
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

    if (action === "status_health") {
      const sheet = getStatusSheet_();
      return postMessage_({
        source: "soulkey-bridge",
        type: "status_health",
        ok: true,
        sheet: STATUS_SHEET_NAME,
        rows: Math.max(0, sheet.getLastRow() - 1),
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
      if (!taskId) {
        return postMessage_({
          source: "soulkey-bridge",
          type: "language_plan",
          ok: false,
          error: "missing_task_id"
        });
      }
      return postMessage_({
        source: "soulkey-bridge",
        type: "language_plan",
        ok: true,
        task_id: taskId,
        plan: readLanguagePlan_(taskId),
        server_time: new Date().toISOString()
      });
    }

    if (action === "language_plan_save") {
      const taskId = String((e && e.parameter && e.parameter.task_id) || "").trim();
      const planJson = String((e && e.parameter && e.parameter.plan_json) || "").trim();
      if (!taskId || !planJson) {
        return postMessage_({
          source: "soulkey-bridge",
          type: "language_plan_saved",
          ok: false,
          error: "missing_plan"
        });
      }

      let plan = [];
      try {
        plan = JSON.parse(planJson);
      } catch (err) {
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

    if (action === "status" || action === "status_batch") {
      const raw = String(
        (e && e.parameter && (e.parameter.task_ids || e.parameter.task_id)) || ""
      ).trim();

      const taskIds = raw
        .split(",")
        .map(function(x) { return x.trim(); })
        .filter(function(x) { return x; })
        .slice(0, 20);

      if (!taskIds.length) {
        return postMessage_({
          source: "soulkey-bridge",
          type: "status_result",
          ok: false,
          error: "missing_task_id"
        });
      }

      return postMessage_({
        source: "soulkey-bridge",
        type: "status_result",
        ok: true,
        tasks: readLatestStatuses_(taskIds),
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

function bridgeRequest_(request) {
  try {
    request = request || {};
    const props = PropertiesService.getScriptProperties();
    const expectedKey = String(props.getProperty("BRIDGE_KEY") || "").trim();
    const bridgeKey = String(request.bridge_key || "").trim();
    const action = String(request.action || "").trim();

    if (!expectedKey) {
      return {
        source: "soulkey-bridge",
        type: action === "status_health" ? "status_health" : "status_result",
        ok: false,
        error: "server_not_configured",
        message: "BRIDGE_KEY 尚未設定"
      };
    }

    if (!bridgeKey || bridgeKey !== expectedKey) {
      return {
        source: "soulkey-bridge",
        type: action === "status_health" ? "status_health" : "status_result",
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
        server_time: new Date().toISOString()
      };
    }

    if (action === "status" || action === "status_batch") {
      const raw = String(request.task_ids || request.task_id || "").trim();
      const taskIds = raw
        .split(",")
        .map(function(x) { return x.trim(); })
        .filter(function(x) { return x; })
        .slice(0, 20);

      if (!taskIds.length) {
        return {
          source: "soulkey-bridge",
          type: "status_result",
          ok: false,
          error: "missing_task_id",
          message: "缺少 task_id"
        };
      }

      return {
        source: "soulkey-bridge",
        type: "status_result",
        ok: true,
        tasks: readLatestStatuses_(taskIds),
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
      if (!taskId) {
        return {
          source: "soulkey-bridge",
          type: "language_plan",
          ok: false,
          error: "missing_task_id"
        };
      }

      return {
        source: "soulkey-bridge",
        type: "language_plan",
        ok: true,
        task_id: taskId,
        plan: readLanguagePlan_(taskId),
        server_time: new Date().toISOString()
      };
    }

    if (action === "language_plan_save") {
      const taskId = String(request.task_id || "").trim();
      const planJson = String(request.plan_json || "").trim();

      if (!taskId || !planJson) {
        return {
          source: "soulkey-bridge",
          type: "language_plan_saved",
          ok: false,
          error: "missing_plan"
        };
      }

      let plan = [];
      try {
        plan = JSON.parse(planJson);
      } catch (err) {
        return {
          source: "soulkey-bridge",
          type: "language_plan_saved",
          ok: false,
          error: "invalid_plan_json"
        };
      }

      saveLanguagePlan_(taskId, plan);

      return {
        source: "soulkey-bridge",
        type: "language_plan_saved",
        ok: true,
        task_id: taskId,
        plan: readLanguagePlan_(taskId),
        server_time: new Date().toISOString()
      };
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

function bridgeClientHtml_() {
  const html = `
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>SoulKey Bridge Client</title>
</head>
<body>
<script>
(function(){
  function send(payload){
    try {
      window.parent.postMessage(payload, "*");
    } catch (e) {}
  }

  send({
    source: "soulkey-bridge-client",
    type: "ready"
  });

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
      .bridgeRequest_(data.request || {});
  });
})();
</script>
</body>
</html>`;

  return HtmlService
    .createHtmlOutput(html)
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function dispatchSmoke_(githubToken) {
  const url =
    "https://api.github.com/repos/" + OWNER + "/" + REPO +
    "/actions/workflows/" + encodeURIComponent(WORKFLOW) + "/dispatches";

  const response = UrlFetchApp.fetch(url, {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify({ ref: REF }),
    headers: {
      Authorization: "Bearer " + githubToken,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2026-03-10"
    },
    muteHttpExceptions: true
  });

  const status = response.getResponseCode();

  if (status !== 200 && status !== 204) {
    return json_({
      ok: false,
      error: "github_dispatch_failed",
      github_status: status,
      github_body: response.getContentText().slice(0, 800)
    });
  }

  let githubResult = {};
  const responseText = String(response.getContentText() || "").trim();
  if (responseText) {
    try {
      githubResult = JSON.parse(responseText);
    } catch (_) {
      githubResult = {};
    }
  }

  return json_({
    ok: true,
    action: "smoke",
    message: "GitHub Actions workflow dispatched",
    workflow_run_id: githubResult.workflow_run_id || null,
    html_url: githubResult.html_url || null
  });
}


function getSheetByName_(name) {
  const spreadsheet = SpreadsheetApp.openById(CONTROL_SHEET_ID);
  const sheet = spreadsheet.getSheetByName(name);
  if (!sheet) {
    throw new Error("找不到工作表：" + name);
  }
  return sheet;
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
  if (!Array.isArray(plan)) {
    throw new Error("plan 必須是陣列");
  }

  const sheet = getSheetByName_(LANGUAGE_PLAN_SHEET_NAME);
  const values = sheet.getDataRange().getDisplayValues();

  for (let r = values.length - 1; r >= 1; r--) {
    if (String(values[r][0] || "").trim() === taskId) {
      sheet.deleteRow(r + 1);
    }
  }

  const now = Utilities.formatDate(
    new Date(),
    Session.getScriptTimeZone() || "Asia/Taipei",
    "yyyy-MM-dd HH:mm:ss"
  );

  const rows = [];
  plan.slice(0, 50).forEach(function(item) {
    const code = String(item.language_code || item.code || "").trim();
    if (!code || code === "en") return;

    const transcriptEnabled = !!item.transcript_enabled;
    const audioEnabled = !!item.audio_enabled;
    const transcriptSource = transcriptEnabled
      ? String(item.transcript_source || "ai").trim()
      : "skip";
    const audioSource = audioEnabled
      ? String(item.audio_source || "tts").trim()
      : "skip";

    rows.push([
      taskId,
      code,
      String(item.language_name || item.name || code).trim(),
      transcriptEnabled,
      transcriptSource,
      audioEnabled,
      audioSource,
      "planned",
      now,
      String(item.note || "").slice(0, 500)
    ]);
  });

  if (rows.length) {
    sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, 10).setValues(rows);
  }
}

function getStatusSheet_() {
  const spreadsheet = SpreadsheetApp.openById(CONTROL_SHEET_ID);
  const sheet = spreadsheet.getSheetByName(STATUS_SHEET_NAME);
  if (!sheet) {
    throw new Error("找不到工作表：" + STATUS_SHEET_NAME);
  }
  return sheet;
}

function readLatestStatuses_(taskIds) {
  const sheet = getStatusSheet_();
  const values = sheet.getDataRange().getDisplayValues();

  if (values.length < 2) {
    return {};
  }

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

    if (!wanted[taskId] || !stage) {
      continue;
    }

    if (!result[taskId]) {
      result[taskId] = { stages: {} };
    }

    // 執行狀態採 append-only；越後面的 row 就是越新的狀態。
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

function responseForAction_(action, payload) {
  if (
    action === "status" ||
    action === "status_batch" ||
    action === "status_health" ||
    action === "language_settings" ||
    action === "language_plan_get" ||
    action === "language_plan_save"
  ) {
    payload.source = "soulkey-bridge";
    payload.type =
      action === "status_health" ? "status_health" :
      action === "language_settings" ? "language_settings" :
      action === "language_plan_get" ? "language_plan" :
      action === "language_plan_save" ? "language_plan_saved" :
      "status_result";
    return postMessage_(payload);
  }
  return json_(payload);
}

function postMessage_(payload) {
  const safe = JSON.stringify(payload).replace(/</g, "\\u003c");
  const html =
    "<!doctype html><meta charset='utf-8'>" +
    "<body style='font-family:sans-serif;font-size:12px'>" +
    "SoulKey status response" +
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

function json_(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
