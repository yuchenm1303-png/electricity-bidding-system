import assert from "node:assert/strict";
import test from "node:test";
import {browserImagePoint} from "../src/pmssBrowserCoordinates.ts";

test("school frame letterbox coordinate mapping", () => {
  const rect={left:35,top:85,width:1470,height:827};
  const scale=1470/1365;
  const top=85+(827-680*scale)/2;
  assert.deepEqual(browserImagePoint(35+900*scale,top+300*scale,rect,1365,680),{x:900,y:300});
  assert.equal(browserImagePoint(50,90,rect,1365,680),null);
});

test("invalid screenshot dimensions ignored",()=>{
  assert.equal(browserImagePoint(30,40,{left:0,top:0,width:0,height:400},1365,680),null);
});
