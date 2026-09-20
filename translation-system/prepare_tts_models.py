from pathlib import Path

from huggingface_hub import snapshot_download

MODELS = {
    "en": "facebook/mms-tts-eng",
    "th": "facebook/mms-tts-tha",
    "es": "facebook/mms-tts-spa",
    "id": "facebook/mms-tts-ind",
    "vi": "facebook/mms-tts-vie",
}

ROOT = Path("/kaggle/working/persistent-model")


def main():
    ROOT.mkdir(parents=True, exist_ok=True)

    for lang, model_id in MODELS.items():
        dirname = model_id.rsplit("/", 1)[-1]
        target = ROOT / dirname
        target.mkdir(parents=True, exist_ok=True)
        print("=" * 72)
        print(f"[TTS MODEL] {lang}: {model_id}")
        print(f"Target: {target}")
        snapshot_download(
            repo_id=model_id,
            local_dir=str(target),
        )
        print(f"✅ {lang} TTS model ready")

    print("")
    print("✅ 五語 MMS-TTS 模型全部準備完成")
    print("請 Save Version / 保存 Notebook Output，之後掛成 Kaggle Input。")
    print("注意：MMS-TTS 模型授權為 CC-BY-NC 4.0。")


if __name__ == "__main__":
    main()
