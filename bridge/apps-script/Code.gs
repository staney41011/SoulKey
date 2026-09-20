const OWNER = "staney41011";
const REPO = "SoulKey";
const WORKFLOW = "kaggle_run_bridge_test.yml";
const REF = "main";

function doGet() {
  return json_({
    ok: true,
    service: "SoulKey Studio Bridge",
    message: "bridge-ready"
  });
}

function doPost(e) {
  try {
    const props = PropertiesService.getScriptProperties();
    const expectedKey = String(props.getProperty("BRIDGE_KEY") || "").trim();
    const githubToken = String(props.getProperty("GITHUB_TOKEN") || "").trim();

    if (!expectedKey || !githubToken) {
      return json_({
        ok: false,
        error: "server_not_configured"
      });
    }

    const bridgeKey = String((e && e.parameter && e.parameter.bridge_key) || "").trim();
    const action = String((e && e.parameter && e.parameter.action) || "").trim();

    if (!bridgeKey || bridgeKey !== expectedKey) {
      return json_({
        ok: false,
        error: "unauthorized"
      });
    }

    if (action !== "smoke") {
      return json_({
        ok: false,
        error: "unsupported_action"
      });
    }

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
        "X-GitHub-Api-Version": "2022-11-28"
      },
      muteHttpExceptions: true
    });

    const status = response.getResponseCode();

    if (status !== 204) {
      return json_({
        ok: false,
        error: "github_dispatch_failed",
        github_status: status,
        github_body: response.getContentText().slice(0, 800)
      });
    }

    return json_({
      ok: true,
      action: action,
      message: "GitHub Actions workflow dispatched"
    });
  } catch (err) {
    return json_({
      ok: false,
      error: "bridge_exception",
      message: String(err && err.message ? err.message : err)
    });
  }
}

function json_(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
