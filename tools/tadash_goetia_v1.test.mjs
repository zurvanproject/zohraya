import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {initialWorld, tickWorld, advance, transferBody, worldExport, report,
  enableGoetia, selectGoetiaGate, practiceGate, castGate, goetiaReport} from "./tadash_evolution_v1.mjs";
import {assertGoetiaState, DOMAINS} from "./tadash_goetia_v1.mjs";

const catalogue = JSON.parse(readFileSync(new URL("./data/tadash_goetia_72.json", import.meta.url), "utf8"));
const results = [];
const test = (name, fn) => {fn(); results.push(name);};
const copy = x => JSON.parse(JSON.stringify(x));
const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-10, `${a} != ${b}`);
const enabled = (id = 1, automatic = false) => enableGoetia(initialWorld(), catalogue, {selectedGate: id, autoPractice: automatic});
const gateFor = domain => catalogue.find(d => d.tadash.domain === domain).id;
const q = (w, id) => {const a=w.agents[0];return Math.min(1, Math.max(0,.35+.35*a.energy+.20*a.culture.focus+.10*a.lilith.regulation-.30*a.fatigue+.02*w.goetia.gates[id-1].stage));};
const opts = (w, id) => {
  const d = catalogue[id-1].tadash.domain;
  if (d === "passage") return {targetTown: w.towns.find(t => t.id !== w.agents[0].town).id};
  if (d === "transformation") return {from: "water", to: "food"};
  return {};
};

// Every progression fixture below obtains mastery through actual world ticks.
// Controlled state changes in individual boundary tests are explicitly local fixtures.
function trained(id, qualified = 3) {
  let w = enabled(id, true), steps = 0;
  while (w.goetia.gates[id-1].qualified < qualified && steps++ < 500) w = tickWorld(w);
  assert.ok(w.goetia.gates[id-1].qualified >= qualified, "natural training did not qualify");
  return selectGoetiaGate(w, id, {autoPractice: false});
}
function ready(w, id) {
  let steps = 0;
  while ((w.goetia.lastActionTick >= w.tick || q(w,id)<.60 || w.agents[0].energy < .18+.01*w.goetia.gates[id-1].stage || w.agents[0].fatigue > .85) && steps++ < 100)
    w = tickWorld(w);
  assert.ok(steps < 100, "cast did not become ready");
  return w;
}

test("actual catalogue contains 72 ordered entries and every implemented domain", () => {
  assert.equal(catalogue.length,72);
  assert.deepEqual(catalogue.map(d=>d.id),Array.from({length:72},(_,i)=>i+1));
  assert.deepEqual([...new Set(catalogue.map(d=>d.tadash.domain))].sort(),[...DOMAINS].sort());
});
test("enabling is opt-in, immutable and starts with zero mastery", () => {
  const old=initialWorld(), before=JSON.stringify(old), w=enableGoetia(old,catalogue);
  assert.equal(JSON.stringify(old),before);
  assert.equal(old.goetia,undefined);
  assert.equal(w.goetia.gates.length,72);
  assert.equal(goetiaReport(w).unlocked,0);
  assert.equal(w.agents.length,1);
});
test("malformed catalogue entries are rejected", () => {
  assert.throws(()=>enableGoetia(initialWorld(),catalogue.slice(1)));
  for(const edit of [c=>c[1].id=1,c=>c[1].tadash.domain="mind_control",c=>c[1].name=""]){const c=copy(catalogue);edit(c);assert.throws(()=>enableGoetia(initialWorld(),c));}
});
test("catalogue and returned reports have no mutable aliases into the world", () => {
  const c=copy(catalogue),w=enableGoetia(initialWorld(),c),name=w.goetia.definitions[0].name;
  c[0].name="changed";assert.equal(w.goetia.definitions[0].name,name);
  const r=goetiaReport(w);r.gates[0].stage=4;assert.equal(w.goetia.gates[0].stage,0);
});
test("an existing school cannot be reset by re-enabling", () => assert.throws(()=>enableGoetia(enabled(),catalogue)));
test("one action per tick applies across different gates", () => {
  const w=practiceGate(enabled(),1), before=JSON.stringify(w);
  assert.throws(()=>practiceGate(w,2),/one gate action/);
  assert.equal(JSON.stringify(w),before);
});
test("untrained casting is rejected without cost or mutation", () => {
  const w=enabled(),before=JSON.stringify(w);
  assert.throws(()=>castGate(w,1),/three qualified/);
  assert.equal(JSON.stringify(w),before);
});
test("a qualified practice costs exactly the documented energy and fatigue", () => {
  const w=enabled(),out=practiceGate(w,1),a=out.agents[0];
  close(w.agents[0].energy-a.energy,.04);close(a.fatigue-w.agents[0].fatigue,.025);
  assert.equal(out.goetia.gates[0].qualified,1);assert.equal(out.goetia.gates[0].stage,0);
});
test("low quality practice consumes a turn but earns no qualification", () => {
  const w=enabled();w.agents[0].energy=.2;w.agents[0].fatigue=.8;w.agents[0].culture.focus=0;
  const out=practiceGate(w,1);assert.equal(out.goetia.gates[0].repetitions,1);
  assert.equal(out.goetia.gates[0].qualified,0);assert.equal(out.goetia.history.at(-1).outcome,"unqualified");
});
test("exhaustion and invalid gate ids fail transactionally", () => {
  for(const modify of [w=>w.agents[0].energy=.05,w=>w.agents[0].fatigue=.95]){
    const w=enabled();modify(w);const before=JSON.stringify(w);assert.throws(()=>practiceGate(w,1));assert.equal(JSON.stringify(w),before);
  }
  const w=enabled();for(const id of [0,73,1.5,"1"])assert.throws(()=>practiceGate(w,id));
});

const first=trained(1), mastered=trained(1,15);
test("three natural qualified practices unlock stage one", () => {
  assert.equal(first.goetia.gates[0].qualified,3);assert.equal(first.goetia.gates[0].stage,1);
});
test("natural practice advances by three qualifications and caps at four", () => {
  const g=mastered.goetia.gates[0];assert.equal(g.stage,4);assert.ok(g.qualified>=15);
  for(const e of mastered.goetia.history) assert.ok(e.stage<=4);
});
test("automatic training replaces the legacy blessing and charges only once", () => {
  const e=first.culture.events.find(e=>e.kind==="magic"&&e.detail?.gate);
  assert.ok(e);close(e.detail.gate.energyCost,.04);close(e.detail.gate.fatigueChange,.025);
  assert.equal(e.worldGain,0);assert.equal(first.culture.magicEffects,0);
  const primary=first.events.find(x=>x.tick===e.tick);
  const baseDelta=primary.action==="rest" ? Math.min(.3,1-primary.before.energy) : -.13;
  close(primary.after.energy,primary.before.energy+baseDelta-.04);
});
test("turning off automatic training preserves ordinary cultural activity", () => {
  const w=advance(enabled(1,false),80);assert.equal(w.goetia.totalPractice,0);assert.ok(w.culture.magicEffects>0);
});
test("casting quality failure spends the turn and cost but changes no effect fields", () => {
  const w=ready(first,1);w.agents[0].energy=.20;w.agents[0].fatigue=.80;w.agents[0].culture.focus=0;
  const out=castGate(w,1),e=out.goetia.history.at(-1);
  assert.equal(e.outcome,"fizzle");assert.equal(e.changes.length,0);assert.equal(e.observation,null);
  close(e.energyCost,.09);assert.equal(out.goetia.totalCasts,w.goetia.totalCasts+1);
});

// One continuous, naturally advancing world trains and invokes every actual gate.
let journey=enabled(1,true);
const walk=[];
for(let id=1;id<=72;id++){
  journey=selectGoetiaGate(journey,id,{autoPractice:true});
  let n=0;
  while(journey.goetia.gates[id-1].stage<1 && n++<500) journey=tickWorld(journey);
  assert.ok(n<500,`gate ${id} did not unlock`);
  journey=selectGoetiaGate(journey,id,{autoPractice:false});
  journey=ready(journey,id);
  const before=JSON.stringify(journey);
  const out=castGate(journey,id,opts(journey,id));
  assert.equal(JSON.stringify(journey),before,`gate ${id} mutated its input`);
  assertGoetiaState(out);
  walk.push({id,domain:catalogue[id-1].tadash.domain,tick:out.tick,stage:out.goetia.gates[id-1].stage,outcome:out.goetia.history.at(-1).outcome});
  journey=out;
}
test("all 72 actual gates train and cast in one valid continuous world", () => {
  assert.equal(walk.length,72);assert.equal(journey.goetia.totalCasts,72);
  assert.equal(goetiaReport(journey).unlocked,72);
  assert.ok(journey.goetia.totalPractice>=216);
  assert.equal(journey.agents.length,1);
});
test("all domain paths produce an observed or changed result when available", () => {
  for(const domain of DOMAINS)assert.ok(walk.some(x=>x.domain===domain&&["changed","observed","no_effect"].includes(x.outcome)));
  assert.ok(walk.every(x=>x.outcome!=="fizzle"));
});
test("school history is bounded and owner-qualified", () => {
  assert.equal(journey.goetia.history.length,64);
  assert.ok(journey.goetia.history.every(e=>e.owner==="tadash:nasuraya"));
});

function masteredDomain(domain){const id=gateFor(domain);return {id,w:ready(journey,id)};}
test("every domain realizes a bounded effect when its target is not saturated", () => {
  for(const domain of DOMAINS){
    const {id,w}=masteredDomain(domain),a=w.agents[0];
    a.energy=.9;a.fatigue=.1;
    for(const k of ["focus","joy","discipline","imagination","coordination","insight"])a.culture[k]=.5;
    for(const k of ["anger","desire","agency","shadowInsight","nightAffinity","regulation"])a.lilith[k]=.5;
    a.culture.bonds={founder:.5,gaya:.5};a.affinity=.5;a.skills.create=.5;
    for(const town of w.towns)for(const k of ["water","food","clinic"])town[k]=50;
    const before=JSON.stringify(w),out=castGate(w,id,opts(w,id)),e=out.goetia.history.at(-1);
    assert.ok(["changed","observed"].includes(e.outcome),domain);
    for(const change of e.changes){
      if(change.field==="town")continue;
      const limit=/^(gaya|zurvan|lilith)\./.test(change.field)?4:.06;
      assert.ok(Math.abs(change.after-change.before)<=limit+1e-10,domain);
    }
    assertGoetiaState(out);assert.equal(JSON.stringify(w),before);
  }
});
test("resource effects record actual capacity-limited changes", () => {
  const {id,w}=masteredDomain("water");const t=w.towns.find(t=>t.id===w.agents[0].town);t.water=99.9;
  const out=castGate(w,id),e=out.goetia.history.at(-1);
  close(out.towns.find(x=>x.id===t.id).water,100);close(e.changes[0].after-e.changes[0].before,.1);
});
test("fully saturated effects report no effect and still cost energy", () => {
  const {id,w}=masteredDomain("knowledge");w.agents[0].culture.insight=1;
  const out=castGate(w,id),e=out.goetia.history.at(-1);
  assert.equal(e.outcome,"no_effect");assert.deepEqual(e.changes,[]);assert.ok(e.energyCost>0);
});
test("resource transformation conserves the local sum and obeys capacity", () => {
  const {id,w}=masteredDomain("transformation"),t=w.towns.find(t=>t.id===w.agents[0].town);
  t.water=.2;t.food=99.9;const sum=t.water+t.food+t.clinic;
  const out=castGate(w,id,{from:"water",to:"food"}),after=out.towns.find(x=>x.id===t.id);
  close(after.water+after.food+after.clinic,sum);close(after.water,.1);close(after.food,100);
  assert.throws(()=>castGate(w,id,{from:"water",to:"water"}));
});
test("passage keeps owner and history while moving only to an existing town", () => {
  const {id,w}=masteredDomain("passage"),target=w.towns.find(t=>t.id!==w.agents[0].town).id;
  const out=castGate(w,id,{targetTown:target});assert.equal(out.agents[0].town,target);
  assert.equal(out.agents[0].identity,"tadash:nasuraya");assert.deepEqual(out.agents[0].memory,w.agents[0].memory);
  assert.throws(()=>castGate(w,id,{targetTown:"niara"}));assert.throws(()=>castGate(w,id));
  assert.equal(castGate(w,id,{targetTown:w.agents[0].town}).goetia.history.at(-1).outcome,"no_effect");
});
test("revelation records current simulated resources with its original timestamp", () => {
  const {id,w}=masteredDomain("revelation"),out=castGate(w,id),e=out.goetia.history.at(-1);
  assert.equal(e.observation.kind,"current_simulated_resources");assert.equal(e.observation.asOfTick,w.tick);
  const t=w.towns.find(t=>t.id===w.agents[0].town);assert.deepEqual(e.observation.towns,[t]);
  const saved=copy(e.observation),next=tickWorld(out);assert.deepEqual(next.goetia.history.at(-1).observation,saved);
});
test("remembrance only recalls an existing own decision", () => {
  const {id,w}=masteredDomain("remembrance"),last=w.agents[0].memory.at(-1),out=castGate(w,id);
  const o=out.goetia.history.at(-1).observation;
  assert.equal(o.memoryTick,last.tick);assert.equal(o.action,last.action);assert.equal(o.benefit,last.benefit);
  w.agents[0].memory=[];const empty=castGate(w,id);assert.equal(empty.goetia.history.at(-1).outcome,"no_effect");
});
test("remembrance rejects foreign and malformed memories before relabeling or effects", () => {
  for(const memory of [
    {tick:2,action:"rest",benefit:.3,agent:"niara",identity:"tadash:niara"},
    {tick:2,action:"rest",benefit:.3,owner:"tadash:asalameh"},
    {tick:2,action:"rest",benefit:.3,before:{identity:"tadash:niara"}},
    {tick:-1,action:"invalid",benefit:.3},
    {tick:2,action:"invalid",benefit:.3},
    {tick:2,action:"rest",benefit:NaN}
  ]){
    const {id,w}=masteredDomain("remembrance");w.agents[0].memory=[memory];const before=JSON.stringify(w);
    assert.throws(()=>castGate(w,id));assert.throws(()=>report(w));assert.equal(JSON.stringify(w),before);
  }
});
test("standalone gate APIs reject malformed desire associations", () => {
  const w=enabled();w.agents[0].lilith.memory.day.strength=2;
  assert.throws(()=>practiceGate(w,1));assert.throws(()=>goetiaReport(w));
});
test("snapshot continuation reproduces exact outcomes", () => {
  const w=enableGoetia(initialWorld(2026),catalogue,{selectedGate:10});
  assert.deepEqual(advance(copy(advance(w,40)),40),advance(w,80));
});
test("body transfer preserves school mastery and memory", () => {
  const out=transferBody(journey,"nasuraya");assert.deepEqual(out.goetia,journey.goetia);
  assert.deepEqual(out.agents[0].memory,journey.agents[0].memory);assert.equal(out.agents[0].bodyGeneration,2);
});
test("host reports include school scope while the core export remains version one", () => {
  assert.equal(report(journey).goetia.gateCount,72);assert.equal(report(journey).phenomenalConsciousness,"not_measured");
  assert.equal(worldExport(journey).version,1);assert.equal(worldExport(journey).goetia,undefined);
});
test("pre-school snapshots continue without an implicit opt-in", () => {
  const w=initialWorld();delete w.agents[0].culture;delete w.culture;
  const out=tickWorld(w);assert.ok(out.agents[0].culture);assert.equal(out.goetia,undefined);
});
test("foreign owners, actors and events are rejected at both API layers", () => {
  for(const mutate of [w=>w.owner="niara",w=>w.agents.push({...w.agents[0],id:"niara",identity:"tadash:niara"}),
    w=>w.goetia.owner="tadash:niara",w=>w.goetia.history[0].owner="tadash:asalameh"]){
    const w=copy(first);mutate(w);assert.throws(()=>practiceGate(w,1));
    for(const f of [()=>advance(w,0),()=>report(w),()=>worldExport(w),()=>transferBody(w,"nasuraya")])assert.throws(f);
  }
});
test("malformed mastery, chronology, counters and history are rejected", () => {
  for(const mutate of [w=>w.goetia.gates[0].stage=4,w=>w.goetia.lastActionTick=w.tick+1,w=>w.goetia.totalPractice++,
    w=>w.goetia.history[0].domain="desire",w=>w.goetia.history[0].quality=NaN,w=>w.goetia.history[0].sequence=999,
    w=>w.goetia.definitions[0].id=72,w=>w.goetia.gates[0].qualified=-1]){
    const w=copy(first);mutate(w);assert.throws(()=>assertGoetiaState(w));
  }
});

console.log(JSON.stringify({passed:results.length,checks:results,continuousWalk:{ticks:journey.tick,
  practices:journey.goetia.totalPractice,casts:journey.goetia.totalCasts,unlocked:72,history:journey.goetia.history.length,
  domains:[...new Set(walk.map(x=>x.domain))],gates:walk}},null,2));
