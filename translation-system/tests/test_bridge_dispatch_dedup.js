// Offline contract test of the actual Apps Script dedup functions.
// Never contacts GitHub/Google or reads secrets.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const path = require('node:path');

const source = fs.readFileSync(
  path.resolve(__dirname, '../../bridge/apps-script/Code.gs'), 'utf8'
);
const from = source.indexOf('const DISPATCH_DEDUP_TTL_MS =');
const until = source.indexOf('function dispatchWorkflow_(', from);
assert.ok(from > 0 && until > from, 'missing dedup implementation');
const implementation = source.slice(from, until);

let sends = 0;
let releases = 0;
let failures = false;
let created = 0;
const storage = new Map();
const properties = {
  getProperty: k => storage.get(k) || null,
  setProperty: (k, v) => storage.set(k, v),
  deleteProperty: k => storage.delete(k),
};
const sandbox = {
  Date, String, JSON, Set, Array,
  Utilities: {
    DigestAlgorithm: { SHA_256: 'sha256' },
    computeDigest: (_, text) => Array.from(crypto.createHash('sha256').update(text).digest()),
    base64EncodeWebSafe: bytes => Buffer.from(bytes).toString('base64url'),
  },
  LockService: {
    getScriptLock: () => ({
      waitLock(ms) { assert.equal(ms, 30000); },
      releaseLock() { releases++; },
    }),
  },
  PropertiesService: { getScriptProperties: () => properties },
  createRuntimeJob_: (task, stage, lang, langs) => {
    const nonce = 'test_nonce_' + (++created);
    storage.set('JOB_' + nonce, JSON.stringify({ task, stage, lang, langs }));
    return nonce;
  },
  dispatchWorkflow_: () => {
    sends++;
    return failures ? { ok: false, error: 'test_failure' } : { ok: true };
  },
  ScriptApp: { getService: () => ({ getUrl: () => 'https://example.invalid/bridge' }) },
  WORKFLOW_WEB_JOB: 'kaggle_web_job.yml',
};
vm.createContext(sandbox);
vm.runInContext(implementation, sandbox, {timeout: 2000});

const fn = sandbox.dispatchWorkflowIdempotently_;
const first = fn('private-token', 'P257-L02', 'tts', 'en,pt', 'it,th');
assert.equal(first.ok, true);
assert.equal(first.duplicate, undefined);
assert.equal(sends, 1);
const duplicate = fn('private-token', 'P257-L02', 'tts', 'pt,en', 'th,it');
assert.equal(duplicate.duplicate, true);
assert.equal(sends, 1, 'duplicate should not dispatch again');
assert.equal(fn('private-token', 'P257-L02', 'multi', '', 'it,pt').ok, true);
assert.equal(sends, 2, 'different stage should dispatch');

sandbox.releaseDispatchLease_(
  {task_id: 'P257-L02', stage: 'tts', lang: 'en,pt', langs: 'it,th'}, first.nonce
);
assert.equal(fn('private-token', 'P257-L02', 'tts', 'en,pt', 'it,th').ok, true);
assert.equal(sends, 3, 'terminal release permits a future explicit rerun');

failures = true;
const failed = fn('private-token', 'P257-L02', 'asr', '', '');
assert.equal(failed.ok, false);
assert.ok(!storage.has('JOB_' + 'test_nonce_' + created), 'failed send must drop runtime job');
failures = false;
const retry = fn('private-token', 'P257-L02', 'asr', '', '');
assert.equal(retry.ok, true, 'failed dispatch is immediately retryable');
assert.ok(releases >= 6, 'every lock use must release');
console.log('BRIDGE_DEDUP_OK: duplicate rejected, release and failed dispatch retry work');
