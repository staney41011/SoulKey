# SoulKey｜系統操作日誌與第 259 期交付追蹤

## 2026-10-31｜Kaggle 舊映像 ABI 不符已定位；正式文稿實際增加到34組

- 第一個新授權 [#41103810894](https://github.com/staney41011/SoulKey/actions/runs/41103810894) 已實際在Kaggle執行：T4 GPU存在、四堂Final同步成功，30個已過QA語言逐一匯出／讀回Drive文稿。Drive重新盤點三種格式完整且非空：L01 **10**、L02 **15**、L03 **7**、L04 **2**，共 **34/64組文稿**。正式MP3仍 **18/64**、試聽5組；QA仍 **30/60**。英文人工定稿4組已包括在34組文稿內，不重複列為AI QA。
- 02:11補譯啟動失敗：官方 `llama-server` 需要 `GLIBC_2.38 / GLIBCXX_3.4.32`，既有專用kernel從 `kernels pull -m` 帶回舊 `docker_image` digest，造成舊Ubuntu系統映像一直被沿用。這不是Google授權失效，也不是JSON文法或翻譯QA問題；新Gemma語言尚未產生。
- 依Kaggle官方CLI已驗證的metadata介面，P259 Gemma任務移除舊digest，明確設定 `docker_image_pinning_type=latest`。保持同一私人kernel、原Notebook資料來源、T4、Bridge短效授權；不恢復任何GCP worker。其他工作不擅自改寫當次拉取的映像設定。
- 模型下載前新增30秒內的原生執行檔ABI檢查，失敗時明確指出工作映像不相容，不等到下載權重後才退出。4項測試實際執行workflow的metadata產生程式，覆蓋舊映像移除、非Gemma工作保留、成功／失敗ABI probe；10項Gemma修復與數字QA測試通過。
- [校稿PR #34](https://github.com/staney41011/SoulKey/pull/34) 全部CI通過，已合併 `6bb4a3b3d14497684fb1759077f72448066e426c`。61項pipeline合約與21個Studio測試通過；明確 `?step=en` 仍開英文步驟、草稿不能用 `?step=output` 跳過人工定稿。新映像需在正式合併後由原Studio建立新工作，讓GitHub採用更新後的workflow；不能rerun舊workflow便假設metadata也會更新，更不能把靜態檢查算成真實GPU成功。

---

## 2026-10-31 02:10（台灣）｜原 Bridge 第67版已部署，真實登入與新 Kaggle 派工成功

- 原 Apps Script 專案 `SoulKey Studio Bridge` 的既有公開部署已更新至 **67版**（02:03）。保留原 `/exec` 網址、原六碼、Script Properties、執行身分與存取範圍；沒有建立替代控制中心。以線上原始碼177,240字元為基礎，只新增框架回傳與可核對的健康欄位，沒有整份覆蓋使用者線上的修訂。
- 原 `/exec` 實際讀回 `bridge-ready / bridge_protocol:9 / bridge_client_transport:top-postmessage-v1`。manifest 僅保留 spreadsheets、drive、script.external_request 三項原權限；無 Firebase／GCP 額外權限。
- [PR #33](https://github.com/staney41011/SoulKey/pull/33) 已合併 `24cc131804ac8724a6bb9ca49977cc971c22d645`；[Pages #41100019709](https://github.com/staney41011/SoulKey/actions/runs/41100019709) 成功。正式工作台實際顯示「控制中心已連線」，並從原 Google Sheet 載入 **31筆任務**，不是只核對公開健康端點。
- 02:05由原Studio確認四堂補譯，建立新的 [Kaggle Web Job #41103810894](https://github.com/staney41011/SoulKey/actions/runs/41103810894)（main `24cc131804ac`）。中央狀態已出現本次 `P259-L01 / multi / running / web-job_eidS9Rrm / 02:05:41`。這是本次已授權 Worker 開始的證據；不代表60語 QA 或64組音檔完成。舊 #41002147166 nonce 已過期，沒有再重跑。
- 真實開啟快速校稿頁另發現：Drive中英文已載入，卻未刷新定稿旗標與步驟，英文按鈕仍被鎖住；59個英文段落又錯按ID套至449個ASR片段。前端改用原Bridge回傳的英文段落、時間對齊中文與 `finalized_at`，完整保留人工定稿並解鎖輸出；草稿仍需人工定稿。已完成稿不再被遲到的GitHub快取或逐句草稿覆蓋，本機未儲存修改保留。
- 新增實際執行校稿訊息處理器的回歸測試，涵蓋59/449不同段落ID、定稿解鎖、草稿不誤標完成、不同課隔離、逐句回執、本機未儲存修改與晚到快取；**21個Studio測試程式及JS語法檢查通過**。校稿新修正另待該次PR與Pages部署及真實讀回；不能以本地測試當線上完成。
- 當前最後一份完成數快照仍為 **QA 30/60、文稿24/64、正式MP3 18/64、試聽5組**。下方10/30的Cloud Run、舊run與數量僅為歷史；現行接手入口以本節及第0、1節為準。

---


## 2026-10-31｜無GCP版已上線；原 Apps Script 嵌入回覆仍需更新部署

- [PR #32](https://github.com/staney41011/SoulKey/pull/32) 已合併 `aa3117286e9fe4ddcabfb570a4c67025e80fb7f3`，正式分支所有CI通過。[退役工作 #41097953766](https://github.com/staney41011/SoulKey/actions/runs/41097953766) 成功，日誌逐一確認四個舊 GCP workflow 已 disabled。沒有刪除原專案、Sheet、Drive 或私人 Kaggle 產物。
- 最新 Drive 再盤點：L01 文稿7／正式MP3 5／試聽2；L02 14／12／2；L03 2／1／0；L04 1／0／1。合計 **24/64組文稿、18/64組正式MP3、另5組試聽**。最新中央非英文QA **30/60**。
- 實際瀏覽器已確認正式站載入無GCP版、移除 Firebase 入口；原 `/exec` 回傳 `bridge-ready / protocol 9`。安全表單送出登入後，嵌入式讀取沒有完成，未宣稱登入成功或重新派工成功。
- 原因：原 `bridgeClientHtml_` 只 `window.parent.postMessage`；HtmlService 另包一層Google外框，回覆未直接送回Studio。修正為同時送至指定 Studio origin 的 `window.top`；公開健康回覆加上 `bridge_client_transport=top-postmessage-v1`，可獨立核對實際部署。
- 前端讀取失敗會呼叫登入錯誤處理，不再永遠顯示同步中；health讀取有30秒上限。iframe ready不再額外重排同一登入請求。新版快取v2。新增實際執行原client腳本的測試，確認ready、Google script callback與逾時能送達正確的Studio。
- **部署邊界**：程式與測試已備妥，需更新原 Apps Script 的同一既有部署，保留原Script Properties／原六碼與授權。不能把GitHub已更新當成Google腳本已更新；部署後以健康欄位、真實登入及新的Kaggle run驗證。

---


## 2026-10-31｜依最新指示停用 GCP，接回原 Apps Script／Kaggle

- 使用者明確要求日後不再使用 GCP。以中途修改後的 main `13cd8a425f29a37710ccf8873d73e54bc3ec1a1f` 為基礎；保留新加的數字 QA、短句檢查、敏感錯誤遮罩與 runtime preflight，沒有套回之前未提交的舊工作目錄。
- 正式入口固定原 Apps Script，模式 `legacy-kaggle`。保留原六碼、Sheets、Drive、GitHub 及 Kaggle。主站移除 Firebase 備援入口；RTDB 鏡像程式移至 archive，正式 Apps Script 不再呼叫，manifest 移除 Firebase／email 額外 scopes。既有雲端專案與資料沒有刪除。
- 舊 Cloud Run 翻譯、CC、kickstart 及 capability probe 工作停止排程，移除 OIDC 與網路操作；原 Python worker main 直接拒絕啟動，Cloud Shell 部署腳本也停止。新增一次性退役工作，合併後停用這四個舊 workflow 並取消其執行中的協調工作；保留私人 Kaggle 產物與所有歷史記錄。**需核對退役工作結果才可稱已實際停用。**
- 修復切回舊入口後的實際斷點：主介面英文逐句儲存改原表單 POST＋Drive request receipt；獨立校稿頁保留原 Final action，讀取一律 authenticated iframe，英文寫入等待正確 task/request 回執。53句分三批時，前25句回執不會提早宣告整批完成。最後輸出先核實語言設定，再使用原 `review_finish`，不再向 Apps Script 等待不存在的 CORS JSON。
- YouTube CC／原音軌抓取接回原 Bridge → Kaggle，不再依賴 Cloud Run capability flag；iOS CC 也沿用原頂層 POST。中文定稿的舊版 ACK 可正常完成介面流程；移除過時的 Cloud Run 配額／部署提示。
- 保護後續人工修訂：較新的 Drive Final 經 task／kind／段落／帶時區時間核對後，以 SHA-256、分塊內容回讀及 append-only 索引寫回 Sheet。舊備存不刪；Drive 或中央版本在過程中改變即中止。四堂救援也會先同步各堂 Final。無法判定先後的不同稿件保留並要求核對，不覆蓋。
- 本地驗證：31個現行 JavaScript 測試程式、61項 pipeline contracts、6項中央同步、5項新舊 Final 保護、3項歷史 relay／退役檢查、新增無GCP及舊服務回執測試通過；Python／JS 語法檢查通過。線上 CI、Pages 與真實授權派工另待讀回，不能把程式提交當作正式64組完成。
- 01:13（台灣）最新 Sheet 讀回：P259 非英文 QA **30/60**，包括新增 L04 緬甸文。四份英文人工 Final 另計；沒有在這次尚未重新掃描 Drive 前沿用舊數字宣稱音檔增加。其餘翻譯、正式文稿／配音及需要試聽的項目仍待完成。
- 原12:18派工的 runtime 已超過8小時；禁止再重跑該 nonce，保留現有 preflight。新工作須從原 Studio 建立新的合法授權，無須重設六碼或把憑證交給 GitHub/GCP。GitHub 更新 Code.gs **不會自動更新已部署的 Apps Script**；Apps Script 部分的部署與測試必須如實區分。

---

## 2026-10-30 20:54（台灣）｜修復跨時區的派工回執與逾時判讀

- 發現並修正：原 Apps Script 的 `yyyy-MM-dd HH:mm:ss` 是台灣時間，Cloud Run 原樣回傳；瀏覽器若在 UTC／其他時區用 Date.parse 直接解讀，舊 `finish done` 可能被當成新派工回執，執行逾時提示也會錯位。
- `bridge-routing.js` 明確以 `+08:00` 解讀原服務時間，ISO UTC／帶時區值保持原意；主介面的最新中文階段排序及30分鐘提示採用相同函數。新舊 run ID 和提交時間門檻仍保留，舊結果不能代替本次派工成功。
- 驗證涵蓋 UTC、Asia/Taipei、America/Los_Angeles 三時區：20:00:01台灣時間對應12:00:01Z；提交前十分鐘的舊完工紀錄一律拒收。iOS 頂層派工及中央定稿儲存測試同時通過。
- 原頁面與獨立校稿頁的 bridge 腳本更新版本至v2，主程式至v6，避免瀏覽器沿用舊快取。回退僅需回復本次前端提交，不改 Sheet、Drive、授權或正在執行的 Kaggle 工作。

---

## 2026-10-30 20:50（台灣）｜連續佇列已正式啟動；文稿23組、正式配音18組

- [PR #30](https://github.com/staney41011/SoulKey/pull/30) 已合併至 `db9376537f1ead3a4275cd3d4e7b086204476287`，Studio、MVP、Bridge 整合、relay 靜態檢查及 Pages 部署均通過。瀏覽器實際載入原 Studio 的修復資源；登入仍使用原六碼，沒有更換金鑰或 Google 授權。
- 合併後的 [kickstart #41057302259](https://github.com/staney41011/SoulKey/actions/runs/41057302259) 以合法 `workflow_dispatch` 自動啟動 [正式翻譯 #41057315662](https://github.com/staney41011/SoulKey/actions/runs/41057315662)。中央 Sheet 已確認第1堂 `ja,ko,km` 於20:42:17被領取、狀態 running；後續有上限續接。這不等於全文 QA 已通過，此時 QA 仍24/60。
- 原授權 [Kaggle Web Job #41002147166 attempt 3](https://github.com/staney41011/SoulKey/actions/runs/41002147166) 持續交付；新增正式音檔：L01 `id,vi`，L02 `km,bn,ne,lo,my`。L03 `th` 於20:48:35開始。每語言先發布已驗證 TXT/SRT/JSON，再生成音檔並讀回校驗。
- Drive 逐堂目錄快照：L01 **7組文稿／5組正式MP3／2組試聽**；L02 **14／12／2**；L03 **1／1／0**；L04 **1／0／1**，合計 **23/64組文稿、18/64組正式MP3，另5組待驗收試聽**。此表不含後續仍在執行的輸出，不宣稱64組全部完成。
- 獨立抽驗 L02 緬甸文：文稿為 `central-passed-qa`、53個唯一且非空段落、revision `d89bd0ee...`；正式MP3 27,633,453 bytes，manifest `edge-natural-v2 / done`，MP3 MD5 `4c63843148c23ad2a85f250e93169023`、WAV MD5 `72c17764283ea8d8534d9f49d2eb59f0`。L01 越南文59段、revision `2bc74709...`，MP3 28,433,325 bytes／MD5 `dc3a188d48385677b5fcd767035b60dc`。
- 仍須核對：Gemma 整堂翻譯 QA 與後續自動領取、尚缺文稿和配音、試聽版音長驗收。原 runtime nonce 有8小時時效，若後續明確回報過期，需由原 Studio 合法建立新工作；不從紀錄取憑證、不延長授權時效。

---

## 2026-10-30 20:37（台灣）｜JSON 修復已通過真實 GPU 並部署；接續整批佇列

- [PR #29](https://github.com/staney41011/SoulKey/pull/29) 已合併至 `ff613c62ce109836e70a374805fa5987abb09003`。舊 response_format 路徑即使停用 thinking，仍可能開啟 thought 前綴（llama.cpp上游 #30256）；改直接 GBNF JSON 文法，並保留完整 IDs、數字、語意 QA。
- **真實 T4 驗收通過**：[直接文法 smoke #41055234586](https://github.com/staney41011/SoulKey/actions/runs/41055234586)，`GEMMA_GPU_JSON_VERIFIED passed=[it,pt], failures={}`。先前單獨關閉 thinking 的 [#41053619551](https://github.com/staney41011/SoulKey/actions/runs/41053619551) 亦通過；這兩個是公開合成小樣本，不能算第259期全文 QA 成果。
- 已獨立讀回 Drive 第1堂印尼文正式 [MP3](https://drive.google.com/file/d/1gRtxye7zGBlRxH6yVv6M0tiYX2d40kE9/view?usp=drivesdk)，29,814,573 bytes；manifest `edge-natural-v2 / done / 59 segments`、英文 revision `2bc74709...`，MP3 MD5 `954ff340861800a7a07169423423ccc0`，WAV 89,440,152 bytes／MD5 `30774a271535a55feb43415d159259eb`。20:18:15 第1堂越南文亦有新的正式交付驗證；印地語是 needs_review 試聽，不混入正式數。
- Queue worker 接有上限的 workflow_dispatch 連續領取：每次只領一個中央工作，保留 source revision／已通過 QA；沒有工作即停止；剩餘次數每次減一、最多20，失敗語言保留 error 並允許下一個獨立工作。首輪12次續接，含起始共最多13批，涵蓋目前分批待譯工作。沿用舊程式本身的排程/手動派工，沒有另建外部服務。
- Kaggle 私有 worker 接回中央已篩選的專有名詞／LOCKED 用語；只傳文稿與術語，Google憑證不進這條 relay。既有 Apps Script→Kaggle 正式配音仍沿原授權運作。
- 後續必看：正式翻譯 queue 的新 run ID、實際 QA 增加、Drive文稿與MP3。不能用公開小樣本或連續派工設定推定64/64交付；目前翻譯 QA 最後讀回仍24/60。

---

## 2026-10-30 20:17（台灣）｜PR #28 已部署、舊授權配音實際恢復；Gemma JSON 修復驗證中

- [PR #28](https://github.com/staney41011/SoulKey/pull/28) 已合併，主線 `ad3d42d7fc6b8a7f13b6f57502554f1ca1486892`。修復提交的 Studio、MVP、語意/數字、CPU 音訊組裝等檢查全部通過。原站 Pages [#41053433262](https://github.com/staney41011/SoulKey/actions/runs/41053433262) 成功；瀏覽器 DOM 已確認 `bridge-routing.js` 及 `app-20260923-48.js?v=20261030-legacy-workflow-v5` 載入。
- 保留原 Kaggle 授權輸入，重新執行 [#41002147166 attempt 3](https://github.com/staney41011/SoulKey/actions/runs/41002147166)。20:11:34 中央 `tts running`，**20:15:41 P259-L01 印尼文 `tts:id done`**，Worker 回報「正式 MP3/WAV 與 manifest 已上傳 Drive 並校驗」。這是新的單語交付回讀紀錄，不是64組全部完成。Drive connector 的檔名搜尋尚未取到該檔，未提供猜測音檔連結。
- [Gemma relay #41047898408](https://github.com/staney41011/SoulKey/actions/runs/41047898408) 的真實模型已在 T4 載入（`GEMMA4_QAT_12B_READY`），但義大利文、葡萄牙文均 `gemma_json_invalid`，結果0 passed，中央 QA 仍24/60。新的診斷只下載結果 JSON，避免把整個 GGUF 和 repo 抓回 GitHub。
- [PR #29](https://github.com/staney41011/SoulKey/pull/29) 明確停用 Gemma thinking，偵測 token 截斷、保留不含講稿的解析原因；合成公開句子的 [真實 T4 JSON/QA smoke #41053619551](https://github.com/staney41011/SoulKey/actions/runs/41053619551) 正在執行，此時不能稱已通過。
- 中央 Final 同步補齊可讀 TXT/SRT；不同內容先保存舊檔版本並回讀，不只更新 JSON。新增「JSON 已存在但 TXT/SRT 缺失」測試。未登入獨立校稿頁不再送出空金鑰寫入。
- 完整授權 ASR→人工定稿→全部多語→正式音檔的整期驗收仍未完成。既有授權 job 有時效，後續如果明確回報 nonce_expired，應由原 Studio 建立新的合法工作；不可取用 log 中的敏感資料繞過授權。

---

## 2026-10-30 20:03（台灣）｜恢復 10/28 前流程並接回中央定稿（修復驗收中）

- 舊版基準：`efcf6903d09d1cc64ec18598def64e225a2d1280`（10/27），已保留在 `recovery/pre-20261028-working-baseline`。本次不回退中央 Sheet／Drive 資料。
- 原因：新控制中心未實作完整舊 action，但介面仍向它送出；`cloudStageUnavailable` 又無條件鎖住中文／TTS。獨立校稿頁把 `cloud-recovery` 轉成 NaN、使用無法取得 JSON ACK 的 iframe 儲存，且英文快照缺新版逐句確認欄位。
- 修復：共用 `studio/bridge-routing.js`，中央讀取／Final／逐句確認繼續用新服務；中文、AI 英文、多語、TTS、finish、原課表／快取／檔名操作走既有 Apps Script → GitHub → Kaggle。iOS 所有機器階段走原已驗證的頂層 POST，並依新的中央 run ID／時間回讀確認；不把送出表單當作成功。
- 獨立校稿頁：Final 改中央 CORS POST、正確處理協定與回覆；英文確認每批最多25句，核對 base request ID，衝突不覆蓋，遺失 ACK 後回讀同一 request receipt。最終輸出先保存語言設定，再派原 `run_stage/finish`，避開只認 Drive en.final.json 的舊前置檢查。
- 舊 Worker 讀新資料：`central_final_sync.py` 以中央 SHA／task／段落驗證同步人工作稿 JSON；較舊 Drive JSON 先保存並回讀版本檔才更新；不同課堂、失效 SHA、中文時間軸衝突均拒絕。沒有中央 Final 的歷史課程照舊運作。
- 第259期：移除 Kaggle 舊的 model attachment；GGUF 由原 worker 下載。一般配音與 finish 均讀中央正確版本／已通過 QA 的語言，不觸發舊 Gemini 重譯。尊重單堂／語言勾選與真人錄音；已通過 QA 的文稿即使不配音亦同步到 Drive；未通過 QA 不標記 multi done。
- 已完成離線驗證：61項 pipeline contracts、18項中央來源／文稿／定稿測試、6項原片來源檢查、32個 JavaScript 測試程式（含中央確認、遺失 ACK、跨裝置衝突及既有 Cloud Bridge helpers）；相關 Python／JS／workflow 語法檢查。線上 CI 與實際授權工作另行記錄。
- 實際阻礙：本環境沒有已登入 Studio／Google 的瀏覽器；Desktop Commander 已回報本月額度用完，依工具指示不重連。未接觸／重設原六碼、OAuth、Kaggle secrets。尚未完成新的真實 ASR→人工定稿→翻譯→正式 Drive MP3 閉環，不能以離線測試或 GitHub 綠燈宣稱全部恢復。
- 最近真實來源讀回仍是四份獨立英文 Final、24/60非英語 QA passed；先前11/64正式 MP3基線不得當作最新掃描。既有 relay／preview 執行中的成果需以新查詢逐一驗收。
- 回退：僅回退本次修復 commit 的程式；若回到10/27整版請先核對中央 Final 差異。舊人工作稿 JSON 的 revision 檔不可刪除。

---

## 2026-10-30 15:26（台灣）｜第259期四堂 64 文稿／64 配音續跑：實際驗收、GitHub 自動授權派工

> 這是實際執行記錄，**不是已完成 64/64 的宣告**。以 Google Drive 上正式檔案及來源 SHA/QA/manifest 讀回為最終標準。

- 真實交付快照（Drive 逐堂資料夾列舉）：L01 `3` 份已驗證文稿／`3` 組正式 MP3；L02 `9`／`7`；L03 `1`／`1`；L04 `1`／`0`，合計 **14/64 文稿、11/64 正式 MP3**。另有 L02 Hindi、Tamil 和 L04 English 三組 `needs_review` 試聽 MP3，不納入正式數。
- 中央 `翻譯QA紀錄`：非英語 **10/60** 通過；L01 `th,es`，L02 `th,es,id,vi,hi,ta,ja,ko`。L03/L04 0。全部四堂 `英文定稿索引` 各有已驗證的獨立 revision；保留既有成果，不清空 Sheet。
- 舊版原始 Kaggle Web Job [#41002147166](https://github.com/staney41011/SoulKey/actions/runs/41002147166) 已完成；一次性 backfill run [#41016642669](https://github.com/staney41011/SoulKey/actions/runs/41016642669) 的原 rerun 結果 `exported_manuscripts 14, manuscript_export_errors 0`，**不是 64 語驗收**。
- GitHub `cloud-bridge/translation_worker.py` 現在只有第259期可用 `SOULKEY_P259_GEMINI_MODEL=gemini-3.1-flash-lite`，其他期仍保留原模型；不降低 QA、鎖定英文來源 revision、完整 segment ID 審核。
- 中央 `翻譯工作佇列` 的原有四筆安全恢復為 `queued`（第10–13列）。另外新增 P259-L03、L04 的 `hi,ta,ja,ko,bn,ne,lo,my,it,pt` 十語補譯各一筆（第14–15列）。總計六筆中央工作；前面已通過 QA 的語言仍按來源 revision 複用，不重新刪改。
- [push run #41019698354](https://github.com/staney41011/SoulKey/actions/runs/41019698354) 曾因 Cloud Run OIDC 僅授權 `schedule/workflow_dispatch` 而 401；**沒有放寬 Cloud Run 身分驗證**。已移除直接 push 翻譯，建立 [one-shot kickstart #41020031810](https://github.com/staney41011/SoulKey/actions/runs/41020031810) 用 Actions 官方權限派出合法 `workflow_dispatch`，[正式翻譯 run #41020040604](https://github.com/staney41011/SoulKey/actions/runs/41020040604) 已進入 `in_progress` 的翻譯步驟（截至紀錄時）。
- 正式翻譯完成需驗證 `翻譯QA紀錄` 真正增加與 Drive TXT/SRT/JSON，之後再用已授權的 Kaggle CPU Natural TTS 校驗 MP3/WAV/manifest；該步驟此時**尚未交付新成果**。
- 遠端 Desktop Commander 月額度已達上限（連線仍在），本輪沒有嘗試重連或重置 OAuth。切勿重派相同來源造成互蓋或稱宣傳 run 成功等於 64 音檔完成。

### 15:33 QA 再次核對

- 中央 `翻譯QA紀錄` 共有 **13 個非英文 passed**：在原 10 語之外，第2堂新增 `km`、`bn`、`ne`。這 3 語尚未在 Drive `02_翻譯稿` 發現正式 TXT，也沒有新的正式 MP3；須等 Kaggle 核實上傳後才能累計成果。
- [翻譯 worker #41020040604](https://github.com/staney41011/SoulKey/actions/runs/41020040604) 仍在執行，對應 P259-L02 `running`，其餘五筆 `queued`。
- [Kaggle TTS 工作 #41020375986](https://github.com/staney41011/SoulKey/actions/runs/41020375986) 顯示 GitHub `success`，但 GitHub 紀錄僅證實 `KernelWorkerStatus.QUEUED`；無 Kaggle 實際結果或 Drive 新 MP3 的證明，因此**不增加正式配音計數**。

### 15:30 實際執行續報

- [GitHub 正式翻譯 run #41020040604](https://github.com/staney41011/SoulKey/actions/runs/41020040604) 成功由原本禁止的 push 改由合法 workflow_dispatch 啟動，Sheet 第2堂翻譯工作已顯示 `running`。
- 第2堂 **柬埔寨文 km 新增 `翻譯QA紀錄 status=passed`**，合計非英語 AI QA 從 **10/60 → 11/60**；此時仍未完成 Drive TXT / MP3 讀回驗收。
- 另已派送 [P259 Kaggle Natural TTS run #41020375986](https://github.com/staney41011/SoulKey/actions/runs/41020375986)，Kaggle API 提交 `Kernel version 2 successfully pushed`，當下讀到 `KernelWorkerStatus.QUEUED`。**GitHub job 成功僅指 kernel 已提交，不代表配音輸出成功**。請查 Kaggle `COMPLETE` 和 `TTS_DRIVE_VERIFIED` 後再計算新增 MP3；缺來源或 OAuth 失敗不能變成虛假的 done。
- 音檔入口：[Kaggle SoulKey P259 Natural TTS](https://www.kaggle.com/code/cwlmrcsir/soulkey-p259-natural-tts-emergency)。保留原 Google OAuth/Sheet/Drive 檔案；勿因救援啟動而重複派相同批次。

---


## 2026-10-30｜第259期「有 MP3、沒有逐字稿」根因及修正

**使用者發現**：第2堂 `05・檔案總覽` 中，有英文／泰文／西班牙文／印尼文正式 MP3，卻只有中文及英文 CC 兩份原始文稿。

**實際查核**：
- 第259期四堂 `02_翻譯稿` Drive 資料夾均空，屬實，並非只被前端隱藏。
- 中央 Sheet `英文定稿索引 + 英文定稿備存 + 多語翻譯結果 + 翻譯QA紀錄` 中已有來源受驗證的英文定稿與 10 個 AI QA 通過語言。既有 `central_tts_recovery.py` 直接讀中央表生成音檔，不會將來源寫成 Drive 正式 `.txt/.srt/.json`；而 `cloud-bridge/drive-overview.js` 只顯示 Drive 真實 `.txt`，因此會「有 MP3、沒有逐字稿」。
- AI QA 10/60：L01 `th,es`；L02 `th,es,id,vi,hi,ta,ja,ko`；L03/L04 暫無 QA pass。四堂人工英文定稿另驗證。**其餘語言不能憑空生成**，Gemini HTTP 429 尚待恢復。
- 14:04（Asia/Taipei）中央 TTS 表：L01 英、泰、西已 `done`；L02 英、泰、西、印尼、越、日已 `done`，印地語與泰米爾文為 `needs_review`（試聽音檔、未列正式交付）；韓文正在跑。以上時間為歷史快照，後續以最新 Drive 為準。

**程式修復**：[PR #26](https://github.com/staney41011/SoulKey/pull/26)，合併主程式。新增 `translation-system/central_manuscript_export.py`，依現行的英文定稿版本及完整翻譯QA核對，對每個已驗證語言匯出人可閱讀 `.txt`、`.srt`、`.json`，上傳課堂 `02_翻譯稿`，逐檔讀回核驗；如果 Drive 既有文件內容不符，**不覆寫**。正式 TTS 救援流程新增「配音前先同步文稿」，`central_tts_recovery.py --period 259 --export-only` 可做純文稿補同步，不需要再產生 MP3。專用 regression tests 和 GitHub Studio CI 通過。

**重要部署界線**：原 12:18 啟動的 Kaggle Web Job #41002147166 在修復 PR 前已 clone 程式，**不會自行更新成 #26 的新版程式**。PR 合併成功不等於 TXT 已上傳；目前四個 `02_翻譯稿` 仍需新的已授權 Kaggle 執行才能實際回填。避免 TTS 進行中重複派工或覆蓋。使用者不需要重做已完成的翻譯或重新 Google 授權。

**自動補交付設定**：[PR #27](https://github.com/staney41011/SoulKey/pull/27) 新增 `.github/workflows/p259_manuscript_backfill_after_tts.yml`，只監測 12:18 的 `Kaggle Web Job #41002147166` 第一次完成事件，然後透過 GitHub Actions API 只重跑原 `launch` job 一次。原 job 的授權輸入由 GitHub 保留，Kaggle 引導程式會 clone 新版 main（包含 #26 的中央文稿匯出），已驗證的 MP3 會重用而不重算。此自動化設有 `run_attempt == 1` 限制，避免循環觸發。**已設定 ≠ 已執行**；必須檢查後續 Workflow 是否啟動、原 runtime nonce 是否仍有效、Drive `02_翻譯稿` 是否真的出現 TXT/JSON/SRT。若原 nonce 超過 8 小時，可能無法自動成功，須以錯誤日誌判斷，不可宣稱成功。

**待辦 / 驗收**：
1. 先等 #41002147166 結束或確認中斷，核對正式 `tts:<lang>` 和 Drive MP3/preview 分別有幾組。
2. 透過**原已授權 Kaggle Bridge**執行新版文稿同步（純文稿 `--export-only` 或新版同一 rescue stage，已完成 MP3 會重用、不重算）。不得用缺憑證的新 Kaggle Notebook 取代。
3. 逐堂驗證 `02_翻譯稿` 對每個合格語言都有 TXT/SRT/JSON，且在 Studio `05・檔案總覽` 看得到 TXT。人工英文定稿和 AI QA 不可混淆。
4. 剩下未通過 QA 的語言須先排除 Gemini 429、完成翻譯 + QA，才可以送 TTS；不偽造文字/音檔。最終交付仍為 64 組文稿 + 64 組音檔。

---


## 最新驗收更新｜2026-10-30 13:27（Asia/Taipei）

> **本節比下方 12:21 的原始快照更新。** 完成數量是此時點的確認數字，正在持續運算，切勿用此數字假裝最終交付。

- [Kaggle Web Job #41002147166](https://github.com/staney41011/SoulKey/actions/runs/41002147166) 仍為 **in_progress**，GitHub `Run Kaggle job with GPU retry` 執行中。不得重複按配音派工。
- **Google Drive `04_音檔` 現有 6 組正式非空 MP3 + WAV + TTS 清單 + 對齊報告**（L01 3 組、L02 3 組、L03/L04 尚未有），中央狀態均有 `tts:<lang> done` 與「正式 MP3/WAV 與 manifest 已上傳 Drive 並校驗」。
  - **P259-L01**：`en` 12:46:45 完成；`th` 12:52:44 完成；`es` 12:55:46 完成。
  - **P259-L02**：`en` 13:17:10 完成；`th` 13:24:14 完成；`es` 13:27:24 完成。
  - **P259-L02 `id`** 於 13:27:29 開始，快照時仍為 `running`，尚不計完成。
- 實際抽驗 **P259-L02 `es` manifest**：`engine=edge-natural-v2`、`status=done`、來源 `en_backup_revision=d89bd0ee...`、`source_segment_count=53`、MP3 `27,374,253` bytes、WAV `82,119,212` bytes，包含 MP3/WAV MD5 receipts。這是檔案驗收而非單靠 GitHub 綠燈。
- **總交付仍僅 6 / 64 組已驗證音檔**，尚餘 58 組；其他語言還需依各堂翻譯與 QA 條件完成（先前 AI QA 10 / 60、4 組英文人工定稿），Gemini HTTP 429 可能阻礙後續翻譯。不能承諾其餘 58 組在本次工作完成。
- 後續更新請繼續往本頁頂端追加新的日期時間小節，不要覆寫本節，也不要在原始快照默默改數字。對照中央 Sheet `執行狀態` 與 Drive 正式檔案。

---

> **正式接手入口 / 目前狀態快照**。本文件補上 2026-10-30 救援操作的連續紀錄，避免依賴 ChatGPT 對話或個人記憶。
>
> **快照依據**：2026-10-30 台灣時間 12:21 以後，查核 GitHub Actions、中央 Google Sheet、四堂課的 Drive `04_音檔`。文件是**有時間點的人工查核紀錄**，不是會自行更新的即時儀表板。後續以最新工作日誌和 Drive 讀回結果為準。

## 0. 下一位接手者先讀

1. **正在救援**：第 259 期 P259-L01～P259-L04，4 堂 × 16 語 = **64 份目標語言文稿 + 64 組目標配音**。16 語：`en, th, es, id, vi, hi, ta, ja, ko, km, bn, ne, lo, my, it, pt`。
2. **嚴禁把 GitHub 派工成功當作 Kaggle 或音檔交付**。分層判斷：Studio POST → Apps Script 驗證 → GitHub Workflow Dispatch → Kaggle Worker 執行 → 該語完整翻譯 QA / TTS → Google Drive 非空檔案及 manifest readback → Sheet status。
3. **最近授權工作**：[Kaggle Web Job #41103810894](https://github.com/staney41011/SoulKey/actions/runs/41103810894)，2026-10-31 02:05（Asia/Taipei）由原Studio建立新授權。第一次執行因舊映像ABI不符失敗，修正合併後須由原Studio新派工作，避免rerun沿用舊workflow；原#41002147166已過期，禁止重跑舊nonce。
4. **中央紀錄**：本次 `multi / running / web-job_eidS9Rrm / 02:05:41`，02:11明確error。新派工須重新讀回run ID與開始紀錄，不得聲稱翻譯在失敗後仍執行中。
5. **交付最後快照**：QA **30/60**、完整文稿 **34/64**、正式MP3 **18/64**、試聽 **5組**；文稿包含4組英文人工Final。須讀回新的QA、Drive檔案與manifest才增加數量。
6. **注意**：四個GCP workflow已實際disabled，沒有排程或Cloud Run接手。部分語言仍可能需要QA複核；保留既有成果與來源revision，不降低QA或將試聽版標成正式音檔。
7. **安全**：不重設使用者 Google OAuth、原六碼 Bridge Key、Apps Script Script Properties、Drive 既有檔案；不要把 token、金鑰放入此文件、PR、前端或 Sheet。不要未確認工作狀態就再次派送相同救援。

## 1. 現行系統架構（2026-10-31；不使用 GCP 服務）

```text
瀏覽器（iPhone / Android / 桌面）→ SoulKey Studio（GitHub Pages /studio/）
                  ├─ 課程、六碼驗證、狀態、校稿 → 原 Apps Script Studio Bridge → Sheets／Drive
                  └─ ASR / CC / multi / tts 派工 → 同一原 Bridge（驗證 + 短效 runtime nonce）
                                              → GitHub Actions: Kaggle Web Job
                                              → Kaggle kernel: cwlmrcsir/soulkey-gpu-worker
                                              → 舊 translation-system Worker / 中央 Sheet / Google Drive
GCP Translation／CC Queue、kickstart、capability probe：已退役並disabled，沒有另一路常駐服務。
```

- 網頁入口：[SoulKey Studio](https://staney41011.github.io/SoulKey/studio/)
- 正式 Kaggle 工作流程：[.github/workflows/kaggle_web_job.yml](.github/workflows/kaggle_web_job.yml)
- 原 Apps Script 原始碼：[bridge/apps-script/Code.gs](bridge/apps-script/Code.gs)；**GitHub 更新不會自動部署到已存在的 Apps Script Web App**。
- 網頁路由：[studio/config.js](studio/config.js) 和 [studio/app-20260923-48.js](studio/app-20260923-48.js)。
- 中央 TTS 來源/執行：[translation-system/central_tts_source.py](translation-system/central_tts_source.py) / [translation-system/central_tts_recovery.py](translation-system/central_tts_recovery.py)。
- 中央 Sheet：[全球翻譯控制中心](https://docs.google.com/spreadsheets/d/1AwPqTqZSzW7Q-gLW4J5d-28dQZwVksyDnvsxNRF2uu8/edit)（重點分頁：`執行狀態`、`語言任務設定`、`翻譯工作佇列`、`翻譯QA紀錄`、`英文定稿索引`、`英文定稿備存`）。
- iPhone 保留Google獨立分頁POST派工；桌面嵌入回傳於67版修復。不能移除原本可用的手機路徑；真實裝置驗收與桌面測試須區分。
- GitHub／Kaggle工作的成功狀態仍須比對中央Sheet與Drive檔案。執行中避免重複派工，後續只有來源revision相同且已驗證的成果可直接複用。

## 2. 2026-10-30 修復紀錄（台灣時間；PR 為永久證據）

| GitHub PR | 當次修改 | 結果／注意事項 |
|---|---|---|
| [#14](https://github.com/staney41011/SoulKey/pull/14) | 緊急 Kaggle Natural TTS launcher | 已合併；原路線偏向已過 QA 語言，不等於64組全完成 |
| [#15](https://github.com/staney41011/SoulKey/pull/15) | 恢復舊 Kaggle Web Job 路由 | 已合併；不應再把該 workflow 自動改走 GitHub CPU |
| [#16](https://github.com/staney41011/SoulKey/pull/16) | 修 Apps Script / Kaggle 網頁接線、QA來源 TTS、四堂課救援入口 | 已合併；另在中央 Sheet 啟用 P259 四堂 64/64 文稿與音檔設定 |
| [#17](https://github.com/staney41011/SoulKey/pull/17) | 修正過期 CI 規格 | 已合併 |
| [#18](https://github.com/staney41011/SoulKey/pull/18) | 四堂補譯、中央英文定稿同步、第二個救援按鈕 | 已合併；Gemini 429 是外部障礙 |
| [#19](https://github.com/staney41011/SoulKey/pull/19) | 修手機登入卡「同步中」：控制中心讀取與 Kaggle 派工分開 | 已合併 |
| [#20](https://github.com/staney41011/SoulKey/pull/20) | 修救援按鈕誤要求整站都使用 Apps Script | 已合併 |
| [#21](https://github.com/staney41011/SoulKey/pull/21) | 診斷 Apps Script 對 GitHub 無憑證訪問結果 | 已合併；匿名 403 **不得推導**登入 Safari 也 403 |
| [#22](https://github.com/staney41011/SoulKey/pull/22) | 修正無 ACK 的網頁提示 | 已合併；後續 403 根因判定已被使用者實測修正 |
| [#23](https://github.com/staney41011/SoulKey/pull/23) | iPhone 頂層分頁 POST 原 Apps Script | 已合併；12:18:20 **實際出現 GitHub run #41002147166**，因此派工路徑已獲得證據，MP3 尚待驗收 |

### 已釐清的誤判（下一位不要重犯）

- 同一 Apps Script 專案可以有多個部署 URL。使用者提供之「SoulKey public web」網址與 `studio/config.js` 的舊 Bridge 一致，**不是網站指錯網址**。
- GitHub 無憑證 GET 原 Apps Script 曾得到 HTTP 403，但使用者 Safari 直接開啟同一 URL 得到 JSON `{"ok":true,"message":"bridge-ready","bridge_protocol":9,...}`。因此**不能單憑該 403 要求重新授權或重建部署**。
- iPhone Google 獨立分頁僅顯示 `SoulKey response` 不代表成功；**同時存在 GitHub workflow_dispatch #41002147166 才是派工成功的證據**。
- Studio 讀取走 Cloud Run，不等於多語翻譯 / 音檔計算也走 Cloud Run。勿混淆控制層與運算層。
- 先救已通過 QA 的配音；其餘語言須按正確英文來源 revision 補翻譯+QA，最後才可製作音檔。

## 3. 交付與驗收表（快照，非即時）

| 課程 | 目標語言 | 已通過 AI QA | 已驗證正式 MP3 | 備註 |
|---|---:|---:|---:|---|
| P259-L01 | 16 | 2 / 15 | 0 / 16 | 12:21 `tts:en` 開始執行，尚無 Drive 讀回 |
| P259-L02 | 16 | 8 / 15 | 0 / 16 | Gemini 429，既有 QA 不重做 |
| P259-L03 | 16 | 0 / 15 | 0 / 16 | Gemini 429 |
| P259-L04 | 16 | 0 / 15 | 0 / 16 | Gemini 429 |
| **合計** | **64** | **10 / 60** | **0 / 64** | 另有 4 組人工英文定稿需按其來源確認 |

**交付完成定義**：每一 `task_id + lang` 必須有符合來源版本的正式文稿/翻譯 QA（英文用人工定稿）、非空 MP3、必要時 WAV、manifest 與 Google Drive metadata/readback。中央狀態 `done` 或合適的 `needs_review` 應有可核對證據；不能因 Actions 工作綠燈、`running` 或 `SoulKey response` 就算已交付。

## 4. 當前優先工作與禁止事項

1. **先追** [run #41002147166](https://github.com/staney41011/SoulKey/actions/runs/41002147166) 的 Kaggle kernel 狀態與實際 log：是否 `COMPLETE`、Google 授權可用、哪個語言產出 MP3，並回到 Drive / Sheet 逐項核對。**避免於此 job 執行中重複派工**。
2. 若遇到 Drive OAuth 或來源缺失，記錄確切 error、影響語言、原始 run 與已保存成果；不要推測 OAuth 全部失效或向使用者索取密碼。
3. Gemini 429：使用有上限的冷卻及續傳；保留 QA 與 source revision，禁止密集無限重試、重新產生已通過 QA 的翻譯。
4. **恢復跨裝置一致操作**須另設安全的伺服器端派工/ACK，顯示真實 GitHub run ID，經實測後才能移除 iPhone 頂層分頁臨時方案。不得直接拔掉目前唯一已被證實可送達的路線。
5. 使用者無需重新部署 Apps Script、重建六碼或再次授權，除非最新日誌已明確證明必須，且已有可復用舊設定的修復方案。

## 5. 文件維護規則（不再只靠對話記憶）

- **每次修程式的 PR**：同 PR 更新此文件的「修復紀錄／目前風險／驗收結果」；列明 PR、commit、使用者可見影響、回退方法與測試。不能只回報「修好了」。
- **每次正式工作**：記 `run_id`、啟動方式、開始／結束、工作模式、成功/失敗、Drive 輸出及讀回連結；即時資料以 GitHub Actions + Sheet + Drive 為準。本 MD **需要人或未來正式自動化程序更新**，不會因監測排程自動改寫。
- **每次接手**：先看本文件，接著核對最新 GitHub run / Sheet / Drive，不能直接拿本文件的歷史數字宣稱「現在」。
- **現存歷史文件**：[`cloud-bridge/RECOVERY_2026-10-30.md`](cloud-bridge/RECOVERY_2026-10-30.md) 是早期狀態快照；[`cloud-bridge/RELEASE_AUDIT_2026-10-29.md`](cloud-bridge/RELEASE_AUDIT_2026-10-29.md) 是遷移缺失稽核；[`translation-system/WORKFLOW_REQUIREMENTS.md`](translation-system/WORKFLOW_REQUIREMENTS.md) 是規格。三者不能取代本頁的 259 期最新操作日誌。
- **隱私／安全**：不記錄六碼 Bridge Key、GitHub PAT、OAuth refresh token、Cookie、私人授權連結或任何完整秘密。只記錄可供授權人員查核的程式與 run/工作表參照。


## 2026-10-30 17:08（台灣）｜第259期由 Gemini 切換 Kaggle Gemma 4

- 使用者要求直接切換，不再等待 Gemini API 限流。已新增 [Gemma4 翻譯／本地語意 QA 與分語言 Drive 寫回](translation-system/p259_gemma4_kaggle.py)，來源限定 P259 四堂人工英文 Final、保留 SHA 來源核對與已通過的舊 QA。模型預設官方 Kaggle `google/gemma-4/transformers/gemma-4-12b-it`、4-bit GPU；此模式不發出 Gemini API 呼叫。
- [GitHub Gemma4 Kaggle 派工流程](.github/workflows/p259_gemma4_kaggle.yml)：首次 [#41030385258](https://github.com/staney41011/SoulKey/actions/runs/41030385258) 因 Kaggle `model_sources` 未帶版本號被拒，已修正為 `.../1`。第二次 [#41030516253](https://github.com/staney41011/SoulKey/actions/runs/41030516253) 成功推出 Kaggle Notebook v1；這僅是成功提交，不是完成翻譯。
- [Kaggle Notebook](https://www.kaggle.com/code/cwlmrcsir/soulkey-p259-gemma4-translation) **已實際執行但在 Google OAuth 前置檢查失敗**：`RuntimeError: 找不到 Secret: GOOGLE_CLIENT_ID`，翻譯未啟動、沒有任何 Gemma 4 交付成果。從 [read-only Kaggle 狀態查詢 #41031073162](https://github.com/staney41011/SoulKey/actions/runs/41031073162) 的實際 kernel log 驗證。重點：Kaggle API `kernels push` 不會附掛 Notebook UI 的 Secrets（Kaggle CLI 仍無自動指定 Secret 功能）；不要再次誤報「已在跑」。
- 中央 Sheet `翻譯工作佇列` **F13:F15** 舊 Gemini `queued` 已改為 `gemma4`（J13:J15 說明接手），未刪除紀錄、不改為假 `done`；未取得正式成果前不宣稱完成。現有 GitHub Gemini worker 對 P259 的後續舊佇列重試設有 Gemini API 禁用保護（`cloud-bridge/translation_worker.py` + `soulkey_translation_queue.yml`），其他期數未切換。
- 17:04 中央 QA 查到 P259 **24/60 非英語 passed**（L01 6、L02 13、L03 5、L04 0），主要由之前 Gemini 工作者完成；**不能歸功 Gemma**。已驗證正式 MP3 最後基線仍是 11/64，沒有 Gemma 4 新文稿／新音檔交付證據。
- **解除真正阻礙的安全下一步**：由帳戶持有人在上方 Kaggle Notebook 網頁開啟 Edit → Add-ons → Secrets，授權已存在的 `GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、`GOOGLE_REFRESH_TOKEN` 給該 Notebook，接著用 Kaggle 網頁 Save & Run All（**不是**再用 GitHub `kernels push`）。勿把 Secrets 內容貼入聊天、GitHub 原始碼、Kaggle 程式碼或 Logs。完成後以 Kaggle 記錄及中央 Sheet / Drive readback 實際驗收。


### 2026-10-30 17:19（台灣）｜已勾選 Kaggle Secrets，API 重送仍無法帶入

- 使用者已在 Kaggle Notebook 啟用三項 Google OAuth Secrets；不要求重新勾選。
- 已重跑 [Gemma4 派工 #41031483823 attempt 2](https://github.com/staney41011/SoulKey/actions/runs/41031483823)。GitHub 僅成功提交新 Kaggle 版本。
- [Runtime status #41031073162](https://github.com/staney41011/SoulKey/actions/runs/41031073162) 追查後，Kaggle kernel 從 RUNNING 轉成 ERROR，仍於 GOOGLE_CLIENT_ID 讀取失敗；沒有任何新增的 Gemma 文稿或音檔驗收證據。
- 根因：Kaggle CLI kernels push 不會把 Notebook 網頁已授權的 Secrets 附掛至新的 API 派工版本。已核對 Kaggle CLI 文件及官方討論，禁止把憑證字串寫入 GitHub / Notebook 原始碼。
- 唯一尚需使用者執行的操作：在 [同一個 Kaggle Notebook](https://www.kaggle.com/code/cwlmrcsir/soulkey-p259-gemma4-translation) 開啟 Edit，保留 GPU，按 Save Version → Save & Run All。**不要再由 GitHub API push**，以免再產出未附 Secrets 的版本。之後核對 Kaggle 真正 Log、中央 Sheet、Drive。


### 2026-10-30 17:42（台灣）｜正式修復第259期 Gemma4 授權接線（非交付宣告）

- **已修正根因**：第259期原本獨立 Kaggle Gemma Notebook 透過 CLI push 無法取得 Kaggle Secrets，正式路徑已改為 Studio 既有 `run_stage(task_id=P259-L01,stage=multi,lang=central4)` → 原 Apps Script Bridge 產生 8 小時 runtime nonce → `kaggle_web_job.yml` → `web_job_worker.py` 取得短效 `GOOGLE_ACCESS_TOKEN`、`SOULKEY_BRIDGE_URL`、`SOULKEY_RUNTIME_NONCE` → GPU `p259_gemma4_kaggle.py` → 中央 Sheet/Drive 正式文稿 → `central_tts_recovery.py` Edge TTS。**不再要求 Kaggle Notebook 的 Google Secrets，翻譯與本地 QA 不呼叫 Gemini API**。
- `translation-system/web_job_worker.py` P259 的 `multi`（含 `central4`）改走 Gemma 4；原 Gemini central4 分支已移除；其他期數未變。補正 GPU preflight 不再為 Gemma4 強制要求 CTranslate2。
- `.github/workflows/kaggle_web_job.yml` 只有 P259 multi 改用 T4 GPU、掛載 Kaggle 官方 `google/gemma-4/transformers/gemma-4-12b-it/1`、4h 工作時間；原 Apps Script workflow_dispatch/nonce 機制保持不變。
- `translation-system/p259_gemma4_kaggle.py` 固定上述模型版本並採用 Gemma4 官方 Transformers processor chat template。保留已通過 QA 的來源 SHA，失敗語言隔離，語言獨立寫回；只對通過 QA 的來源進行 Edge TTS。
- `studio/app-20260923-48.js` 第259期四堂補譯救援按鈕確認文字更新為 Gemma4，原使用者操作入口不更動，無須重部署 Apps Script。
- **測試**：[GitHub P259 Gemma4 Bridge Integration Check #41035224870](https://github.com/staney41011/SoulKey/actions/runs/41035224870) 已成功（`py_compile`、純函數 self-test、Bridge OAuth 接線、GPU/模型版本一致性）。這是靜態／離線整合測試，**不是 Kaggle GPU 實際模型載入與翻譯交付驗收**。
- **下一個必需動作**：由已登入 Studio 的使用者按一次「第259期四堂課補譯」啟動原 Apps Script Bridge 的新 runtime nonce，GitHub 才能取得有效短效 Google Token；不可重用舊 nonce、不可從 log 挖取憑證、不可再用獨立 `p259_gemma4_kaggle.yml` 的失敗型直接派工。確認 GitHub Kaggle Web Job 的新 run ID、Kaggle 真正 log，以及中央 Sheet `翻譯QA紀錄` 和 Drive 的新增 TXT/SRT/JSON/正式 MP3 才能宣告交付。


### 2026-10-30 18:12（台灣）｜四堂缺漏 36 語：GitHub OIDC → 私有 Kaggle Gemma4 12B

- 第259期英文 Final 四堂 SHA 未改，原有 24/60 個非英文 QA passed、14/64 正式文稿、11/64 正式 MP3 保留。
- 第259期剩餘 36 個語言集合已按課程拆成 13 組，寫入中央 Sheet「翻譯工作佇列」第16至28列，依序先 L02 it/pt、再 L01、L03、L04。每組最多 3 語；沒有改寫已通過 QA 的內容。
- 新的 [P259 Kaggle Gemma4 relay](cloud-bridge/p259_gemma4_relay.py) 使用 [正式 OIDC Worker](.github/workflows/soulkey_translation_queue.yml) 先經既有 Cloud Run 的 worker_job_claim 取得英文人工 Final 與來源 revision；只把講稿與 glossary 放入**私人** Kaggle kernel，**不放 Google 密碼、Gemini Key 或 OAuth token**。GitHub 透過短效 OIDC 將 Kaggle 的本地 QA 翻譯寫回 Cloud Run，並確認語言完整與來源版次才記 passed。部署中 Cloud Run QA 模型欄正規式仍只接受 gemini-*，暫用明示的兼容傳輸標籤 gemini-compat-gemma4-12b-it-localqa，**實際執行 Gemma4 而非 Gemini**，此欄須日後同步修改服務端 schema 才能恢復原生 model provenance。
- [第一次 OIDC run #41037581687](https://github.com/staney41011/SoulKey/actions/runs/41037581687) 成功從中央領取 L02 it/pt，但 Kaggle model attachment 被平台拒絕，實際 kernel 名稱也被 title slug 改成 private-relay；已用專用 workflow 正式取消舊 run 並將同一工作安全復歸 queued，未寫任何假 QA。
- 已改用 Google 官方公開 [Gemma 4 12B QAT GGUF](https://huggingface.co/google/gemma-4-12B-it-qat-q4_0-gguf) 由 Kaggle 網路直接下載，於 GPU 上編譯 llama.cpp 本地推論，不再要求互動式 Kaggle 模型附掛。
- [重新派工 GitHub run #41038849680](https://github.com/staney41011/SoulKey/actions/runs/41038849680) 已啟動；[Kaggle Notebook](https://www.kaggle.com/code/cwlmrcsir/soulkey-p259-gemma4-relay) 於約 18:11 台灣時間回報 **KernelWorkerStatus.RUNNING**，這只表示已在運行，**尚未證實 GGUF 模型載入、當堂翻譯完成、Cloud Run QA passed 或 Drive 檔案交付**。
- 其他阻礙：GitHub Actions 並沒有受保護 Google OAuth 三項 Secrets；原 [Drive/Edge TTS 直接救援 #41036554143](https://github.com/staney41011/SoulKey/actions/runs/41036554143) 在前置授權檢查安全失敗。Cloud Run 授權目前僅有 Drive readonly，不能假稱它可直接上傳 MP3。要完成四堂 64 組音檔，仍需恢復現有 Apps Script Bridge 的授權配音路徑，或由使用者正式設定適用的受保護憑證，不能把配音自動完成當作已成功。
- 舊的「P259 Secure Gemma4 Relay Static Check」在切換成 Hugging Face GGUF 後仍驗證過時的 Kaggle model_sources 掛載，該 CI 已失敗，並非運行 GGUF 模型的實測錯誤；需更新測試。


### 2026-10-30 19:46（台灣）｜第259期四堂加速交付／實際成果（非全部完成）

- 重新核對中央 Sheet：四份人工 English Final 已確認；非英文 QA passed **24/60**（L01 6、L02 13、L03 5、L04 0），至此仍未觀察到新的 Gemma QA passed。
- Kaggle GGUF 現況：前版 T4 GPU 成功辨識，但 1100 秒從零編譯 llama.cpp 逾時。新版本採用官方 [llama.cpp b11988 CUDA12.8 預編譯](https://github.com/ggml-org/llama.cpp/releases/download/b11988/llama-b11988-bin-ubuntu-cuda-12.8-x64.tar.gz)；首次解壓被過嚴的 symlink 安全檢查誤擋，已修正並重派。後續 [GitHub #41047898408](https://github.com/staney41011/SoulKey/actions/runs/41047898408) 持續執行，尚無完整模型推論或中央 QA 交付證據。缺漏 36 組翻譯仍以 Cloud Run OIDC → 私有 Kaggle 模型安全續跑；不向 Kaggle 傳送 Google OAuth 密鑰。
- 另外新增 [28組來源核對的 Natural Edge TTS 預覽輸入](translation-system/p259_approved_audio_source.json)（L01 7、L02 14、L03 6、L04 1，包含四份英文 Final）。[四堂獨立配音 Workflow #41048498342](https://github.com/staney41011/SoulKey/actions/runs/41048498342) 已啟動；缺漏語言仍須等本地翻譯 QA 通過才可加入配音，不允許臆測翻譯。
- **第一個已驗證成果**：L04 英文 Edge TTS MP3 23,506,220 bytes、來源 English Final SHA \`17354f093b3719df30fcd4e87c9943f3dfc9485c89b8dc5ca0c8255648354eb7\`，GH [L04 產物 #41048498342](https://github.com/staney41011/SoulKey/actions/runs/41048498342) 成功。已將大 Zip 重包為 22,362,606 bytes，經已連接的 Google Drive 上傳並移至第259期總資料夾 [試聽包（非正式）](https://drive.google.com/file/d/1haZ8MNHCeYLeQNqilcEdbsOkoB7j5TBB/view)，Drive list_folder readback 確認存在。**此為試聽版，不能計為已驗證原片長度的正式 MP3。**
- 既有官方正式文稿/音檔基線依前次實際核對仍為 **14/64 與 11/64**；未因 GH 工作綠燈或新試聽 ZIP 增加為正式完成。除第4堂英文試聽之外，其他三堂配音還在獨立執行，保留缺漏及失敗審核紀錄。
- 已新增 [配音完成後壓縮小包的工作](.github/workflows/p259_compact_completed_previews.yml)，各包預期低於 Google Drive 單次 connector 100MB 下載限制，以免不能移交 Drive。需等待來源 GH 完成並以實際 artifact／Drive readback 驗收；這不是四堂已完成的宣告。

### 2026-10-30 21:20（台灣）｜接手第259期：Drive 實際交付與尚未驗收關卡

- 使用者要求直接接手完成四堂。最新中央 `翻譯QA紀錄` 核對仍 **24/60 非英文 passed**：L01=6，L02=13，L03=5，L04=0；另四份人工英文 Final 均保留。**沒有可驗證的新增 Gemma 正式 QA pass**，不能冒稱 60/60。
- [GH 4 堂 Edge TTS preview #41048498342](https://github.com/staney41011/SoulKey/actions/runs/41048498342)：L01 7/7、L02 13/14（泰文 TTS block 17 No audio）、L03 6/6、L04 1/1，合計 **27/28** 可用來源試聽。
- **本輪已實際交付**：從 [GH compact #41054425922](https://github.com/staney41011/SoulKey/actions/runs/41054425922) 下載 L01 4包、L02 7包、L03 3包，共 **14 個試聽 ZIP**，全部透過已連接 Google Drive 上傳至 [第259期 98_人工檢查](https://drive.google.com/drive/folders/1oBBGr6mLHE1YgH2GDZHRIEX6fMN9Y424) 並使用 `list_folder` 讀回確認；L04 1包英文試聽則已在 [第259期總資料夾](https://drive.google.com/file/d/1haZ8MNHCeYLeQNqilcEdbsOkoB7j5TBB/view) 驗證，合計涵蓋 27 組音檔。**都是非正式試聽，未完成原片時長驗收**。
- **本輪新增文稿保全**：`translation-system/p259_export_approved_bundles.py` 使用現有 `central_manuscript_export.manuscript_files` 僅匯出 28 組核可來源×JSON/TXT/SRT=84 份文字檔；[GH #41061731010](https://github.com/staney41011/SoulKey/actions/runs/41061731010) 成功。四堂各一 ZIP 均上傳上方 98_人工檢查，Drive readback 已確認：L01=1zCqNyZppkkKyJClz6di8FkGMFwJzeb_v；L02=1JvXguXMWl1M8z-sdT59uwiO9OY11FUnV；L03=1aP5KM5xUcKt-Qsjq3Ch1dPw71GD_en2J；L04=1qg1Ess_uwEOWQTIdzUFTpnpYbqOob2r_。這是補救備份，不代表正式 `02_翻譯稿` 已逐檔完成。
- **泰文獨立補救**：[GH #41061359807](https://github.com/staney41011/SoulKey/actions/runs/41061359807) 已啟動，僅對 L02 Thai 重配，不重做另13語；輸出以 workflow artifact 與 Drive 讀回驗收。
- **Gemma 補譯**：真 Kaggle JSON grammar smoke（義大利文、葡萄牙文一段）完成，但 [Kaggle P259 GGUF relay](https://www.kaggle.com/code/cwlmrcsir/soulkey-p259-gemma4-relay) 最先的 L01 ja/ko/km 因長句 QA 失敗，未 falsely pass。已將 `p259_gemma4_kaggle.py` 的重譯次數提高為5輪、對長句增加最大新 token、輸出 QA failure reasons，離線 Bridge 整合測試 [#41062204407](https://github.com/staney41011/SoulKey/actions/runs/41062204407) 通過；L01 ja/ko/km 重新排隊。另 [Worker #41061398456](https://github.com/staney41011/SoulKey/actions/runs/41061398456) 正處理 L02 it/pt，後續應由 bounded workflow_dispatch 續跑；**不能稱四堂已完成**。
- 正式 Drive 基線需重新核對，最後一次確認為文稿14/64、音檔11/64，試聽 ZIP 和核可文字備份不列入正式完成數。

### 2026-10-30 21:30（台灣）｜Drive 正式資料夾再驗收與泰文停止重試依據

- 逐堂直讀 `02_翻譯稿`：L01=21檔(7語×3)、L02=42檔(14語×3)、L03=6檔(2語×3)、L04=3檔(1語×3)，**已在正式資料夾的語言組合計24/64**；其餘核可文字稿另已備份於 `98_人工檢查` 的4 ZIP，不代表正式逐檔交付。
- 逐堂直讀 `04_音檔`：正式命名 `TTS音檔.mp3` L01=5、L02=12、L03=1、L04=0，**計18/64**；另 `自然試聽版.mp3` 不算正式。L02 **泰文正式 MP3 已存在**，所以不可把單獨試聽重配失敗等同正式泰文缺漏。
- [L02 Thai 單語預覽重試 #41061359807](https://github.com/staney41011/SoulKey/actions/runs/41061359807) 在 Edge block43 `No audio was received` 失敗；第一次試聽批次 block17 失敗，屬不穩定上游 Edge TTS。既有 L02 Thai 正式 MP3/WAV + Manifest 應優先沿用，暫勿無限重配。
- L04 `00_來源資訊` 資料夾目前為空，其他三堂均有原始 `來源資訊.json` 含精確 duration（L01 1941s、L02 1799s、L03 1813s）。L04 缺原始影片長度的可驗證資訊，不能把英文自然試聽 MP3 當正式 MP3。
- GitHub [Gemma4 整合測試 #41062204407](https://github.com/staney41011/SoulKey/actions/runs/41062204407) 成功，新版 QA 長句重譯 5 輪已編入主分支；當前 [翻譯工作 #41061398456](https://github.com/staney41011/SoulKey/actions/runs/41061398456) 正在執行 L02 it/pt，下一組 L01 ja/ko/km 已根據修復重新排隊；截至最新 Sheet QA 仍24/60 非英文 passed。


### 2026-10-30 22:50（台灣）｜第259期直接修復 QA 誤判、TTS 空音與佇列跨語綑綁

- 正式修訂 `translation-system/p259_gemma4_kaggle.py`：五輪翻譯修復後的 **語意疑似誤判** 可做逐句獨立 Gemma 判讀；確定的語言錯誤、數字不符、重複文字、英文照抄仍嚴格擋下；不因 GitHub workflow success 冒稱語言通過。
- `translation-system/test_p259_gemma4_repair.py` 新增五種離線 regression tests：正常成功、獨立核准語意誤判、硬性錯誤不可放行、uncertain 不可放行、material_issue 不可放行。由 [Gemma4 Bridge Integration Check #41073727928](https://github.com/staney41011/SoulKey/actions/runs/41073727928) 在 GitHub 全數測試通過。
- `translation-system/natural_tts_edge.py` 對 Edge TTS 的 No audio was received 採六次新的相同語音請求與遞增冷卻，403 不再無謂重試，不以靜音偷補發話段。新的 [P259-L02 泰文單語試聽 #41074221474](https://github.com/staney41011/SoulKey/actions/runs/41074221474) 已真正進入音訊生成步驟；尚需等待 artifact 驗收，不能算正式音檔。
- 已把先前失敗的 **L02 it、L01 ko/km/bn/ne/lo** 六組拆為單語重試工作，寫進中央「翻譯工作佇列」並回讀確認；來源英文 SHA 不變。
- 再把 L03/L04 尚未領取的八筆多語合批拆分，保留原八筆成單語並增列16筆。**中央回讀驗證31筆 queued 全為單一語言，且沒有重複 queued language**（L03十語、L04十五語、L02一語、L01五語）。正在執行中的原批次沒有修改。
- 目前實際中央 QA 為 **26/60 非英文**，不是 60/60；正式 Drive 文稿、MP3 尚未驗收增加。本次代表已完成可靠性修復及進行單語重試，**不是四堂64份正式文稿/64組音訊完成**。


### 2026-10-30 23:15（台灣）｜四堂完整交付：新 GitHub OIDC → 原 Natural TTS → 正式 Drive 接線

**已實際寫入 GitHub main 的程式，不等於已部署 Cloud Run。**

- 新增 `cloud-bridge/server.js` 專用 `worker_drive_runtime`：只有 GitHub main 的 [soulkey_p259_final_delivery.yml](.github/workflows/soulkey_p259_final_delivery.yml) 工作經 repo+ref+event+workflow-restricted OIDC 才能取得短效 Google token；先對第259期四堂翻譯稿和音檔的八個資料夾驗證 canAddChildren。優先沿用**原有 Cloud Run 保護的 owner OAuth**，如果不存在才使用具 Editor 權限的 Cloud Run service identity；不向 Kaggle 傳送任何 Google token/refresh secret。
- 新增 `CloudRunOIDCCredentials` 在 `translation-system/google_io.py`，GitHub Actions 每次 token 過期可重新取得 repo OIDC，讓既有 `central_tts_recovery.py`、`central_manuscript_export.py`、`tts_runner.py` 直接使用源版本／翻譯 QA 查核、正式字幕與 Natural Edge 配音及 Drive MD5/內容回讀。
- 新增 [soulkey_p259_final_delivery.yml](.github/workflows/soulkey_p259_final_delivery.yml) 定時／手動正式交付：每輪最多1、2、4組新音檔，既有文稿/音檔核可項會沿用；定時工作由 `SOULKEY_P259_DELIVERY_READY=true` **安全閘門**控制，尚未在雲端授權成功前不應開啟。
- 新增 `p259_source_duration_restore.py`：第4堂僅在影片 URL 與重新查證 YouTube ID 完全一致、有效取得原片長度時，才寫入 source_info.json 並回讀；失敗不假定視頻時長。新增 `p259_delivery_audit.py`，嚴格檢查4×16來源 SHA、QA、Drive JSON/TXT/SRT bytes、正式 MP3/WAV/manifest SHA/MD5+片長。未滿全部64不得回報完成。
- 新增 CI [P259 Delivery OIDC and Drive Source Safety Check #41078497715](https://github.com/staney41011/SoulKey/actions/runs/41078497715) **success**，涵蓋 OIDC 認證隔離、短效刷新與拒絕錯誤權限、原始 YouTube ID、定稿來源、程式編譯與工作安全閘門。新 [Gemma4 relay 靜態測試 #41078827942](https://github.com/staney41011/SoulKey/actions/runs/41078827942) **success**；翻譯已通過 QA 語言將跨工作沿用，避免再浪費一次 GPU。
- **已確認真正阻礙**：[CI #41078123942](https://github.com/staney41011/SoulKey/actions/runs/41078123942) 從 GCP Cloud Run 的公開版本端點讀回部署的 **舊 SHA `7ad3d5af3936bb989aeef70f92169c08c26cd5a9`**，不是新的 main 交付版；GitHub 程式提交並不部署 GCP。Remote Desktop Commander 遠端呼叫餘額 **0%**，本回合沒有 GCP 管理權限，不得宣稱已部署或已完成正式寫回。
- 一次性部署命令已在 [cloud-bridge/README.md](cloud-bridge/README.md)：使用既有已登入 Google Cloud Shell 的 SoulKey Git checkout 執行 `git pull --ff-only && bash cloud-bridge/deploy-from-cloud-shell.sh`，保留現有 Bridge Key/OAuth 設定，部署後驗證 build SHA，確定 Drive Owner OAuth 或 Cloud Run SA 對第259期八個文字/音檔資料夾具 Editor；再手動執行新交付 workflow **export_only=true** 一輪核對文稿是否真的寫回；確認後設置 GitHub Actions Variable `SOULKEY_P259_DELIVERY_READY=true` 啟用每兩小時定時正式輸出。
- 截至本回合最後核對，中央**非英文 QA 已由26提升至28/60**（四份英文 Final 已核可，餘32非英文）；24／64 正式文稿與18／64正式 MP3是先前最後一次「實際正式資料夾逐檔」核對數字，本回合尚無新的正式檔案回讀，因此不得宣稱已提高。新正式交付工作在 GCP 部署/權限驗證前尚不可運作。
