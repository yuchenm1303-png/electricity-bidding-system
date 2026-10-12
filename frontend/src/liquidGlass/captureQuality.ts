/**
 * Adaptive optical capture density for the *actual* ROI, never the full
 * window. Candid's published demo uses DPR, capture quality, image
 * complexity and frame cost; this independent implementation has a fixed
 * memory budget and a rate-limited quality governor for PowerBid charts.
 *
 * UI pixels, ROI rectangles and hit tests remain in CSS viewport coords;
 * only the backing pixels of the existing single WebGL lens change.
 */
export const QUALITY_LIMITS = {
  desktop: 2,
  mobile: 1.5,
  min: 0.75,
  maxPixels: 3_200_000, // per surface; five backing surfaces may coexist
  qualityCooldownMs: 1500,
} as const;

export function calculateCaptureScale(
  roiWidth:number,
  roiHeight:number,
  devicePixelRatio:number,
  maxTextureSize:number,
  mobile=false,
  degraded=false,
):number {
  const width=Math.max(1,roiWidth);
  const height=Math.max(1,roiHeight);
  // Supersample 1x desktop font glyphs; on high-DPI screens avoid paying
  // for pixels exceeding the available GPU texture and canvas budgets.
  const preferred=Math.max(1.65, Math.min(2,devicePixelRatio||1));
  const ceiling=mobile ? QUALITY_LIMITS.mobile : QUALITY_LIMITS.desktop;
  const budgetScale=Math.sqrt(QUALITY_LIMITS.maxPixels/(width*height));
  const textureScale=Math.max(0.25,(maxTextureSize-2)/Math.max(width,height));
  const high=Math.min(preferred,ceiling,budgetScale,textureScale);
  // Degrade only after sustained high frame cost; never drop beneath a
  // single native CSS pixel unless huge ROI would exceed the GPU limit.
  const low=Math.min(high,Math.max(1,high*.78));
  return Math.max(.01,Math.floor((degraded ? low : high)*100)/100);
}

export function createCaptureQualityGovernor(
  devicePixelRatio:number,
  maxTextureSize:number,
  mobile=false,
) {
  let scale=1;
  let pixelRatio=devicePixelRatio;
  let mobileViewport=mobile;
  let slowFrames=0;
  let fastFrames=0;
  let degraded=false;
  let lastQualityChange=Number.NEGATIVE_INFINITY;
  let frameCosts=0;
  const current=()=>scale;
  const select=(width:number,height:number,now:number,dt:number) => {
    if(Number.isFinite(dt) && dt>0) {
      // After long scheduling gaps and hidden-tab throttling, do not punish
      // the renderer for a one-off pause or a debugger breakpoint.
      if(dt>=.040 && dt<.25) {slowFrames++;fastFrames=0;}
      else if(dt<.028) {fastFrames++;slowFrames=Math.max(0,slowFrames-1);}
      if(slowFrames>=12 && !degraded && now-lastQualityChange>QUALITY_LIMITS.qualityCooldownMs) {
        degraded=true; slowFrames=0;fastFrames=0;lastQualityChange=now;
      } else if(fastFrames>=100 && degraded && now-lastQualityChange>QUALITY_LIMITS.qualityCooldownMs) {
        degraded=false; slowFrames=0;fastFrames=0;lastQualityChange=now;
      }
      frameCosts++;
    }
    const next=calculateCaptureScale(width,height,pixelRatio,maxTextureSize,mobileViewport,degraded);
    if(Math.abs(next-scale)>.015) {
      scale=next;
      return true;
    }
    return false;
  };
  return {get scale(){return current()},select,get degraded(){return degraded},
    get observedFrames(){return frameCosts},
    setDisplay(nextPixelRatio:number,nextMobile=false) {
      pixelRatio=nextPixelRatio;
      mobileViewport=nextMobile;
    }};
}
