from pathlib import Path

from huggingface_hub import snapshot_download

MODEL_ID = "Qwen/Qwen3-4B"
TARGET = Path("/kaggle/working/persistent-model/qwen3-4b")


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    print(f"下載 {MODEL_ID} 到 {TARGET}")
    snapshot_download(
        repo_id=MODEL_ID,
        local_dir=str(TARGET),
    )
    print("")
    print("✅ AI 校稿模型準備完成")
    print(f"Model: {TARGET}")
    print("請像 ASR 模型一樣 Save Version，之後掛成 Kaggle Input，避免每次重抓。")


if __name__ == "__main__":
    main()
