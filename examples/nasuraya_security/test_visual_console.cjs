// Execute the actual UI state logic in Node. No browser/pixel-accuracy claim.
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const template=fs.readFileSync(path.join(__dirname,'visual_console.html'),'utf8');
const script=template.split('<script>\n')[1].split('</script>')[0];
const epoch=Date.parse('2026-10-16T20:00:00Z');
function fixture(){return {schema:'nasuraya.visual-status.v2',observed_at:new Date(epoch).toISOString(),ttl_seconds:120,state:'healthy',checks:{source:'pass',audit:'pass'},reasons:[],audit:{latched:false,events:0,warnings:0,capacity_stop:false,recent:[]},expected_manifest_sha256:'a'.repeat(64),scope:'local_guard_sources_and_audit_only'};}
function run(report,offset=0){
  const clock={wall:epoch+offset,mono:0};
  const nodes={};
  const node=()=>({textContent:'',children:[],appendChild(x){this.children.push(x);},addEventListener(){}});
  const document={body:{className:'unknown'},getElementById(id){return nodes[id]??=node();},createElement:node,addEventListener(){}};
  document.getElementById('snapshot').textContent=typeof report==='string'?report:JSON.stringify(report);
  class ClockDate extends Date{static now(){return clock.wall;}}
  let interval;
  vm.runInNewContext(script,{document,Date:ClockDate,performance:{now:()=>clock.mono},setInterval(fn){interval=fn;}},{timeout:1000});
  return {document,nodes,advance(ms,wall=ms){clock.mono+=ms;clock.wall+=wall;interval();}};
}
let checks=0;
function state(report,expected,offset=0){assert.equal(run(report,offset).document.body.className,expected);checks++;}
state(fixture(),'healthy');
state(fixture(),'unknown',121000);
state(fixture(),'unknown',-6000);
state('{}','unknown');
state('{broken','unknown');
state({...fixture(),ttl_seconds:999999},'unknown');
state({...fixture(),state:'healthy',audit:{...fixture().audit,latched:true}},'unknown');
state({...fixture(),state:'warning',audit:{...fixture().audit,events:2,warnings:1}},'warning');
state({...fixture(),state:'blocked',audit:{...fixture().audit,latched:true}},'blocked');
state({...fixture(),state:'blocked',checks:{source:'fail',audit:'unknown'},audit:{...fixture().audit,latched:null,events:null,warnings:null}},'blocked');
state({...fixture(),state:'healthy',expected_manifest_sha256:null},'unknown');
state({...fixture(),reasons:['<script>evil</script>']},'unknown');
const stale=run(fixture());stale.advance(121000);assert.equal(stale.document.body.className,'unknown');checks++;
const rollback=run(fixture());rollback.advance(1000,-10000);assert.equal(rollback.document.body.className,'unknown');rollback.advance(1000,12000);assert.equal(rollback.document.body.className,'unknown');checks++;
const blocked=run({...fixture(),state:'blocked',audit:{...fixture().audit,latched:true}});blocked.advance(121000);assert.equal(blocked.document.body.className,'unknown');assert.match(blocked.nodes.latch.textContent,/آخرین مشاهده.*فعال/);checks++;
assert.ok(!template.includes('innerHTML')&&!template.includes('fetch(')&&!template.includes('XMLHttpRequest'));checks++;
console.log(`${checks} visual state checks passed (Node VM; not browser rendering)`);
