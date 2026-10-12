import test from "node:test";
import assert from "node:assert/strict";
import {calculateCaptureScale,createCaptureQualityGovernor,QUALITY_LIMITS}
  from "../src/liquidGlass/captureQuality.ts";

test("high fidelity capture is ROI-driven, not limited by viewport width",()=>{
  const scale=calculateCaptureScale(520,520,1,4096);
  assert.equal(scale,1.65);
  // The old code used max viewport width to cap this at 1.75 or less
  // even when a tiny ROI fits easily into a GPU texture.
  assert.equal(calculateCaptureScale(520,520,2.5,4096),2);
  assert.equal(calculateCaptureScale(520,520,2,4096),2);
});

test("GPU and memory budgets cap huge snapped controls",()=>{
  const quality=calculateCaptureScale(2200,1100,2,4096);
  assert.ok(quality<=Math.sqrt(QUALITY_LIMITS.maxPixels/(2200*1100))+.01);
  assert.ok(2200*quality<=4096);
  const narrowGPU=calculateCaptureScale(1800,1200,2,2048);
  assert.ok(1800*narrowGPU<=2048);
});

test("mobile quality remains bounded and never silently exceeds budget",()=>{
  assert.ok(calculateCaptureScale(800,800,3,4096,true)<=1.5);
  assert.equal(calculateCaptureScale(400,400,1,4096,true),1.5);
  assert.ok(calculateCaptureScale(4000,4000,2,2048,true)<=.52);
});

test("governor degrades only after sustained slow frames and recovers",()=>{
  const governor=createCaptureQualityGovernor(2,4096);
  governor.select(500,500,0,0);
  assert.equal(governor.scale,2);
  for(let i=0;i<10;i++)governor.select(500,500,2000+i*45,.045);
  assert.equal(governor.degraded,false);
  for(let i=10;i<15;i++)governor.select(500,500,2000+i*45,.045);
  assert.equal(governor.degraded,true);
  assert.ok(governor.scale<2);
  assert.ok(governor.scale>=1.75,"Retina fallback must not regress below previous 1.75x capture");
  for(let i=0;i<110;i++)governor.select(500,500,4500+i*16,.016);
  assert.equal(governor.degraded,false);
  assert.equal(governor.scale,2);
});

test("single slow frame or hidden-tab scheduling gap does not drop quality",()=>{
  const governor=createCaptureQualityGovernor(2,4096);
  governor.select(480,480,0,0);
  governor.select(480,480,2500,.2);
  governor.select(480,480,12000,8);
  assert.equal(governor.scale,2);
  const standard=createCaptureQualityGovernor(1,4096);
  standard.select(500,500,0,0);
  for(let i=0;i<15;i++)standard.select(500,500,2000+i*45,.045);
  assert.ok(standard.scale>=1.65,"1x desktop supersampling should survive slow frames");
});

test("browser zoom changes pixel ratio on resize",()=>{
  const governor=createCaptureQualityGovernor(1,4096);
  governor.select(500,500,0,0);
  assert.equal(governor.scale,1.65);
  governor.setDisplay(2.25,false);
  governor.select(500,500,100,0);
  assert.equal(governor.scale,2);
});

test("density transitions avoid reallocation on stable frames",()=>{
  const governor=createCaptureQualityGovernor(2,4096);
  assert.equal(governor.select(600,600,0,0),true);
  assert.equal(governor.select(600,600,16,.016),false);
  assert.equal(governor.select(600,600,32,.016),false);
  assert.equal(governor.select(1200,1400,48,.016),true);
  assert.equal(governor.select(1200,1400,64,.016),false);
});
