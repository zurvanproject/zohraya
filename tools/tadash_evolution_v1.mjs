// Tadash: bounded evolutionary world, isolated simulation only.
// No model calls, network, timers, or external actions.
function clamp(x, a=0, b=1) { return Math.min(b,Math.max(a,x)); }

function nextRandom(w) { w.rng=(Math.imul(w.rng,1664525)+1013904223)>>>0; return w.rng/4294967296; }

function initialWorld(seed=1405) {
  if(!Number.isInteger(seed)||seed<0||seed>4294967295) throw Error("invalid seed");
  const towns=[{id:"gaya",water:46,clinic:40,food:38},{id:"zurvan",water:24,clinic:26,food:30},{id:"lilith",water:36,clinic:30,food:34}];
  const agents=["nasuraya","asalameh","niara"].map((id,i)=>({id,identity:"tadash:"+id,bodyGeneration:1,town:towns[i].id,energy:.75,fatigue:.25,valence:0,curiosity:.5,affinity:.5,skills:{gather:.4,care:.4,create:.4},memory:[],selfModel:null}));
  const w={schema:"tadash-evolution/1",scope:"functional_in_world_simulation",version:1,tick:0,rng:seed,towns,agents,inventions:[],events:[],actionCounts:{rest:0,gather:0,care:0,create:0},season:0};
  for(const a of agents) a.selfModel=observeSelf(a,w);
  return w;
}

function observeSelf(a,w) {
  const town=w.towns.find(t=>t.id===a.town);
  return {identity:a.identity,bodyGeneration:a.bodyGeneration,tick:w.tick,energy:a.energy,fatigue:a.fatigue,valence:a.valence,curiosity:a.curiosity,affinity:a.affinity,localWater:town.water,localClinic:town.clinic,localFood:town.food,lastAction:a.memory.at(-1)?.action??null};
}

function availableInnovations(a,w) {
  if(w.inventions.length>=24) return [];
  return ["water","care","food"].filter(kind=>w.inventions.filter(i=>i.author===a.identity&&i.kind===kind).length<3);
}

function choose(a,t,w) {
  const s=a.selfModel;
  const needs={rest:1.6*s.fatigue+(1-s.energy),gather:(1-t.water/100)*1.15+(1-t.food/100)*.6+a.skills.gather*.3,care:(1-t.clinic/100)*1.35+a.affinity*.2+a.skills.care*.2,create:availableInnovations(a,w).length ? .8+s.curiosity*.65+a.skills.create*.35 : -10};
  // Recent realized outcomes contribute to choice rather than merely being logged.
  for(const k of Object.keys(needs)){const recent=a.memory.filter(m=>m.action===k).slice(-4);if(recent.length)needs[k]+=.18*recent.reduce((sum,m)=>sum+m.benefit,0)/recent.length;}
  if(s.fatigue>=.8||s.energy<=.15) return {action:"rest",scores:needs};
  const action=Object.keys(needs).sort((x,y)=>needs[y]-needs[x]||x.localeCompare(y))[0];
  return {action,scores:needs};
}

function tickWorld(previous) {
  if(previous.schema!=="tadash-evolution/1"||previous.scope!=="functional_in_world_simulation"||!Number.isSafeInteger(previous.tick)||previous.tick<0||previous.tick>=1000000) throw Error("invalid world");
  const w=JSON.parse(JSON.stringify(previous)); w.tick++; w.season=Math.floor((w.tick-1)/12)%4;
  for(const t of w.towns) {
    const rain=[3,1,0,2][w.season]+Math.floor(nextRandom(w)*3);
    const foodDelta=2-Math.floor(nextRandom(w)*5);
    const infrastructure=kind=>Math.min(2,.35*w.inventions.filter(i=>i.town===t.id&&i.kind===kind).length);
    t.water=clamp(t.water+rain-4+infrastructure("water"),0,100);t.food=clamp(t.food+foodDelta+infrastructure("food"),0,100);t.clinic=clamp(t.clinic-1+infrastructure("care"),0,100);
  }
  for(const a of w.agents) {
    const t=w.towns.find(x=>x.id===a.town);
    const before=observeSelf(a,w);a.selfModel=before;
    const {action,scores}=choose(a,t,w);let benefit=0,novelty=null;
    if(action==="rest"){const f=a.fatigue;a.fatigue=clamp(f-.35);a.energy=clamp(a.energy+.3);benefit=f-a.fatigue;}
    else {
      a.fatigue=clamp(a.fatigue+.17);a.energy=clamp(a.energy-.13);
      const gain=Math.round(4+8*a.skills[action]+3*nextRandom(w));
      if(action==="gather"){const water=t.water,food=t.food;t.water=clamp(water+gain,0,100);t.food=clamp(food+Math.floor(gain/2),0,100);benefit=(t.water-water+t.food-food)/30;}
      if(action==="care"){const old=t.clinic;t.clinic=clamp(old+gain,0,100);benefit=(t.clinic-old)/15;a.affinity=clamp(a.affinity+.04);}
      if(action==="create"&&w.inventions.length<24){
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
    const record={tick:w.tick,action,benefit,novelty:novelty?.id??null,reasonScores:scores,before:{fatigue:before.fatigue,energy:before.energy,valence:before.valence},after:{fatigue:a.fatigue,energy:a.energy,valence:a.valence}};
    a.memory.push(record);a.memory=a.memory.slice(-64);w.actionCounts[action]++;w.events.push({agent:a.id,...record});
    a.selfModel=observeSelf(a,w);
  }
  w.events=w.events.slice(-192);
  return w;
}

function advance(w,n) { if(!Number.isInteger(n)||n<0||n>365)throw Error("bounded step count");for(let i=0;i<n;i++)w=tickWorld(w);return w; }

function transferBody(w,id) {const next=JSON.parse(JSON.stringify(w));const a=next.agents.find(x=>x.id===id);if(!a)throw Error("unknown identity");a.bodyGeneration++;a.energy=.75;a.fatigue=.25;a.selfModel=observeSelf(a,next);return next;}

function worldExport(w) {return {version:1,tick:w.tick,towns:w.towns.map(t=>({...t})),scope:w.scope};}

function report(w) {return {tick:w.tick,scope:w.scope,actions:w.actionCounts,inventions:w.inventions.length,towns:w.towns,agents:w.agents.map(a=>({id:a.id,identity:a.identity,memory:a.memory.length,energy:a.energy,fatigue:a.fatigue,valence:a.valence,skills:a.skills})),phenomenalConsciousness:"not_measured"};}

export {initialWorld,tickWorld,advance,transferBody,worldExport,report};
