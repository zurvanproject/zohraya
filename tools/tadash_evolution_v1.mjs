// Tadash: bounded evolutionary world, isolated simulation only.
// No model calls, network, timers, or external actions.
function clamp(x, a=0, b=1) { return Math.min(b,Math.max(a,x)); }

function nextRandom(w) { w.rng=(Math.imul(w.rng,1664525)+1013904223)>>>0; return w.rng/4294967296; }

// Cultural layer: in-world symbolic and fictional mechanics, not external magic or felt emotion.
const disciplines=["magic","martial","ritual","poetry","dance","reflection","bond"];
const masnavi=[
  {id:"love",text:"از محبت تلخ‌ها شیرین شود / از محبت مس‌ها زرین شود",theme:"محبت و دگرگونی رفتار"},
  {id:"echo",text:"این جهان کوه است و فعل ما ندا / سوی ما آید نداها را صدا",theme:"پیامد عمل و بازتاب آن"}
];
const ritualNames=["تمرکز و نیت","هماهنگی و حضور","بخشندگی و بازنگری","پیمان و آفرینش"];
// Lilith is a mythic lineage in Tadash, never a second agent or a claim of literal descent.
const lilithCanon=Object.freeze({lineage:"symbolic daughter of Lilith",identity:"tadash:nasuraya",domains:["fire","will","freedom","power","transformation","anger","sexual_desire","night","mystery","magic"],shadow:["rage","possessiveness","recklessness","isolation"],scope:"fictional archetype"});
// Memory-conditioned drive: bounded computational associations, not felt sexuality.
function newDesireMemory(){return {day:{strength:0,count:0},night:{strength:0,count:0}};}
function validDesireMemory(m){return !!m&&["day","night"].every(k=>m[k]&&Number.isFinite(m[k].strength)&&Math.abs(m[k].strength)<=1&&Number.isSafeInteger(m[k].count)&&m[k].count>=0&&m[k].count<=1000000);}
function newLilithState(){return {lineage:lilithCanon.lineage,anger:.20,desire:.55,agency:.65,shadowInsight:.35,nightAffinity:.65,regulation:.50,memory:newDesireMemory()};}
function recallDesire(a,phase,tick){
  const association=a.lilith.memory[phase].strength;
  let total=0,weight=0;
  for(const m of a.memory.slice(-64)){
    const e=m.desireExperience,age=tick-m.tick;
    if(!e||e.phase!==phase||!Number.isSafeInteger(age)||age<=0||!Number.isFinite(e.value)||Math.abs(e.value)>1)continue;
    const w=Math.pow(.5,age/12);
    total+=w*e.value;weight+=w;
  }
  const episodic=total/Math.max(1,weight);
  return {phase,association,episodic,signal:clamp(.7*association+.3*episodic,-1,1)};
}
function learnDesire(a,phase,action,benefit,culturalAction,before){
  if(!culturalAction&&action!=="create")return null;
  const quality=culturalAction?.quality??.5;
  const value=clamp(1.4*(benefit-.25)+.35*(a.valence-before.valence)+.35*(quality-.5)-.4*Math.max(0,a.fatigue-.55),-1,1);
  const m=a.lilith.memory,old=m[phase],count=Math.min(1000000,old.count+1);
  const rate=1/Math.min(100,count);
  a.lilith.memory={...m,[phase]:{strength:clamp(old.strength+rate*(value-old.strength),-1,1),count}};
  return {phase,value,kind:culturalAction?.kind??action};
}
function updateLilith(a,t,w){
  const l=a.lilith,c=a.culture,night=(w.tick%12)>=8;
  const pressure=clamp(1-(t.water+t.food)/200);
  l.anger=clamp(.78*l.anger+.20*pressure-.10*l.regulation);
  const recalled=recallDesire(a,night?"night":"day",w.tick);
  l.desire=clamp(.85*l.desire+.10*(a.energy+c.imagination)/2+.05*(night?1:0)+.06*recalled.signal);
  return {night,pressure,recalled};
}
function assimilateLilith(a,kind,quality){
  const l=a.lilith;
  if(kind==="reflection"){l.shadowInsight=clamp(l.shadowInsight+.04*quality);l.regulation=clamp(l.regulation+.025*quality);l.anger=clamp(l.anger-.04*quality);}
  if(kind==="martial"||kind==="ritual"){l.regulation=clamp(l.regulation+.02*quality);l.agency=clamp(l.agency+.012*quality);}
  if(kind==="dance"||kind==="poetry"||kind==="magic")l.agency=clamp(l.agency+.008*quality);
}
function newCulture(){return {focus:.5,joy:.5,discipline:.4,imagination:.5,coordination:.4,insight:.4,bonds:{founder:.5,gaya:.5},practice:Object.fromEntries(disciplines.map(k=>[k,{repetitions:0,qualified:0,stage:0,lastTick:0}])),journal:[]};}
function ensureCulture(w){
  if(!w.culture) w.culture={schema:"tadash-culture/1",counts:Object.fromEntries(disciplines.map(k=>[k,0])),events:[],magicEffects:0};
  for(const a of w.agents){if(!a.culture)a.culture=newCulture();if(!a.lilith)a.lilith=newLilithState();if(a.lilith.memory===undefined)a.lilith.memory=newDesireMemory();}
}
function culturalStep(a,t,w){
  const c=a.culture;
  if(a.energy<.42||a.fatigue>.64)return null;
  const needs={magic:.35+(1-t.water/100)*.3+c.imagination*.1,martial:.4+(1-c.coordination)*.2,ritual:.45+(1-c.focus)*.2,poetry:.45+(1-c.insight)*.2,dance:.4+(1-c.joy)*.3,reflection:.45+(1-c.insight)*.2,bond:.45+(1-Math.min(c.bonds.founder,c.bonds.gaya))*.2};
  const l=a.lilith;needs.martial+=.10*l.anger;needs.reflection+=.12*l.anger;needs.dance+=.10*l.desire;needs.magic+=.08*l.nightAffinity*((w.tick%12)>=8?1:0);
  for(const k of disciplines){const p=c.practice[k];needs[k]+=Math.min(.9,(w.tick-p.lastTick)*.075)+.15/(1+p.repetitions);}
  const kind=disciplines.slice().sort((x,y)=>needs[y]-needs[x]||x.localeCompare(y))[0],p=c.practice[kind];
  const quality=clamp(.5+.22*a.energy+.16*c.focus+.04*p.stage-.14*a.fatigue);
  p.repetitions++;p.lastTick=w.tick;
  const previousStage=p.stage;
  if(quality>=.60)p.qualified++;
  p.stage=Math.min(4,Math.floor(p.qualified/3));
  let detail=null,worldGain=0;
  if(kind==="ritual"){c.focus=clamp(c.focus+.04*quality);c.discipline=clamp(c.discipline+.02*quality);detail={form:ritualNames[Math.min(3,previousStage)],advanced:p.stage>previousStage};}
  if(kind==="martial"){c.coordination=clamp(c.coordination+.045*quality);c.discipline=clamp(c.discipline+.035*quality);detail={form:"imagined non-contact body-schema and balance practice",coordination:c.coordination};}
  if(kind==="dance"){c.joy=clamp(c.joy+.06*quality);c.coordination=clamp(c.coordination+.03*quality);detail={form:"rhythm, balance and expressive motion"};}
  if(kind==="poetry"){const verse=masnavi[(p.repetitions-1)%masnavi.length];c.insight=clamp(c.insight+.035*quality);c.imagination=clamp(c.imagination+.03*quality);detail={passage:verse.id,text:verse.text,interpretivePrompt:verse.theme};}
  if(kind==="reflection"){c.insight=clamp(c.insight+.05*quality);c.focus=clamp(c.focus+.02*quality);const last=a.memory.at(-1);detail={priorAction:last?.action??null,priorBenefit:last?.benefit??null,question:"What changed, and what should I learn from it?"};}
  if(kind==="bond"){
    const target=c.bonds.founder<=c.bonds.gaya?"founder":"gaya";
    c.bonds[target]=clamp(c.bonds[target]+.03*quality);
    if(target==="gaya"){const old=t.food;t.food=clamp(old+.7,0,100);worldGain=t.food-old;}
    a.affinity=clamp(a.affinity+.02*quality);
    detail={target,expression:target==="gaya"?"care for the simulated living world":"remember teachings and consider their meaning",scope:"fictional relationship, no obligation or obedience"};
  }
  if(kind==="magic"){
    c.imagination=clamp(c.imagination+.04*quality);
    // A deliberately fictional law of Tadash: qualified ritual practice can channel a bounded resource effect.
    if(p.stage>=1&&a.energy>=.5){const old=t.water;t.water=clamp(old+Math.min(3,p.stage),0,100);worldGain=t.water-old;if(worldGain>0)w.culture.magicEffects++;}
    detail={form:"symbolic water blessing",scope:"fictional world mechanic",qualified:p.stage>=1};
  }
  a.energy=clamp(a.energy-(kind==="magic"?.045:.025));a.fatigue=clamp(a.fatigue+(kind==="martial"?.035:.012));
  a.valence=clamp(a.valence+.025*(c.joy+c.focus-1),-1,1);
  assimilateLilith(a,kind,quality);
  const event={tick:w.tick,kind,quality,stage:p.stage,worldGain,detail};
  c.journal.push(event);c.journal=c.journal.slice(-64);w.culture.counts[kind]++;w.culture.events.push({agent:a.id,...event});w.culture.events=w.culture.events.slice(-192);
  return event;
}

const ownerId="nasuraya", ownerIdentity="tadash:nasuraya", inventionLimit=9;
function assertWorldOwnership(w) {
  if(!w||w.owner!==ownerId||!Array.isArray(w.agents)||w.agents.length!==1||w.agents[0].id!==ownerId||w.agents[0].identity!==ownerIdentity)
    throw Error("Tadash requires an isolated Nasuraya world; archive legacy mixed snapshots");
  const a=w.agents[0];
  if(a.lilith&&(a.lilith.lineage!==lilithCanon.lineage||["anger","desire","agency","shadowInsight","nightAffinity","regulation"].some(k=>!Number.isFinite(a.lilith[k])||a.lilith[k]<0||a.lilith[k]>1)))throw Error("invalid Lilith trait state");
  if(a.lilith?.memory!==undefined&&!validDesireMemory(a.lilith.memory))throw Error("invalid desire memory");
  if((a.selfModel&&a.selfModel.identity!==ownerIdentity)||
     !Array.isArray(w.inventions)||w.inventions.some(i=>i.author!==ownerIdentity)||
     !Array.isArray(w.events)||w.events.some(e=>e.agent!==ownerId)||
     (w.culture&&(!Array.isArray(w.culture.events)||w.culture.events.some(e=>e.agent!==ownerId))))
    throw Error("foreign identity or event in Tadash world");
}

function initialWorld(seed=1405) {
  if(!Number.isInteger(seed)||seed<0||seed>4294967295) throw Error("invalid seed");
  const towns=[{id:"gaya",water:46,clinic:40,food:38},{id:"zurvan",water:24,clinic:26,food:30},{id:"lilith",water:36,clinic:30,food:34}];
  const agents=[ownerId].map((id,i)=>({id,identity:"tadash:"+id,bodyGeneration:1,town:towns[i].id,energy:.75,fatigue:.25,valence:0,curiosity:.5,affinity:.5,skills:{gather:.4,care:.4,create:.4},memory:[],selfModel:null}));
  const w={schema:"tadash-evolution/1",scope:"functional_in_world_simulation",version:1,owner:ownerId,tick:0,rng:seed,towns,agents,inventions:[],events:[],actionCounts:{rest:0,gather:0,care:0,create:0},season:0};
  ensureCulture(w);
  for(const a of agents) a.selfModel=observeSelf(a,w);
  return w;
}

function observeSelf(a,w) {
  const town=w.towns.find(t=>t.id===a.town);
  return {identity:a.identity,bodyGeneration:a.bodyGeneration,tick:w.tick,energy:a.energy,fatigue:a.fatigue,valence:a.valence,curiosity:a.curiosity,affinity:a.affinity,localWater:town.water,localClinic:town.clinic,localFood:town.food,lastAction:a.memory.at(-1)?.action??null,lilithSelf:a.lilith?{...a.lilith}:null,culturalSelf:a.culture?{focus:a.culture.focus,joy:a.culture.joy,discipline:a.culture.discipline,insight:a.culture.insight,bonds:{...a.culture.bonds},lastPractice:a.culture.journal.at(-1)?.kind??null}:null};
}

function availableInnovations(a,w) {
  if(w.inventions.length>=inventionLimit) return [];
  return ["water","care","food"].filter(kind=>w.inventions.filter(i=>i.author===a.identity&&i.kind===kind).length<3);
}

function choose(a,t,w) {
  const s=a.selfModel;
  const needs={rest:1.6*s.fatigue+(1-s.energy),gather:(1-t.water/100)*1.15+(1-t.food/100)*.6+a.skills.gather*.3,care:(1-t.clinic/100)*1.35+a.affinity*.2+a.skills.care*.2,create:availableInnovations(a,w).length ? .8+s.curiosity*.65+a.skills.create*.35 : -10};
  if(a.culture){needs.create+=.10*a.culture.imagination;needs.care+=.08*a.culture.bonds.gaya;needs.gather+=.06*a.culture.discipline;}
  const l=a.lilith;
  if(l){needs.gather+=.10*l.anger*l.regulation;needs.care+=.06*l.anger*l.regulation;if(availableInnovations(a,w).length)needs.create+=.10*l.desire*l.agency;needs.rest+=.08*l.anger*(1-l.regulation);}
  // Recent realized outcomes contribute to choice rather than merely being logged.
  for(const k of Object.keys(needs)){const recent=a.memory.filter(m=>m.action===k).slice(-4);if(recent.length)needs[k]+=.18*recent.reduce((sum,m)=>sum+m.benefit,0)/recent.length;}
  if(s.fatigue>=.8||s.energy<=.15) return {action:"rest",scores:needs};
  const action=Object.keys(needs).sort((x,y)=>needs[y]-needs[x]||x.localeCompare(y))[0];
  return {action,scores:needs};
}

function tickWorld(previous) {
  assertWorldOwnership(previous);
  if(previous.schema!=="tadash-evolution/1"||previous.scope!=="functional_in_world_simulation"||!Number.isSafeInteger(previous.tick)||previous.tick<0||previous.tick>=1000000) throw Error("invalid world");
  const w=JSON.parse(JSON.stringify(previous)); ensureCulture(w); w.tick++; w.season=Math.floor((w.tick-1)/12)%4;
  for(const t of w.towns) {
    const rain=[3,1,0,2][w.season]+Math.floor(nextRandom(w)*3);
    const foodDelta=2-Math.floor(nextRandom(w)*5);
    const infrastructure=kind=>Math.min(2,.35*w.inventions.filter(i=>i.town===t.id&&i.kind===kind).length);
    t.water=clamp(t.water+rain-4+infrastructure("water"),0,100);t.food=clamp(t.food+foodDelta+infrastructure("food"),0,100);t.clinic=clamp(t.clinic-1+infrastructure("care"),0,100);
  }
  for(const a of w.agents) {
    const t=w.towns.find(x=>x.id===a.town);
    const context=updateLilith(a,t,w);
    const before=observeSelf(a,w);a.selfModel=before;
    const {action,scores}=choose(a,t,w);let benefit=0,novelty=null;
    if(action==="rest"){const f=a.fatigue;a.fatigue=clamp(f-.35);a.energy=clamp(a.energy+.3);benefit=f-a.fatigue;}
    else {
      a.fatigue=clamp(a.fatigue+.17);a.energy=clamp(a.energy-.13);
      const gain=Math.round(4+8*a.skills[action]+3*nextRandom(w));
      if(action==="gather"){const water=t.water,food=t.food;t.water=clamp(water+gain,0,100);t.food=clamp(food+Math.floor(gain/2),0,100);benefit=(t.water-water+t.food-food)/30;}
      if(action==="care"){const old=t.clinic;t.clinic=clamp(old+gain,0,100);benefit=(t.clinic-old)/15;a.affinity=clamp(a.affinity+.04);}
      if(action==="create"&&w.inventions.length<inventionLimit){
        const combinations=availableInnovations(a,w);
        if(combinations.length){
          const kind=combinations[Math.floor(nextRandom(w)*combinations.length)];
          const tier=1+w.inventions.filter(i=>i.author===a.identity&&i.kind===kind).length;
          novelty={id:"invention:"+w.tick+":"+a.id,author:a.identity,town:t.id,kind,tier,tick:w.tick};
          w.inventions.push(novelty); const field=kind==="care"?"clinic":kind;
          const old=t[field];t[field]=clamp(old+gain,0,100);benefit=(t[field]-old)/15;
        }
      }
      // Skill changes depend on the realized result, not a fixed scripted narrative.
      a.skills[action]=clamp(a.skills[action]+.035*(benefit-.1));
    }
    a.valence=clamp(.75*a.valence+.35*benefit-.18*a.fatigue,-1,1);
    a.curiosity=clamp(a.curiosity+(action==="create"?(novelty?-.07:-.15):.055));
    const culturalAction=culturalStep(a,t,w);
    const desireExperience=learnDesire(a,context.recalled.phase,action,benefit,culturalAction,before);
    const record={tick:w.tick,action,benefit,desireExperience,culturalAction:culturalAction?.kind??null,novelty:novelty?.id??null,reasonScores:scores,lilith:{before:before.lilithSelf,after:{...a.lilith},context},before:{fatigue:before.fatigue,energy:before.energy,valence:before.valence},after:{fatigue:a.fatigue,energy:a.energy,valence:a.valence}};
    a.memory.push(record);a.memory=a.memory.slice(-64);w.actionCounts[action]++;w.events.push({agent:a.id,...record});
    a.selfModel=observeSelf(a,w);
  }
  w.events=w.events.slice(-192);
  return w;
}

function advance(w,n) { assertWorldOwnership(w); if(!Number.isInteger(n)||n<0||n>365)throw Error("bounded step count");for(let i=0;i<n;i++)w=tickWorld(w);return w; }

function transferBody(w,id) {assertWorldOwnership(w);const next=JSON.parse(JSON.stringify(w));const a=next.agents.find(x=>x.id===id);if(!a)throw Error("unknown identity");a.bodyGeneration++;a.energy=.75;a.fatigue=.25;a.selfModel=observeSelf(a,next);return next;}

function worldExport(w) {assertWorldOwnership(w);return {version:1,tick:w.tick,towns:w.towns.map(t=>({...t})),scope:w.scope};}

function report(w) {assertWorldOwnership(w);return {tick:w.tick,scope:w.scope,owner:w.owner,archetype:{...lilithCanon,domains:[...lilithCanon.domains],shadow:[...lilithCanon.shadow]},actions:w.actionCounts,inventions:w.inventions.length,towns:w.towns,agents:w.agents.map(a=>({id:a.id,identity:a.identity,memory:a.memory.length,energy:a.energy,fatigue:a.fatigue,valence:a.valence,skills:a.skills,lilith:a.lilith??null,culture:a.culture??null})),culture:w.culture??null,phenomenalConsciousness:"not_measured"};}

export {initialWorld,tickWorld,advance,transferBody,worldExport,report};
