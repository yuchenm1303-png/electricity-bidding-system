import test from "node:test";
import assert from "node:assert/strict";
import { VISUAL_LENS_SIZE, resolveVisualMode, lensMotion } from "../src/liquidGlass/lensModes.ts";
import { opticalProfile } from "../src/liquidGlass/optics.ts";

class Rect {
  constructor(x, y, width, height) {
    Object.assign(this, {x, y, left:x, top:y, width, height, right:x+width, bottom:y+height});
  }
}
class ElementMock {
  constructor(selectors=[], rect=new Rect(0,0,900,600)) {
    this.selectors=new Set(selectors);
    this.rect=rect;
    this.insideRoot=true;
  }
  getBoundingClientRect() { return this.rect; }
  closest(list) {
    return list.split(",").some(s=>this.selectors.has(s.trim())) ? this : null;
  }
}
globalThis.Element=ElementMock;
globalThis.DOMRect=Rect;
globalThis.getComputedStyle=element=>element.style || {display:"block",visibility:"visible"};

function scene({selectors=[],grid=null,overlays=[],insideRoot=true}={}) {
  const hit=new ElementMock(selectors);
  hit.insideRoot=insideRoot;
  globalThis.document={elementFromPoint:()=>hit};
  const root={
    contains:el=>el.insideRoot,
    querySelector:selector=>selector===".pb-landing .pb-field-canvas" ? grid : null,
    querySelectorAll:()=>overlays,
  };
  return root;
}

test("published four-mode geometry has predictable dimensions",()=>{
  assert.deepEqual(Object.keys(VISUAL_LENS_SIZE),["free","chart","hero","grid"]);
  assert.deepEqual(VISUAL_LENS_SIZE.free,{width:80,height:54});
  assert.deepEqual(VISUAL_LENS_SIZE.chart,{width:156,height:156});
  assert.deepEqual(VISUAL_LENS_SIZE.hero,{width:128,height:128});
  assert.deepEqual(VISUAL_LENS_SIZE.grid,{width:164,height:164});
});

test("default, non-hover, and foreign DOM targets do not switch the lens",()=>{
  const root=scene();
  assert.equal(resolveVisualMode(root,300,300,false),"free");
  assert.equal(resolveVisualMode(root,300,300,true),"free");
  assert.equal(resolveVisualMode(scene({selectors:[".pb-hero"],insideRoot:false}),300,300,true),"free");
});

test("dashboard gauges, lines and PMSS charts use the readable round lens",()=>{
  for(const chart of [".ta-gauge-wrap",".ta-bars",".recharts-wrapper",".pmss-chart",".pb-interactive-chart"]) {
    assert.equal(resolveVisualMode(scene({selectors:[chart]}),350,320,true),"chart",chart);
  }
});

test("interactive controls take precedence even inside charts and Hero",()=>{
  assert.equal(resolveVisualMode(scene({selectors:[".ta-bars","button"]}),350,320,true),"free");
  assert.equal(resolveVisualMode(scene({selectors:[".pb-hero","a[href]"]}),350,320,true),"free");
  assert.equal(resolveVisualMode(scene({selectors:[".pmss-chart","[role='slider']"]}),350,320,true),"free");
  assert.equal(resolveVisualMode(scene({selectors:[".pb-hero-copy",".pb-hero"]}),350,320,true),"free");
});

test("data-card icon surfaces provide visible hero morph without touching numbers",()=>{
  for(const indicator of [".ta-stat-icon",".ta-card-icon",".pb-risk-halo"]) {
    assert.equal(resolveVisualMode(scene({selectors:[indicator]}),350,320,true),"hero",indicator);
  }
  assert.equal(resolveVisualMode(scene({selectors:[".ta-stat-bottom"]}),350,320,true),"free");
  assert.equal(resolveVisualMode(scene({selectors:[".ta-card-icon","button"]}),350,320,true),"free");
});

test("network and decorative Hero content use expressive refraction",()=>{
  assert.equal(resolveVisualMode(scene({selectors:[".pb-flow-network"]}),350,320,true),"hero");
  assert.equal(resolveVisualMode(scene({selectors:[".pb-hero"]}),350,320,true),"hero");
});

test("editorial grid lens requires safe canvas region with no floating HUD",()=>{
  const grid=new ElementMock([],new Rect(200,150,900,650));
  const root=scene({selectors:[".pb-hero"],grid});
  assert.equal(resolveVisualMode(root,600,450,true),"grid");
  // Pointer is over canvas, but a large lens would spill beyond its border.
  assert.equal(resolveVisualMode(root,225,450,true),"hero");
  assert.equal(resolveVisualMode(root,600,155,true),"hero");
  const hud=new ElementMock([".pb-hero-hud"],new Rect(570,420,160,95));
  assert.equal(resolveVisualMode(scene({selectors:[".pb-hero"],grid,overlays:[hud]}),600,450,true),"hero");
});

test("164px lens fits the resized 265px homepage grid while avoiding labels",()=>{
  const grid = new ElementMock([],new Rect(250,500,820,265));
  const root = scene({grid});
  assert.equal(resolveVisualMode(root,650,632,true),"grid");
  assert.equal(resolveVisualMode(root,650,505,true),"free");
  const detail = new ElementMock([".pb-constellation-detail"],new Rect(620,612,180,35));
  assert.equal(resolveVisualMode(scene({grid,overlays:[detail]}),650,632,true),"free");
});

test("optics preserve original free surface and readable chart magnification",()=>{
  assert.equal(opticalProfile("free",0,0,0).reflection,1);
  assert.equal(opticalProfile("brand",0,0,0).reflection,1);
  assert.equal(opticalProfile("reading",0,0,0).reflection,1);
  assert.equal(opticalProfile("chart",0,0,0).zoom,1.48);
  assert.equal(opticalProfile("hero",0,0,0).zoom,1);
  assert.equal(opticalProfile("grid",0,0,0).zoom,1.6);
  assert.ok(opticalProfile("hero",0,0,0).strength>opticalProfile("chart",0,0,0).strength);
});

test("spring motion distinguishes large, Hero and chart states",()=>{
  assert.ok(lensMotion("grid",false).stiffness<lensMotion("chart",false).stiffness);
  assert.ok(lensMotion("hero",false).damping<lensMotion("free",false).damping);
  assert.ok(lensMotion("free",true).stiffness>lensMotion("grid",false).stiffness);
});
