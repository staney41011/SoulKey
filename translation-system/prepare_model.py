from pathlib import Path

from huggingface_hub import snapshot_download

MODEL_ID = "shooding/taiwan-breeze-asr-26"
DEST = Path("/kaggle/working/persistent-model/taiwan-breeze-asr-26")


def main():
    DEST.mkdir(parents=True, exist_ok=True)

    if (DEST / "model.bin").exists() and (DEST / "config.json").exists():
        print(f"✅ 模型已存在：{DEST}")
        return

    print(f"開始下載 {MODEL_ID}")
    print("這個動作只需要做一次。")
    snapshot_download(
        repo_id=MODEL_ID,
        local_dir=str(DEST),
    )

    required = ["model.bin", "config.json", "tokenizer.json"]
    missing = [name for name in required if not (DEST / name).exists()]
    if missing:
        raise RuntimeError(f"模型下載不完整，缺少：{missing}")

    print("✅ 模型準備完成")
    print(f"位置：{DEST}")
    print("")
    print("下一步：")
    print("1. Kaggle 點 Save Version / Save & Run All")
    print("2. 確認保存 Notebook Output")
    print("3. 將這份 Output 或其建立的私人 Dataset 掛回 translate system 的 Input")
    print("4. 未來 Runner 會自動從 /kaggle/input 找模型，不再重下載")


if __name__ == "__main__":
    main()
