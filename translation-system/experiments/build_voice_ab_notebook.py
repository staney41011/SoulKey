"""Generate a portable Kaggle notebook from the tested A/B runner and fixture."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(True)}


def code(text: str) -> dict:
    return {
        "cell_type": "code", "metadata": {}, "execution_count": None,
        "outputs": [], "source": text.splitlines(True),
    }


def build_notebook() -> dict:
    runner = (ROOT / "voice_ab_runner.py").read_text(encoding="utf-8")
    fixture = (ROOT / "voice_ab_samples.demo.json").read_text(encoding="utf-8")
    return {
        "cells": [
            md(
                "# SoulKey｜Edge TTS × VoxCPM2 五語配音 A/B 測試\n\n"
                "獨立實驗：英語、泰語、高棉語、寮語、緬甸語。"
                "本 Notebook 不會連接 Google Drive／Sheets 或改動正式配音流程。\n\n"
                "在 Kaggle Notebook 設定 GPU、Internet On，從第一格依序執行。"
                "可先跑示範文稿驗證流程；比較課程品質時請改成已核對的翻譯文稿。"
                "低資源語的示範文本尚未由母語者校對。\n\n"
                "VoxCPM2：https://huggingface.co/openbmb/VoxCPM2 "
                "（Apache-2.0；官方 VRAM 參考約 8 GiB；Python 3.10–3.12）。"
                "Edge baseline 沿用 SoulKey 現有聲線；不安裝 VoiceStudio 桌面應用。"
            ),
            code(
                "import sys, shutil\n"
                "print('Python:',sys.version)\n"
                "assert (3,10)<=sys.version_info[:2]<(3,13), "
                "'VoxCPM2 支援 Python 3.10–3.12，請切換 Kaggle Runtime'\n"
                "import torch\n"
                "print('torch:', torch.__version__, 'cuda:', torch.version.cuda)\n"
                "assert torch.cuda.is_available(), '請在 Kaggle Settings 開啟 GPU Accelerator'\n"
                "print('GPU:', torch.cuda.get_device_name(0))\n"
                "print('Free GPU memory (GiB):',round(torch.cuda.mem_get_info(0)[0]/1024**3,2))\n"
                "print('BF16 support:',torch.cuda.is_bf16_supported())\n"
                "assert shutil.which('ffmpeg'), 'ffmpeg is required'\n"
                "assert torch.cuda.mem_get_info(0)[0] >= 7.4*1024**3, "
                "'VoxCPM2 推論大約需要 8 GiB 可用顯存'\n"
            ),
            md("## 安裝測試依賴\n只在此 Kaggle Notebook 安裝，不改 SoulKey 正式 Worker 的 requirements。"),
            code("%pip -q install 'edge-tts==7.2.8' 'voxcpm' 'soundfile'\n"),
            md("## 實驗腳本與五語示範文本\n下方會在 Kaggle 工作目錄建立檔案，不會寫回雲端。"),
            code("%%writefile /kaggle/working/voice_ab_runner.py\n" + runner),
            code("%%writefile /kaggle/working/voice_ab_samples.demo.json\n" + fixture),
            md("## 核對文稿\n預設是示範句而非 SoulKey 正式課程翻譯。"
               "真實教學比較請將上述 JSON 各語言 text 換成已確認的同段課程譯稿。"),
            code(
                "!python /kaggle/working/voice_ab_runner.py "
                "--samples /kaggle/working/voice_ab_samples.demo.json --dry-run\n"
            ),
            md("## 正式合成\n五語各跑 Edge 與 VoxCPM2；第一次會下載數 GB 模型。"
               "如果其中一語失敗，其他語仍繼續，錯誤保存在報告。"),
            code(
                "!python /kaggle/working/voice_ab_runner.py "
                "--samples /kaggle/working/voice_ab_samples.demo.json "
                "--output-dir /kaggle/working/soulkey-voice-ab\n"
            ),
            md("## 試聽與報告\nRTF 是合成耗時除以音檔秒數，越低越快，並不代表更自然。"
               "請由各語言母語者聆聽後填寫 human_review.csv。"),
            code(
                "from pathlib import Path\n"
                "from IPython.display import display, Audio\n"
                "import json\n"
                "out=Path('/kaggle/working/soulkey-voice-ab')\n"
                "report=json.loads((out/'ab_report.json').read_text(encoding='utf8'))\n"
                "for row in report['results']:\n"
                "    print(row['language'],row['engine'],row.get('status'),"
                "'duration',row.get('seconds'),'RTF',row.get('rtf'),"
                "'error',row.get('error',''))\n"
                "    if row.get('status')=='ok': display(Audio(filename=str(out/row['file'])))\n"
                "print('請下載 human_review.csv 填寫母語者評分；勿直接取代正式配音。')\n"
            ),
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
            "kaggle": {"isInternetEnabled": True, "accelerator": "gpu"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main():
    result = ROOT / "soulkey_voice_ab_kaggle.ipynb"
    result.write_text(json.dumps(build_notebook(), ensure_ascii=False, indent=1) + "\n",
                      encoding="utf-8")
    print(result)


if __name__ == "__main__":
    main()
