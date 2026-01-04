const fs = require('fs');
const https = require('https');
const path = require('path');

// 您的 API 網址
const API_URL = 'https://script.google.com/macros/s/AKfycbwvNwOn8QwvH-agggTWm6ZZUosmCPDuGUpSbckc8DFahBP9fiHLfPCBCIlWMt9p4V3V/exec?type=json';
const IMG_DIR = 'images';

// 確保 images 資料夾存在
if (!fs.existsSync(IMG_DIR)){
    fs.mkdirSync(IMG_DIR);
}

// 【通用函式】支援所有轉址 (301, 302, 303, 307)
const fetchWithRedirect = (url, callback) => {
  https.get(url, (response) => {
    // 檢查狀態碼是否為轉址 (3xx)
    if (response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
      // console.log(`>> 偵測到轉址 (${response.statusCode})，正在導向新網址...`); 
      // (註解掉避免 Log 太多，只保留關鍵訊息)
      return fetchWithRedirect(response.headers.location, callback);
    }
    // 正常回傳
    callback(response);
  }).on('error', (err) => {
    console.error("連線錯誤:", err.message);
    process.exit(1);
  });
};

console.log(`[1] 正在連線至 API...`);

// 1. 抓取清單
fetchWithRedirect(API_URL, (res) => {
  let body = "";
  res.on("data", (chunk) => { body += chunk; });
  res.on("end", () => {
    try {
      // 解析 JSON
      let json;
      try {
        json = JSON.parse(body);
      } catch (e) {
        console.error("❌ 解析 JSON 失敗！內容可能為 HTML。");
        process.exit(1);
      }

      if (!json.items || json.items.length === 0) {
        console.log("⚠️ 警告: API 回傳的圖片列表是空的！");
        process.exit(0); 
      }

      console.log(`[2] 取得 ${json.items.length} 筆資料 (期數: ${json.period})，準備下載...`);

      const dataJsonPath = path.join(IMG_DIR, 'data.json');
      
      // 準備本地資料結構
      const localData = { ...json };
      localData.items = json.items.map(item => {
        const filename = `${item.lang}.png`; 
        return {
          ...item,
          imageUrl: `images/${filename}`, 
          localFilename: filename
        };
      });

      // 寫入 data.json
      fs.writeFileSync(dataJsonPath, JSON.stringify(localData, null, 2));

      // 2. 下載所有圖片
      let promises = localData.items.map(item => {
        return new Promise((resolve, reject) => {
          const downloadUrl = item.downloadUrl; 
          const dest = path.join(IMG_DIR, item.localFilename);
          
          console.log(`⬇️ 開始下載: ${item.lang}`);
          
          fetchWithRedirect(downloadUrl, (response) => {
            if (response.statusCode !== 200) {
              console.error(`❌ 下載失敗 [${item.lang}] 狀態碼: ${response.statusCode}`);
              reject();
              return;
            }
            
            const file = fs.createWriteStream(dest);
            response.pipe(file);
            
            file.on('finish', () => {
              file.close(() => {
                // 檢查檔案大小
                const stats = fs.statSync(dest);
                if (stats.size === 0) {
                   console.error(`❌ 下載檔案為空: ${item.lang}`);
                   reject();
                } else {
                   console.log(`✅ 下載完成: ${item.lang}`);
                   resolve();
                }
              });
            });
          });
        });
      });

      Promise.all(promises)
        .then(() => console.log("🎉 所有圖片處理完畢，準備上傳 GitHub！"))
        .catch(() => {
          console.error("💥 部分圖片下載失敗");
          process.exit(1);
        });

    } catch (error) {
      console.error("發生錯誤:", error);
      process.exit(1);
    };
  });
});
