import test from "node:test";
import assert from "node:assert/strict";
import {
  SNAP_SELECTOR, MAGNETIC_SELECTOR, CHART_LENS_SELECTOR, getLensBounds,
} from "../src/liquidGlass/targets.ts";

test("public snap points are scoped to intended real controls", () => {
  for (const selector of [
    ".pb-landing .pb-logo-link", ".pb-landing .pb-hero-actions a[href]",
    ".pb-landing .pb-header-actions a[href]",
    ".pb-identity-screen .pb-identity-tabs button",
    ".pb-identity-screen .pb-identity-input-wrap",
    ".pb-identity-screen .pb-identity-primary:not(:disabled)",
  ]) assert.ok(SNAP_SELECTOR.includes(selector),selector);
  assert.ok(!SNAP_SELECTOR.includes(".pb-identity-card,"));
  assert.ok(!SNAP_SELECTOR.includes(".pb-feature,"));
  assert.ok(CHART_LENS_SELECTOR.includes(".pb-landing .pb-interactive-chart"));
});

test("magnetism applies only to small controls, not text entry fields or large CTA", () => {
  assert.ok(MAGNETIC_SELECTOR.includes(".pb-identity-screen .pb-identity-tabs button"));
  assert.ok(MAGNETIC_SELECTOR.includes(".pb-landing .pb-header-actions a[href]"));
  assert.ok(!MAGNETIC_SELECTOR.includes(".pb-identity-screen .pb-identity-input-wrap"));
  assert.ok(!MAGNETIC_SELECTOR.includes(".pb-identity-screen .pb-identity-primary"));
});

test("public brand glass frame hugs the entire logo and label", () => {
  const oldWindow=globalThis.window;
  globalThis.window={innerWidth:1440,innerHeight:900};
  try {
    const target={
      matches:(selector)=>selector.includes(".pb-identity-brand"),
      getBoundingClientRect:()=>({left:75,top:25,right:305,bottom:65,width:230,height:40}),
    };
    const actual=getLensBounds(target,190,45);
    assert.equal(actual.width,242);
    assert.equal(actual.height,56);
    assert.equal(actual.centerX,190);
    assert.equal(actual.centerY,45);
    const landing={
      matches:(selector)=>selector.includes(".pb-logo-link"),
      getBoundingClientRect:()=>({left:20,top:30,right:330,bottom:69,width:310,height:39}),
    };
    assert.equal(getLensBounds(landing,170,49).width,322);
  }finally {
    if(oldWindow===undefined)delete globalThis.window;
    else globalThis.window=oldWindow;
  }
});
