'use strict';
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const match = src.match(/<script>([\s\S]*?)<\/script>/);
assert.ok(match, 'inline JS present');
assert.ok(!/(fetch\s*\(|XMLHttpRequest|localStorage)/.test(match[1]), 'offline, no storage or network');
const source = match[1].replace(/  fresh\(\);\s*\}\)\(\);\s*$/, `
  fresh();
  const results=[];
  for (let i=0;i<30;i++) {
    fresh();let n=0;
    while (!world.done && n<160) {
      const move=route();
      if (!move || !step(...move)) throw new Error('invalid step, game '+i);
      n++;
    }
    if (!world.done || world.found!==TARGET) throw new Error('game not completed '+i);
    results.push({steps:world.steps,score:world.score});
  }
  globalThis.__results=results;
})();`);
const elements={};
const canvas={width:720,height:720,getContext(){return {
  createLinearGradient(){return{addColorStop(){}}}, clearRect(){},fillRect(){},beginPath(){},arc(){},fill(){},moveTo(){},lineTo(){},closePath(){},stroke(){}
}}};
const document={getElementById(id){if(id==='garden')return canvas;return elements[id]??={textContent:'',addEventListener(){}}},querySelectorAll(){return[]}};
const sandbox={document,window:{addEventListener(){}},setInterval(){},clearInterval(){}};
vm.createContext(sandbox);
vm.runInContext(source,sandbox,{timeout:15000});
assert.equal(sandbox.__results.length,30);
console.log(JSON.stringify({games:30,completed:30,min_steps:Math.min(...sandbox.__results.map(x=>x.steps)),max_steps:Math.max(...sandbox.__results.map(x=>x.steps))}));