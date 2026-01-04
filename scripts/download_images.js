const fs = require('fs');
const https = require('https');
const path = require('path');

// 這是你的 Google Apps Script JSON API 網址
const API_URL = 'https://script.google.com/macros/s/AKfycbwvNwOn8QwvH-agggTWm6ZZUosmCPDuGUpSbckc8DFahBP9fiHLfPCBCIlWMt9p4V3V/exec';
const IMG_DIR = 'images';

if (!fs.existsSync(IMG_DIR)){
    fs.mkdirSync(IMG_DIR);
}

// 下載圖片的函數
const download = (url, dest, cb) => {
  const file = fs.createWriteStream(dest);
  https.get(url, function(response) {
    response.pipe(file);
    file.on('finish', function() {
      file.close(cb);
    });
  }).on('error', function(err) {
    fs.unlink(dest);
    if (cb) cb(err.message);
  });
};

console.log("正在讀取圖片清單...");

https.get(API_URL, (res) => {
  let body = "";
  res.on("data", (chunk) => { body += chunk; });
  res.on("end", () => {
    try {
      const json = JSON.parse(body);
      const dataJsonPath = path.join(IMG_DIR, 'data.json');
      
      // 1. 先把 API 資料存一份下來供網頁使用 (這樣網頁就不用再呼叫 Google API 了，更快!)
      // 我們要把圖片連結改成 GitHub 本地的路徑
      const localData = { ...json };
      localData.items = json.items.map(item => {
        // 定義檔名，例如: chinese.png, english.png
        const filename = `${item.lang}.png`; 
        return {
          ...item,
          imageUrl: `images/${filename}`, // 網頁讀取路徑
          localFilename: filename // 下載儲存檔名
        };
      });

      fs.writeFileSync(dataJsonPath, JSON.stringify(localData, null, 2));
      console.log("data.json 已更新");

      // 2. 開始下載圖片
      localData.items.forEach(item => {
        // 使用 Google Drive 下載連結
        const downloadUrl = item.downloadUrl; 
        const dest = path.join(IMG_DIR, item.localFilename);
        
        console.log(`正在下載 ${item.lang}版 DM...`);
        download(downloadUrl, dest, (err) => {
          if(err) console.error(`下載失敗: ${item.lang}`, err);
          else console.log(`下載完成: ${item.lang}`);
        });
      });

    } catch (error) {
      console.error(error.message);
    };
  });
});
