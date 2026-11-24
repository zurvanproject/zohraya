// Seventy-two Gates of Fire: finite, authored laws inside Tadash.
// Browser-compatible pure state operations; no network, timers, tools or extra agents.
const OWNER = "tadash:nasuraya";
const SCHEMA = "tadash-goetia/1";
const MAX_ACTIONS = 1000001;
const HISTORY_LIMIT = 64;
const DOMAINS = Object.freeze([
  "knowledge", "revelation", "craft", "vitality", "bonds", "desire", "ward", "discord",
  "flame", "water", "passage", "transformation", "remembrance", "veil", "art", "nature"
]);
const EFFECTS = Object.freeze({
  knowledge: "insight +0.06p",
  revelation: "observe current town resources; all towns at stage 2+; no forecast",
  craft: "create skill +0.04p; coordination +0.02p",
  vitality: "local clinic +4p",
  bonds: "weaker own founder/Gaia bond +0.04p; affinity +0.02p",
  desire: "own creative drive +0.04p; agency +0.02p",
  ward: "regulation +0.04p; discipline +0.02p",
  discord: "shadow insight +0.04p; anger -0.02p",
  flame: "anger -0.04p; create skill +0.02p",
  water: "local water +4p",
  passage: "move Nasuraya to an existing town, preserving identity and history",
  transformation: "convert up to 4p local resource units, conserving their sum",
  remembrance: "recall latest existing own decision; insight +0.02p if one exists",
  veil: "focus +0.04p; anger -0.02p",
  art: "joy +0.04p; imagination +0.02p",
  nature: "local food +4p"
});
const clamp = (x, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, x));
const clone = x => JSON.parse(JSON.stringify(x));
const bounded = (x, lo, hi) => Number.isFinite(x) && x >= lo && x <= hi;
const count = x => Number.isSafeInteger(x) && x >= 0 && x <= MAX_ACTIONS;
const fail = message => { throw Error(`Goetia: ${message}`); };

function assertOwnProvenance(value) {
  if (!value || typeof value !== "object") return;
  for (const [key, item] of Object.entries(value)) {
    if ((key === "agent" && item !== "nasuraya") ||
        (["identity", "author"].includes(key) && item !== OWNER) ||
        (key === "owner" && item !== OWNER && item !== "nasuraya")) fail("foreign memory identity");
    if (item && typeof item === "object") assertOwnProvenance(item);
  }
}

function assertBase(w) {
  if (!w || w.schema !== "tadash-evolution/1" || w.scope !== "functional_in_world_simulation" ||
      w.owner !== "nasuraya" || !Array.isArray(w.agents) || w.agents.length !== 1 ||
      w.agents[0].id !== "nasuraya" || w.agents[0].identity !== OWNER)
    fail("isolated Nasuraya world required");
  if (!Number.isSafeInteger(w.tick) || w.tick < 0 || w.tick > 1000000) fail("invalid world tick");
  const a = w.agents[0];
  if (!Array.isArray(w.towns) || w.towns.length !== 3 ||
      new Set(w.towns.map(t => t.id)).size !== w.towns.length ||
      w.towns.some(t => !["gaya", "zurvan", "lilith"].includes(t.id) ||
        ["water", "food", "clinic"].some(k => !bounded(t[k], 0, 100))) ||
      !w.towns.some(t => t.id === a.town)) fail("invalid towns");
  if (["energy", "fatigue", "affinity"].some(k => !bounded(a[k], 0, 1)) ||
      !bounded(a.valence, -1, 1) || !Array.isArray(a.memory) || a.memory.length > 64 ||
      !a.skills || ["gather", "care", "create"].some(k => !bounded(a.skills[k], 0, 1)))
    fail("invalid agent state");
  for (const m of a.memory) {
    if (!m || !Number.isSafeInteger(m.tick) || m.tick < 0 || m.tick > w.tick ||
        !["rest", "gather", "care", "create"].includes(m.action) || !Number.isFinite(m.benefit))
      fail("invalid decision memory");
    assertOwnProvenance(m);
  }
  if (!a.culture || ["focus", "joy", "discipline", "imagination", "coordination", "insight"].some(k => !bounded(a.culture[k], 0, 1)) ||
      !a.culture.bonds || ["founder", "gaya"].some(k => !bounded(a.culture.bonds[k], 0, 1)) ||
      !a.lilith || a.lilith.lineage !== "symbolic daughter of Lilith" ||
      ["anger", "desire", "agency", "shadowInsight", "nightAffinity", "regulation"].some(k => !bounded(a.lilith[k], 0, 1)))
    fail("culture and Lilith state required; migrate older snapshots with tickWorld first");
  if (a.lilith.memory !== undefined && (!a.lilith.memory || ["day", "night"].some(k =>
      !a.lilith.memory[k] || !bounded(a.lilith.memory[k].strength, -1, 1) ||
      !Number.isSafeInteger(a.lilith.memory[k].count) || a.lilith.memory[k].count < 0 || a.lilith.memory[k].count > 1000000)))
    fail("invalid desire memory");
  if ((a.selfModel && a.selfModel.identity !== OWNER) || !Array.isArray(w.events) ||
      w.events.some(e => e.agent !== "nasuraya") || !Array.isArray(w.inventions) ||
      w.inventions.some(e => e.author !== OWNER) || !w.culture || !Array.isArray(w.culture.events) ||
      w.culture.events.some(e => e.agent !== "nasuraya")) fail("foreign identity or history");
}

function definitionsFrom(catalogue) {
  if (!Array.isArray(catalogue) || catalogue.length !== 72) fail("catalogue must contain exactly 72 entries");
  const defs = catalogue.map(entry => ({id: entry.id, name: entry.name, domain: entry.tadash?.domain ?? entry.domain}));
  validateDefinitions(defs);
  return defs;
}

function validateDefinitions(defs) {
  if (!Array.isArray(defs) || defs.length !== 72 || defs.some((d, i) =>
    !d || d.id !== i + 1 || typeof d.name !== "string" || d.name.length < 1 || d.name.length > 80 || !DOMAINS.includes(d.domain)))
    fail("invalid ordered gate definitions");
}

function assertGoetiaState(w) {
  if (w?.goetia === undefined) return;
  assertBase(w);
  const s = w.goetia;
  if (!s || s.schema !== SCHEMA || s.owner !== OWNER || s.scope !== "authored_in_world_mechanics" ||
      typeof s.autoPractice !== "boolean" || !Number.isInteger(s.selectedGate) || s.selectedGate < 1 || s.selectedGate > 72 ||
      !Number.isInteger(s.lastActionTick) || s.lastActionTick < -1 || s.lastActionTick > w.tick ||
      !count(s.totalPractice) || !count(s.totalCasts) || s.totalPractice + s.totalCasts > MAX_ACTIONS)
    fail("invalid school state");
  validateDefinitions(s.definitions);
  if (!Array.isArray(s.gates) || s.gates.length !== 72 || s.gates.some((g, i) =>
    !g || g.id !== i + 1 || !count(g.repetitions) || !count(g.qualified) || !count(g.casts) ||
    g.qualified > g.repetitions || g.stage !== Math.min(4, Math.floor(g.qualified / 3)) ||
    !Number.isInteger(g.lastPracticeTick) || !Number.isInteger(g.lastCastTick) ||
    g.lastPracticeTick < -1 || g.lastCastTick < -1 || g.lastPracticeTick > s.lastActionTick || g.lastCastTick > s.lastActionTick ||
    (g.repetitions === 0) !== (g.lastPracticeTick === -1) || (g.casts === 0) !== (g.lastCastTick === -1)))
    fail("invalid mastery or gate timestamps");
  const practices = s.gates.reduce((n, g) => n + g.repetitions, 0);
  const casts = s.gates.reduce((n, g) => n + g.casts, 0);
  const last = Math.max(-1, ...s.gates.flatMap(g => [g.lastPracticeTick, g.lastCastTick]));
  const total = practices + casts;
  if (practices !== s.totalPractice || casts !== s.totalCasts || last !== s.lastActionTick || total > w.tick + 1 ||
      !Array.isArray(s.history) || s.history.length !== Math.min(HISTORY_LIMIT, total))
    fail("inconsistent school counters");
  let priorTick = -1;
  for (let i = 0; i < s.history.length; i++) {
    const e = s.history[i];
    if (!e || e.owner !== OWNER || e.sequence !== total - s.history.length + i + 1 ||
        !Number.isInteger(e.tick) || e.tick <= priorTick || e.tick > w.tick ||
        !Number.isInteger(e.gate) || e.gate < 1 || e.gate > 72 || e.domain !== s.definitions[e.gate - 1].domain || !["practice", "cast"].includes(e.kind) ||
        !["qualified", "unqualified", "changed", "observed", "no_effect", "fizzle"].includes(e.outcome) ||
        !bounded(e.quality, 0, 1) || !Number.isInteger(e.stage) || e.stage < 0 || e.stage > 4 ||
        !bounded(e.energyCost, 0, 1) || !bounded(e.fatigueChange, -1, 1) ||
        !Array.isArray(e.changes) || e.changes.length > 4 || e.changes.some(c =>
          !c || typeof c.field !== "string" || c.field.length > 80 ||
          !((Number.isFinite(c.before) && Number.isFinite(c.after)) || (typeof c.before === "string" && typeof c.after === "string"))))
      fail("invalid gate history");
    if (e.changes.some(c => {
      if (c.field === "town") return ![c.before, c.after].every(id => w.towns.some(t => t.id === id));
      const resource = /^(gaya|zurvan|lilith)\.(water|food|clinic)$/.test(c.field);
      const trait = /^(culture\.(insight|coordination|discipline|focus|joy|imagination|bonds\.(founder|gaya))|skills\.create|affinity|lilith\.(desire|agency|regulation|shadowInsight|anger))$/.test(c.field);
      return !(resource || trait) || !bounded(c.before, 0, resource ? 100 : 1) || !bounded(c.after, 0, resource ? 100 : 1) || c.before === c.after;
    })) fail("invalid recorded effect");
    if (e.observation !== null) {
      const o = e.observation;
      if (!o || o.asOfTick !== e.tick ||
          !(o.kind === "current_simulated_resources" && e.domain === "revelation" &&
            Array.isArray(o.towns) && o.towns.length === (e.stage >= 2 ? 3 : 1) &&
            new Set(o.towns.map(t => t.id)).size === o.towns.length && o.towns.every(t =>
              w.towns.some(known => known.id === t.id) && ["water", "food", "clinic"].every(k => bounded(t[k], 0, 100))) ||
            o.kind === "own_recorded_decision" && e.domain === "remembrance" &&
            Number.isSafeInteger(o.memoryTick) && o.memoryTick >= 0 && o.memoryTick <= e.tick &&
            ["rest", "gather", "care", "create"].includes(o.action) && Number.isFinite(o.benefit)))
        fail("invalid recorded observation");
    }
    if (e.kind === "practice") {
      if (e.changes.length || e.observation !== null || e.outcome !== (e.quality >= .60 ? "qualified" : "unqualified"))
        fail("invalid practice outcome");
    } else {
      const expected = e.quality < .60 ? "fizzle" : e.changes.length ? "changed" : e.observation ? "observed" : "no_effect";
      if (e.stage < 1 || e.outcome !== expected || (e.quality < .60 && (e.changes.length || e.observation !== null)))
        fail("invalid cast outcome");
    }
    priorTick = e.tick;
  }
  if (s.history.length && s.history.at(-1).tick !== s.lastActionTick) fail("history timestamp mismatch");
}

function requireSchool(w) {
  assertBase(w);
  if (!w.goetia) fail("school is not enabled");
  assertGoetiaState(w);
}

function selected(w, id) {
  const gate = id ?? w.goetia?.selectedGate;
  if (!Number.isInteger(gate) || gate < 1 || gate > 72) fail("unknown gate");
  return gate;
}

function goetiaSelf(w) {
  if (!w.goetia) return null;
  const s = w.goetia, g = s.gates[s.selectedGate - 1];
  return {selectedGate: s.selectedGate, stage: g.stage, qualified: g.qualified,
    lastActionTick: s.lastActionTick, totalPractice: s.totalPractice, totalCasts: s.totalCasts};
}

function refreshSelf(w) {
  const a = w.agents[0], t = w.towns.find(town => town.id === a.town), c = a.culture;
  a.selfModel = {...a.selfModel, identity: OWNER, bodyGeneration: a.bodyGeneration, tick: w.tick,
    energy: a.energy, fatigue: a.fatigue, valence: a.valence, curiosity: a.curiosity, affinity: a.affinity,
    localWater: t.water, localClinic: t.clinic, localFood: t.food,
    lastAction: a.memory.at(-1)?.action ?? null, lilithSelf: clone(a.lilith),
    culturalSelf: {focus: c.focus, joy: c.joy, discipline: c.discipline, insight: c.insight,
      bonds: {...c.bonds}, lastPractice: c.journal.at(-1)?.kind ?? null}, goetiaSelf: goetiaSelf(w)};
}

function enableGoetia(world, catalogue, options = {}) {
  assertBase(world);
  if (world.goetia !== undefined) fail("school already exists; select a gate without resetting mastery");
  const defs = definitionsFrom(catalogue);
  if (options.autoPractice !== undefined && typeof options.autoPractice !== "boolean") fail("invalid autoPractice option");
  const id = selected(world, options.selectedGate ?? 1);
  const w = clone(world);
  w.goetia = {schema: SCHEMA, owner: OWNER, scope: "authored_in_world_mechanics",
    definitions: defs, selectedGate: id, autoPractice: options.autoPractice ?? true,
    lastActionTick: -1, totalPractice: 0, totalCasts: 0,
    gates: defs.map(d => ({id: d.id, repetitions: 0, qualified: 0, stage: 0, casts: 0, lastPracticeTick: -1, lastCastTick: -1})), history: []};
  refreshSelf(w);
  return w;
}

function selectGoetiaGate(world, gateId, options = {}) {
  requireSchool(world);
  const id = selected(world, gateId);
  if (options.autoPractice !== undefined && typeof options.autoPractice !== "boolean") fail("invalid autoPractice option");
  const w = clone(world);
  w.goetia.selectedGate = id;
  if (options.autoPractice !== undefined) w.goetia.autoPractice = options.autoPractice;
  refreshSelf(w);
  return w;
}

function quality(a, stage) {
  return clamp(.35 + .35 * a.energy + .20 * a.culture.focus + .10 * a.lilith.regulation - .30 * a.fatigue + .02 * stage);
}

function checkAction(w, cost) {
  if (w.goetia.lastActionTick >= w.tick) fail("one gate action per world tick; advance the world first");
  if (w.goetia.totalPractice + w.goetia.totalCasts >= MAX_ACTIONS) fail("bounded action budget exhausted");
  const a = w.agents[0];
  if (a.energy < cost + .10 || a.fatigue > .85) fail("insufficient energy or recovery");
}

function record(w, gate, kind, q, outcome, beforeEnergy, beforeFatigue, changes = [], observation = null) {
  const s = w.goetia, a = w.agents[0], g = s.gates[gate - 1];
  const event = {sequence: s.totalPractice + s.totalCasts, tick: w.tick, owner: OWNER,
    gate, kind, domain: s.definitions[gate - 1].domain, quality: q, stage: g.stage, outcome,
    energyCost: beforeEnergy - a.energy, fatigueChange: a.fatigue - beforeFatigue, changes, observation};
  s.lastActionTick = w.tick;
  s.history.push(event);
  s.history = s.history.slice(-HISTORY_LIMIT);
  return event;
}

function practiceInPlace(w, id) {
  const a = w.agents[0], s = w.goetia, g = s.gates[id - 1];
  const cost = .04;
  checkAction(w, cost);
  const q = quality(a, g.stage), e = a.energy, f = a.fatigue;
  a.energy = clamp(a.energy - cost);
  a.fatigue = clamp(a.fatigue + .025);
  g.repetitions++;
  g.lastPracticeTick = w.tick;
  if (q >= .60) g.qualified++;
  g.stage = Math.min(4, Math.floor(g.qualified / 3));
  s.totalPractice++;
  return record(w, id, "practice", q, q >= .60 ? "qualified" : "unqualified", e, f);
}

function practiceGate(world, gateId) {
  requireSchool(world);
  const id = selected(world, gateId), w = clone(world);
  practiceInPlace(w, id);
  refreshSelf(w);
  return w;
}

// Internal host hook: called only on a freshly cloned world during culturalStep.
function automaticGatePractice(w) {
  requireSchool(w);
  if (!w.goetia.autoPractice) return null;
  const a = w.agents[0];
  if (w.goetia.lastActionTick >= w.tick || a.energy < .14 || a.fatigue > .85) return null;
  return practiceInPlace(w, w.goetia.selectedGate);
}

function validatedCastOptions(w, domain, options) {
  if (!options || typeof options !== "object" || Array.isArray(options)) fail("invalid cast options");
  const allowed = domain === "passage" ? ["targetTown"] : domain === "transformation" ? ["from", "to"] : [];
  if (Object.keys(options).some(k => !allowed.includes(k))) fail("unsupported cast option");
  if (domain === "passage") {
    if (!w.towns.some(t => t.id === options.targetTown)) fail("passage requires an existing targetTown");
  }
  if (domain === "transformation") {
    const from = options.from ?? "water", to = options.to ?? "food";
    if (!["water", "food", "clinic"].includes(from) || !["water", "food", "clinic"].includes(to) || from === to)
      fail("transformation requires two different resources");
    return {from, to};
  }
  return options;
}

function applyEffect(w, domain, potency, stage, options) {
  const a = w.agents[0], c = a.culture, l = a.lilith, t = w.towns.find(town => town.id === a.town);
  const changes = [];
  let observation = null;
  const add = (obj, key, amount, field, max = 1) => {
    const before = obj[key], after = clamp(before + amount, 0, max);
    obj[key] = after;
    if (after !== before) changes.push({field, before, after});
  };
  switch (domain) {
    case "knowledge": add(c, "insight", .06 * potency, "culture.insight"); break;
    case "revelation":
      observation = {kind: "current_simulated_resources", asOfTick: w.tick,
        towns: (stage >= 2 ? w.towns : [t]).map(town => ({...town}))};
      break;
    case "craft":
      add(a.skills, "create", .04 * potency, "skills.create");
      add(c, "coordination", .02 * potency, "culture.coordination");
      break;
    case "vitality": add(t, "clinic", 4 * potency, `${t.id}.clinic`, 100); break;
    case "bonds": {
      const target = c.bonds.founder <= c.bonds.gaya ? "founder" : "gaya";
      add(c.bonds, target, .04 * potency, `culture.bonds.${target}`);
      add(a, "affinity", .02 * potency, "affinity");
      break;
    }
    case "desire":
      add(l, "desire", .04 * potency, "lilith.desire");
      add(l, "agency", .02 * potency, "lilith.agency");
      break;
    case "ward":
      add(l, "regulation", .04 * potency, "lilith.regulation");
      add(c, "discipline", .02 * potency, "culture.discipline");
      break;
    case "discord":
      add(l, "shadowInsight", .04 * potency, "lilith.shadowInsight");
      add(l, "anger", -.02 * potency, "lilith.anger");
      break;
    case "flame":
      add(l, "anger", -.04 * potency, "lilith.anger");
      add(a.skills, "create", .02 * potency, "skills.create");
      break;
    case "water": add(t, "water", 4 * potency, `${t.id}.water`, 100); break;
    case "passage":
      if (a.town !== options.targetTown) {
        changes.push({field: "town", before: a.town, after: options.targetTown});
        a.town = options.targetTown;
      }
      break;
    case "transformation": {
      const n = Math.min(4 * potency, t[options.from], 100 - t[options.to]);
      add(t, options.from, -n, `${t.id}.${options.from}`, 100);
      add(t, options.to, n, `${t.id}.${options.to}`, 100);
      break;
    }
    case "remembrance": {
      const m = a.memory.at(-1);
      if (m && Number.isSafeInteger(m.tick) && m.tick <= w.tick && typeof m.action === "string" && Number.isFinite(m.benefit)) {
        observation = {kind: "own_recorded_decision", asOfTick: w.tick, memoryTick: m.tick, action: m.action, benefit: m.benefit};
        add(c, "insight", .02 * potency, "culture.insight");
      }
      break;
    }
    case "veil":
      add(c, "focus", .04 * potency, "culture.focus");
      add(l, "anger", -.02 * potency, "lilith.anger");
      break;
    case "art":
      add(c, "joy", .04 * potency, "culture.joy");
      add(c, "imagination", .02 * potency, "culture.imagination");
      break;
    case "nature": add(t, "food", 4 * potency, `${t.id}.food`, 100); break;
    default: fail("unsupported domain");
  }
  return {changes, observation};
}

function castGate(world, gateId, options = {}) {
  requireSchool(world);
  const id = selected(world, gateId), domain = world.goetia.definitions[id - 1].domain;
  const opts = validatedCastOptions(world, domain, options), g0 = world.goetia.gates[id - 1];
  if (g0.stage < 1) fail("three qualified practices are required before casting");
  const cost = .08 + .01 * g0.stage;
  checkAction(world, cost);
  const w = clone(world), a = w.agents[0], g = w.goetia.gates[id - 1];
  const q = quality(a, g.stage), e = a.energy, f = a.fatigue;
  a.energy = clamp(a.energy - cost);
  a.fatigue = clamp(a.fatigue + .04);
  g.casts++;
  g.lastCastTick = w.tick;
  w.goetia.totalCasts++;
  const effect = q >= .60 ? applyEffect(w, domain, q * g.stage / 4, g.stage, opts) : {changes: [], observation: null};
  const outcome = q < .60 ? "fizzle" : effect.changes.length ? "changed" : effect.observation ? "observed" : "no_effect";
  record(w, id, "cast", q, outcome, e, f, effect.changes, effect.observation);
  refreshSelf(w);
  return w;
}

function goetiaReport(w) {
  requireSchool(w);
  const s = w.goetia;
  return {schema: s.schema, scope: s.scope, owner: s.owner, gateCount: 72, domainCount: DOMAINS.length,
    autoPractice: s.autoPractice, selectedGate: s.selectedGate, totalPractice: s.totalPractice, totalCasts: s.totalCasts,
    unlocked: s.gates.filter(g => g.stage >= 1).length, mastered: s.gates.filter(g => g.stage === 4).length,
    gates: s.gates.map((g, i) => ({...g, ...s.definitions[i], implementedEffect: EFFECTS[s.definitions[i].domain]})),
    mechanics: {quality: "clamp(.35 + .35E + .20Focus + .10Regulation - .30Fatigue + .02Stage, 0, 1)",
      qualification: .60, practicesPerStage: 3, maxStage: 4, practiceEnergy: .04, practiceFatigue: .025,
      castEnergy: ".08 + .01Stage", castFatigue: .04, potency: "quality * stage / 4",
      actionsPerWorldTick: 1, historyLimit: HISTORY_LIMIT, effects: {...EFFECTS}}, history: clone(s.history)};
}

export {enableGoetia, selectGoetiaGate, practiceGate, castGate, goetiaReport, assertGoetiaState,
  automaticGatePractice, goetiaSelf, DOMAINS, EFFECTS};
