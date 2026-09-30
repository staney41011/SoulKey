import json
import os
import time
import urllib.error
import urllib.request


NVIDIA_TRANSLATE_ENDPOINT = os.getenv(
    "NVIDIA_TRANSLATE_ENDPOINT",
    "https://integrate.api.nvidia.com/v1/chat/completions",
)
NVIDIA_TRANSLATE_MODEL = os.getenv(
    "NVIDIA_TRANSLATE_MODEL",
    "nvidia/riva-translate-4b-instruct-v2",
)

# NVIDIA Riva Translate v2 supports these four SoulKey targets.
# Sindhi (sd) and Tamil (ta) are intentionally excluded.
SUPPORTED_TARGETS = {"th", "es", "id", "vi"}


def nvidia_target_code(lang: str):
    lang = str(lang or "").strip().lower()
    if lang == "es":
        variant = str(
            os.getenv("NVIDIA_SPANISH_VARIANT", "es-US") or "es-US"
        ).strip()
        if variant not in {"es-US", "es-ES"}:
            variant = "es-US"
        return variant
    if lang in {"th", "id", "vi"}:
        return lang
    raise ValueError(f"NVIDIA Riva Translate 不支援 SoulKey 語言：{lang}")


def _message_text(payload):
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("NVIDIA API 回應沒有 choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if value:
                    parts.append(str(value))
            elif item:
                parts.append(str(item))
        text = "\n".join(parts).strip()
    else:
        text = str(content or "").strip()
    if not text:
        raise RuntimeError("NVIDIA API 回傳空翻譯")
    return text


class NvidiaTranslateClient:
    """Optional second-opinion translator for SoulKey.

    This client never owns the full six-language workflow. It is used only for
    th/es/id/vi when Gemini QA has already found a problem. A failed NVIDIA call
    is therefore non-fatal to the main Gemini pipeline.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = NVIDIA_TRANSLATE_MODEL,
        endpoint: str = NVIDIA_TRANSLATE_ENDPOINT,
        timeout: int = 90,
        max_attempts: int = 3,
    ):
        self.api_key = str(api_key or "").strip()
        if not self.api_key:
            raise ValueError("NVIDIA_API_KEY is empty")
        self.model = str(model or NVIDIA_TRANSLATE_MODEL).strip()
        self.endpoint = str(endpoint or NVIDIA_TRANSLATE_ENDPOINT).strip()
        self.timeout = int(timeout)
        self.max_attempts = max(1, int(max_attempts))

    def translate(self, english_text: str, target_lang: str):
        target = nvidia_target_code(target_lang)
        source = str(english_text or "").strip()
        if not source:
            raise ValueError("NVIDIA translation source is empty")

        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "en-" + target.lower(),
                },
                {
                    "role": "user",
                    "content": source,
                },
            ],
            "temperature": 0,
            "max_tokens": 4096,
            "stream": False,
        }
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        retryable = {408, 409, 425, 429, 500, 502, 503, 504}
        waits = [2, 5, 10]

        last_exc = None
        for attempt in range(1, self.max_attempts + 1):
            request = urllib.request.Request(
                self.endpoint,
                data=encoded,
                method="POST",
                headers={
                    "Authorization": "Bearer " + self.api_key,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "SoulKey-NVIDIA-Second-Opinion/1.0",
                },
            )
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self.timeout,
                ) as response:
                    status = int(getattr(response, "status", 200) or 200)
                    raw = response.read().decode("utf-8")
                if status == 202:
                    raise RuntimeError(
                        "NVIDIA API 回傳 202 pending；本輪改由 Gemini 繼續"
                    )
                if status != 200:
                    raise RuntimeError(f"NVIDIA API HTTP {status}")
                return _message_text(json.loads(raw))
            except urllib.error.HTTPError as exc:
                last_exc = exc
                if int(exc.code) not in retryable or attempt >= self.max_attempts:
                    detail = ""
                    try:
                        detail = exc.read().decode("utf-8")[:800]
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"NVIDIA API HTTP {exc.code}: {detail}"
                    ) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_exc = exc
                if attempt >= self.max_attempts:
                    raise RuntimeError(
                        f"NVIDIA API network error: {type(exc).__name__}: {exc}"
                    ) from exc
            except RuntimeError:
                raise

            wait_seconds = waits[min(attempt - 1, len(waits) - 1)]
            print(
                f"[NVIDIA] transient error; retry {attempt + 1}/"
                f"{self.max_attempts} after {wait_seconds}s",
                flush=True,
            )
            time.sleep(wait_seconds)

        raise RuntimeError(f"NVIDIA translation failed: {last_exc}")
