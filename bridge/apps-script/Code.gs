const OWNER = "staney41011";
const REPO = "SoulKey";
const WORKFLOW = "kaggle_run_bridge_test.yml";
const REF = "main";

const CONTROL_SHEET_ID = "1AwPqTqZSzW7Q-gLW4J5d-28dQZwVksyDnvsxNRF2uu8";
const STATUS_SHEET_NAME = "執行狀態";

function doGet() {
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
    action === "status_health"
  ) {
    payload.source = "soulkey-bridge";
    payload.type = action === "status_health" ? "status_health" : "status_result";
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
