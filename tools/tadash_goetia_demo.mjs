// Run from any directory: node tools/tadash_goetia_demo.mjs
// A reproducible demonstration; all actions remain inside the simulated world.
import {readFileSync, writeFileSync} from 'node:fs';
import {initialWorld, tickWorld, advance, transferBody, enableGoetia,
  selectGoetiaGate, practiceGate, castGate, goetiaReport} from './tadash_evolution_v1.mjs';

const catalogue = JSON.parse(readFileSync(new URL('./data/tadash_goetia_72.json', import.meta.url), 'utf8'));
let world = enableGoetia(initialWorld(1405), catalogue, {selectedGate: 9, autoPractice: false});
const receipts = [];

function train(id) {
  world = selectGoetiaGate(world, id, {autoPractice: false});
  const first = world.tick;
  while (world.goetia.gates[id - 1].stage < 1) {
    if (world.tick - first > 500) throw Error(`Training budget exhausted for ${id}`);
    world = tickWorld(world);
    const a = world.agents[0];
    if (a.energy >= .14 && a.fatigue <= .85) world = practiceGate(world, id);
  }
  return {...world.goetia.gates[id - 1]};
}

for (const item of [
  {id: 9}, {id: 10}, {id: 12}, {id: 34},
  {id: 48, options: {from: 'water', to: 'food'}},
  {id: 70, options: {targetTown: 'zurvan'}}, {id: 4}
]) {
  const training = train(item.id);
  const attempts = [];
  for (let tries = 0; tries < 50; tries++) {
    world = tickWorld(world);
    const a = world.agents[0];
    const cost = .08 + .01 * world.goetia.gates[item.id - 1].stage;
    if (a.energy < cost + .1 || a.fatigue > .85) continue;
    world = castGate(world, item.id, item.options ?? {});
    const result = world.goetia.history.at(-1);
    attempts.push(result);
    if (result.outcome !== 'fizzle') break;
  }
  if (!attempts.length) throw Error(`No cast opportunity for ${item.id}`);
  receipts.push({id: item.id, name: catalogue[item.id - 1].name,
    nameFa: catalogue[item.id - 1].fa, training, attempts});
}

const checkpoint = JSON.parse(JSON.stringify(world));
const resumed = advance(checkpoint, 20);
const uninterrupted = advance(world, 20);
const transferred = transferBody(world, 'nasuraya');
const checks = {
  resumedEqualsUninterrupted: JSON.stringify(resumed) === JSON.stringify(uninterrupted),
  bodyTransferPreservesSchool: JSON.stringify(transferred.goetia) === JSON.stringify(world.goetia),
  singleAgent: world.agents.length === 1 && world.agents[0].identity === 'tadash:nasuraya',
  allReceiptsHaveEvidence: receipts.every(r => r.attempts.length && r.training.qualified >= 3)
};
if (Object.values(checks).some(v => !v)) throw Error('Demonstration contract failed');
// Optional explicit checkpoint destination; no file is written by default.
if (process.argv.length > 2) {
  if (process.argv.length !== 4 || process.argv[2] !== '--checkpoint')
    throw Error('Usage: node tools/tadash_goetia_demo.mjs [--checkpoint path.json]');
  writeFileSync(process.argv[3], JSON.stringify(world, null, 2) + '\n');
}
console.log(JSON.stringify({schema: 'tadash-goetia-demo/1', seed: 1405,
  scope: 'executed_finite_world_simulation', finalTick: world.tick,
  receipts, checks, report: goetiaReport(world)}, null, 2));
