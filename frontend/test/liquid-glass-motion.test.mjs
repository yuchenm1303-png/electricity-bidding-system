import test from "node:test";
import assert from "node:assert/strict";
import { stepSpring, springSettled } from "../src/liquidGlass/motion.ts";
import { opticalProfile, opticalRadius } from "../src/liquidGlass/optics.ts";

function runSpring(dt, duration, initial = 0, target = 100) {
  const s={value:initial,velocity:0,target};
  for(let elapsed=0;elapsed<duration-1e-9;){
    const next=Math.min(dt,duration-elapsed);
    stepSpring(s,next,260,28);
    elapsed+=next;
  }
  return s;
}
test("spring is frame rate invariant at 30, 60 and 144 fps",()=>{
  const values=[runSpring(1/30,0.72),runSpring(1/60,0.72),runSpring(1/144,0.72)];
  assert.ok(Math.abs(values[0].value-values[1].value)<0.0001);
  assert.ok(Math.abs(values[0].velocity-values[2].velocity)<0.0001);
});
test("spring retargeting preserves velocity and remains bounded",()=>{
  const s={value:0,velocity:0,target:220};
  for(let i=0;i<15;i++)stepSpring(s,1/60,280,27);
  const before=s.value;
  const velocity=s.velocity;
  s.target=40;
  stepSpring(s,1/60,280,27);
  assert.ok(s.value>before-40&&s.value<260);
  assert.ok(Number.isFinite(velocity)&&Number.isFinite(s.velocity));
  for(let i=0;i<100;i++)stepSpring(s,1/60,280,27);
  assert.ok(Math.abs(s.value-40)<0.005);
  assert.ok(springSettled(s,0.01,0.08));
});
test("long background frame cannot destabilize spring",()=>{
  const s={value:0,velocity:900,target:140};
  for(const dt of [2,0.5,1,0.032,0.016])stepSpring(s,dt,340,25);
  assert.ok(Number.isFinite(s.value)&&Number.isFinite(s.velocity));
  assert.ok(s.value>-100&&s.value<400);
});
test("optics have distinct but restrained mode targets",()=>{
  const brand=opticalProfile("brand",1,0,0);
  const chart=opticalProfile("chart",0,0,0);
  const reading=opticalProfile("reading",1,0,0);
  const control=opticalProfile("control",1,0,0);
  assert.ok(brand.strength<reading.strength);
  assert.ok(brand.aberration<control.aberration);
  assert.equal(chart.zoom,1.48);
  assert.ok(reading.zoom<1.1);
});
test("morph corner stays compatible with circular and rounded targets",()=>{
  assert.equal(opticalRadius("chart",118,118),59);
  assert.equal(opticalRadius("free",80,54),27);
  assert.equal(opticalRadius("brand",270,70),24);
  const prev=globalThis.getComputedStyle;
  globalThis.getComputedStyle=()=>({borderTopLeftRadius:"14px"});
  try{
    assert.equal(opticalRadius("control",150,50,{}),25);
    assert.equal(opticalRadius("reading",50,30,{}),15);
    assert.ok(opticalRadius("control",300,88,{})>=41);
    assert.equal(opticalRadius("control",40,20,{}),10);
    assert.ok(opticalRadius("reading",300,88,{})<opticalRadius("control",300,88,{}));
  }finally{
    if(prev===undefined)delete globalThis.getComputedStyle;
    else globalThis.getComputedStyle=prev;
  }
});
