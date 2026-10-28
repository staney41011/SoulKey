/* Secure one-time enrollment from a QR shown on the owner's authorized PC.
 * The key lives only in sessionStorage; URL fragment is removed immediately.
 * URL fragments are not transmitted to GitHub Pages in HTTP requests.
 */
(function(){
  "use strict";
  const HASH_PARAM="soulkey_pair";
  const SESSION_KEY="soulkey_bridge_key_session_v1";
  let uri;
  try { uri=new URL(window.location.href); } catch (_) { return; }
  if(!uri.hash || !uri.hash.includes(HASH_PARAM+"=")) return;
  const hash=new URLSearchParams(uri.hash.substring(1));
  const value=hash.get(HASH_PARAM);
  if(value===null) return;
  // Clear before doing anything else; never leave the secret in visible URLs.
  uri.hash="";
  try { window.history.replaceState(window.history.state,"",uri.pathname+uri.search); } catch (_) {}
  if(!/^[A-Za-z0-9_-]{24,128}$/.test(value)){
    window.SOULKEY_PAIR_ERROR="配對碼格式不正確。請重新用授權電腦產生 QR Code。";
    return;
  }
  try {
    window.sessionStorage.setItem(SESSION_KEY,value);
    window.SOULKEY_PAIR_IMPORTED=true;
  } catch (_) {
    window.SOULKEY_PAIR_ERROR="瀏覽器不允許暫存配對資料；請開啟一般 Safari 分頁重試。";
  }
})();
