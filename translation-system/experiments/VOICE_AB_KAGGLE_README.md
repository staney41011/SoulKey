# SoulKey｜5 語言 Edge TTS × VoxCPM2 A/B 語音測試（隔離實驗）

**目的：**比較 **英語 en、泰語 th、高棉語 km、寮語 lo、緬甸語 my** 的語音自然度、清晰度、專有名詞發音、停頓，以及實際生成時間。此測試不修改 SoulKey 正式 TTS 引擎、不連接 Drive、沒有寫入 Studio，不上傳 YouTube。

## 官方來源與限制

- VoiceStudio：https://github.com/debpalash/VoiceStudio — 多引擎開源桌面系統，應用程式 AGPL-3.0；**本實驗沒有安裝／複製它的應用程式**。
- VoxCPM2：https://huggingface.co/openbmb/VoxCPM2 、https://openbmb.cn/docs/en/guides/voxcpm/voxcpm-2 — 模型約 2B、支援 30 語（包括上述 5 語）、Apache-2.0、參考顯存約 8 GiB、輸出 48 kHz；需 Python 3.10–3.12、PyTorch ≥2.5、CUDA ≥12 的 GPU 路線。
- Edge：沿用 translation-system/natural_tts_config.py 五種聲線／語速／音高設定作對照。Edge TTS 需網路連線；它不是開源離線引擎。
- **尚未驗證** VoxCPM2 在 Kaggle T4/P100 的相容性、五語配音品質及任何比 Edge 更佳的結論。官方支援語種不保證自然度。Kaggle GPU 分配與 Python 版本可能不同，執行前必須跑 notebook 的預檢。

## 使用

1. 在 Kaggle 建立 GPU Notebook，開啟 Internet，匯入 soulkey_voice_ab_kaggle.ipynb。Notebook 自帶跑測試所需程式及五語示範文本，不需要 GitHub Token、Google Drive 或 API Key。
2. 依順序執行：Python/GPU 預檢、安裝依賴、生成程式及文本、Dry Run 驗證、正式合成、對照試聽。
3. 測試成果儲存在 /kaggle/working/soulkey-voice-ab/：en_edge.wav、en_voxcpm2.wav 等（每語各兩檔）、ab_report.json（音檔長度、推理耗時、RTF、SHA256、失敗原因）、human_review.csv（保留空白評分欄）。工作結束後可將結果另行下載保存。
4. 若要比較真實課程，將 voice_ab_samples.demo.json 的每語 text 換成**同一堂課已校對的對應語言文稿**。請在 Notebook 內換掉示範文本後重跑乾測試與合成，不要用自動生成的隨意翻譯評斷專有名詞。
5. 若 Kaggle 的 Python 為 3.13、GPU 沒有足夠顯存，或某一語言生成失敗，依照錯誤紀錄處理；**不要動正式 SoulKey 的 Python 環境**。

## 評分與決策

human_review.csv 需要熟悉該語言的人**實際聆聽**後填入：發音、流暢度、自然度、停頓、佛學術語、是否漏唸、評分者、意見。避免只以長度或 RTF 判定勝負。

初版使用自然語速、相同文稿、未指定參考聲線，VoxCPM2 seed=42、cfg_value=2.0、inference_timesteps=10。Edge 使用正式聲線設定；聲線與引擎不同，屬探索性比較，非科學盲測。**不啟用授權不明的聲音克隆**。

正式 SoulKey 仍要符合「內容完整、音檔不超過原影片、驗收確認」的 A+B 合約。**本實驗不對生成秒數作任何配速調整**，也不聲稱其測試音檔可直接當正式影片配音。

## 無 GPU 時的檢查

在專案目錄執行：

    python translation-system/experiments/voice_ab_runner.py --samples translation-system/experiments/voice_ab_samples.demo.json --dry-run
    python -m unittest discover -s translation-system/tests -p test_voice_ab_runner.py

--edge-only 可以單獨執行 Edge，但仍需要網路、ffmpeg、edge-tts 和 soundfile；完整 VoxCPM2 對照需合格 GPU runtime。
