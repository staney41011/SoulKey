// Exercise real Apps Script UID allocator with a minimal in-memory spreadsheet.
// No Google credentials, Drive files, or running course records are modified.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("bridge/apps-script/Code.gs", "utf8");

function pickFunction(name) {
  const start = source.indexOf("function " + name + "(");
  assert.ok(start >= 0, "Missing Apps Script function: " + name);
  const next = source.indexOf("\nfunction ", start + 9);
  return source.slice(start, next < 0 ? undefined : next);
}

class Sheet {
  constructor(rows) { this.rows = rows.map(x => x.slice()); }
  getLastRow() { return this.rows.length; }
  getMaxColumns() { return 26; }
  getDataRange() { return {getValues: () => this.rows.map(x => x.slice())}; }
  getRange(row, col, height, width) {
    const sheet = this;
    height ||= 1;
    width ||= 1;
    return {
      getValues() {
        return Array.from({length:height}, (_, i) =>
          Array.from({length:width}, (_, j) => sheet.rows[row-1+i]?.[col-1+j] ?? ""));
      },
      getDisplayValues() {
        return this.getValues().map(a => a.map(String));
      },
      setValues(values) {
        values.forEach((vals, i) => {
          const target = sheet.rows[row-1+i] ||= Array(26).fill("");
          vals.forEach((value, j) => {target[col-1+j] = value;});
        });
      }
    };
  }
  appendRow(row) { this.rows.push(row.slice()); }
}

function task(id, uid, lesson) {
  const a = Array(26).fill("");
  a[0] = id; a[1] = 257; a[2] = lesson; a[4] = "https://youtu.be/" + id;
  a[20] = uid;
  return a;
}
const sheet = new Sheet([
  Array(26).fill(""),
  task("P257-L01", "SKC-000016", "第1堂"),
  task("P257-L02", "SKC-000017", "第2堂"),
  task("P257-L03", "SKC-000017", "第3堂"),
  task("P257-L04", "SKC-000017", "第4堂"),
]);
let locked = false, lockedCalls = 0, unlockCalls = 0;
const cache = new Map();
const sandbox = {
  Set, Number, String, Math,
  TASK_SHEET_NAME:"任務佇列",
  TASK_TOTAL_COLUMNS:26,
  TASK_COL:{course_uid:20,schedule_status:21,original_period:22,original_lesson:23},
  getSheetByName_:()=>sheet,
  CacheService:{getScriptCache:()=>({
    get:(k)=>cache.get(k),
    put:(k,v)=>cache.set(k,v)
  })},
  LockService:{getScriptLock:()=>({
    waitLock:()=>{assert.equal(locked,false);locked=true;lockedCalls++;},
    releaseLock:()=>{assert.equal(locked,true);locked=false;unlockCalls++;}
  })},
  SpreadsheetApp:{flush(){}},
  ensurePeriodStructure_:()=>{},
  nowText_:()=> "2026-10-08 23:00:00",
  appendStaleIfDone_:()=>{throw new Error("unexpected reset")},
  allocateTaskId_:(base,byId)=>{let n=2;while(byId[base+"-R"+n]) n++;return base+"-R"+n;}
};
vm.createContext(sandbox);
vm.runInContext(
  pickFunction("ensureTaskIdentitySchema_") + "\n" +
  pickFunction("upsertTasks_"),
  sandbox, {filename:"Code.gs"}
);
sandbox.ensureTaskIdentitySchema_();
assert.deepEqual(sheet.rows.slice(1).map(x=>x[20]),
  ["SKC-000016","SKC-000017","SKC-000018","SKC-000019"]);
assert.equal(cache.get("task-identity-schema-v2"),"ok");

// A browser may send another lesson's stale UID; it is never authoritative.
const res = sandbox.upsertTasks_([
  {id:"P258-L01",period:258,lesson:"第1堂",url:"https://youtu.be/new1",course_uid:"SKC-000017"},
  {id:"P258-L02",period:258,lesson:"第2堂",url:"https://youtu.be/new2",course_uid:"SKC-000017"}
]);
assert.deepEqual(Array.from(res, x=>x.course_uid),["SKC-000020","SKC-000021"]);
assert.equal(lockedCalls,1);
assert.equal(unlockCalls,1);

// Existing lesson keeps its unique UID, even if stale localStorage says 000017.
const update = sandbox.upsertTasks_([
  {id:"P257-L03",period:257,lesson:"第3堂",url:"https://youtu.be/P257-L03",course_uid:"SKC-000017"}
]);
assert.equal(update[0].course_uid,"SKC-000018");

// Collision on task ID in a different slot must not overwrite the old lesson.
const reused = sandbox.upsertTasks_([
  {id:"P257-L02",period:259,lesson:"第1堂",url:"https://youtu.be/something",course_uid:"SKC-000017"}
]);
assert.equal(reused[0].id,"P257-L02-R2");
assert.equal(reused[0].course_uid,"SKC-000022");
assert.equal(sheet.rows[2][2],"第2堂");
assert.equal(new Set(sheet.rows.slice(1).map(x=>x[20])).size,sheet.rows.length-1);

console.log("PASS: duplicated historical UIDs repaired");
console.log("PASS: two new tasks with stale local UID receive different server IDs");
console.log("PASS: existing task UID stable and reused legacy IDs cannot overwrite it");
console.log("PASS: UID upserts acquire and release script lock");
