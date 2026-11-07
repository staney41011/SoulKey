const fs=require("fs"),vm=require("vm"),assert=require("assert");
const files=["NativeAudio.gs","NativeNext.gs","NativeQuality.gs"];
function permutations(xs){
  if(xs.length===0)return [[]];
  return xs.flatMap((x,i)=>permutations(xs.filter((_,j)=>i!==j)).map(rest=>[x,...rest]));
}
for(const order of permutations(files)){
  const context=vm.createContext({});
  for(const name of order){
    new vm.Script(fs.readFileSync(__dirname+"/"+name,"utf8"),{filename:name})
      .runInContext(context);
  }
  const langs=vm.runInContext("SK_AUDIO_LANGUAGES.slice()",context);
  const sheetLangs=vm.runInContext("SK_NEXT_LANGS.slice()",context);
  assert.deepStrictEqual(Array.from(langs.slice(1)),Array.from(sheetLangs));
  assert.equal(langs.length,16);
  assert.equal(typeof context.soulkeyRecoveryAuthorize,"function");
}
console.log("PASS all 6 Apps Script global load orders and 16 language parity");
