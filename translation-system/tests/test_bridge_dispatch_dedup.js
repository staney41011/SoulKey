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

const runtimeFrom = source.indexOf('function getRuntimeJob_(');
const runtimeUntil = source.indexOf('function workerRuntime_(', runtimeFrom);
const activeTtl = source.match(/^const ACTIVE_RUNTIME_TTL_MS = .*;$/m);
assert.ok(activeTtl && runtimeFrom > 0 && runtimeUntil > runtimeFrom);
let clock = 1_800_000_000_000;
sandbox.Date = class extends Date {
  static now() { return clock; }
};
vm.runInContext(activeTtl[0] + '\n' + source.slice(runtimeFrom, runtimeUntil), sandbox);
const queuedNonce = 'queued-job';
const queueDeadline = clock + 60_000;
storage.set('JOB_' + queuedNonce, JSON.stringify({
  task_id: 'P260-L04',
  expires_at: new Date(queueDeadline).toISOString(),
}));
const active = sandbox.activateRuntimeJob_(queuedNonce);
assert.equal(Date.parse(active.expires_at), clock + 6 * 60 * 60 * 1000);
clock = queueDeadline + 1000;
assert.equal(sandbox.activateRuntimeJob_(queuedNonce).expires_at, active.expires_at,
  'refresh must not extend the active deadline');
clock = Date.parse(active.expires_at) + 1000;
assert.equal(sandbox.activateRuntimeJob_(queuedNonce), null,
  'an expired job must not be reactivated');
storage.set('JOB_expired-queue', JSON.stringify({
  expires_at: new Date(queueDeadline).toISOString(),
}));
assert.equal(sandbox.activateRuntimeJob_('expired-queue'), null,
  'a job that missed its queue deadline may not start');
console.log('BRIDGE_RUNTIME_OK: queued and active expiry are independently enforced');
