import {
  BASE_WIDTH,BASE_HEIGHT,FREE_ROI_SIZE,FREE_ROI_PADDING,ROI_DEADZONE,
  SNAP_ROI_PADDING,getLensBounds
} from "./targets";

/** One viewport CSS-pixel coordinate system for sampling and lens geometry. */
export function createRoiManager(
  resizeSurfaces:(width:number,height:number)=>boolean,
  onDirty:()=>void,
  onTextureReset:()=>void,
) {
  let roiWidth=FREE_ROI_SIZE,roiHeight=FREE_ROI_SIZE;
  let roiLeft=Number.NaN,roiTop=Number.NaN;
  let roiLockedTarget:HTMLElement|null=null;
  let snappedRoiWidth=FREE_ROI_SIZE,snappedRoiHeight=FREE_ROI_SIZE;
  const state={
    get left(){return roiLeft},get top(){return roiTop},
    get width(){return roiWidth},get height(){return roiHeight},
  };
  const clearLock=()=>{roiLockedTarget=null;};
  const reset=()=>{
    roiLeft=Number.NaN;roiTop=Number.NaN;roiLockedTarget=null;
    onDirty();
  };
  const setSnapDimensions=(lensWidth:number,lensHeight:number)=>{
    snappedRoiWidth=Math.min(window.innerWidth,
      Math.max(FREE_ROI_SIZE,Math.ceil((lensWidth+SNAP_ROI_PADDING*2)/16)*16));
    snappedRoiHeight=Math.min(window.innerHeight,
      Math.max(FREE_ROI_SIZE,Math.ceil((lensHeight+SNAP_ROI_PADDING*2)/16)*16));
  };
    const update = (lensX:number,lensY:number,lensWidth:number,lensHeight:number,
      activeTarget:HTMLElement|null,snapValue:number) => {
      const target = activeTarget?.isConnected ? activeTarget : null;
      // Hold the snapped ROI at its final size for the entire morph and release.
      // Resizing the backing canvas while width/height springs are moving invalidates
      // the WebGL texture and was the source of the visible flashing.
      const holdSnappedRoi =
        Boolean(target) ||
        snapValue > 0.025 ||
        lensWidth > BASE_WIDTH + 4 ||
        lensHeight > BASE_HEIGHT + 4;
      const desiredWidth = holdSnappedRoi ? snappedRoiWidth : FREE_ROI_SIZE;
      const desiredHeight = holdSnappedRoi ? snappedRoiHeight : FREE_ROI_SIZE;

      if (!holdSnappedRoi) {
        snappedRoiWidth = FREE_ROI_SIZE;
        snappedRoiHeight = FREE_ROI_SIZE;
      }

      const boundedWidth = Math.max(1, Math.min(window.innerWidth, desiredWidth));
      const boundedHeight = Math.max(1, Math.min(window.innerHeight, desiredHeight));
      if (boundedWidth !== roiWidth || boundedHeight !== roiHeight) {
        roiWidth = boundedWidth;
        roiHeight = boundedHeight;
        if (resizeSurfaces(roiWidth, roiHeight)) onTextureReset();
        roiLeft = Number.NaN;
        roiTop = Number.NaN;
        roiLockedTarget = null;
        onDirty();
      }

      const maxLeft = Math.max(0, window.innerWidth - roiWidth);
      const maxTop = Math.max(0, window.innerHeight - roiHeight);

      if (target) {
        // Geometry, hit testing and the DOM raster use viewport coordinates.
        // getLensBounds already includes CSS translate via getBoundingClientRect;
        // subtracting magnetic appliedX/Y again shifted the ROI away from the
        // actual button while the lens kept drawing in its visual position.
        const bounds = getLensBounds(target, lensX, lensY);
        const nextLeft = Math.round(Math.max(0, Math.min(maxLeft, bounds.centerX - roiWidth / 2)));
        const nextTop = Math.round(Math.max(0, Math.min(maxTop, bounds.centerY - roiHeight / 2)));
        // Small hysteresis absorbs half-pixel CSS translation rounding, but
        // never permits an old 28px offset between capture and visible lens.
        const recenterThreshold = 2;
        if (roiLockedTarget !== target || !Number.isFinite(roiLeft) || !Number.isFinite(roiTop) ||
            Math.abs(nextLeft - roiLeft) > recenterThreshold ||
            Math.abs(nextTop - roiTop) > recenterThreshold) {
          roiLeft = nextLeft;
          roiTop = nextTop;
          roiLockedTarget = target;
          onDirty();
        }
        return;
      }

      roiLockedTarget = null;
      if (!Number.isFinite(roiLeft) || !Number.isFinite(roiTop)) {
        roiLeft = Math.round(Math.max(0, Math.min(maxLeft, lensX - roiWidth / 2)));
        roiTop = Math.round(Math.max(0, Math.min(maxTop, lensY - roiHeight / 2)));
        onDirty();
        return;
      }

      const halfW = lensWidth / 2;
      const halfH = lensHeight / 2;
      const marginX = Math.max(8, Math.min(FREE_ROI_PADDING, (roiWidth - lensWidth) / 2 - 8));
      const marginY = Math.max(8, Math.min(FREE_ROI_PADDING, (roiHeight - lensHeight) / 2 - 8));
      const minX = roiLeft + halfW + marginX;
      const maxX = roiLeft + roiWidth - halfW - marginX;
      const minY = roiTop + halfH + marginY;
      const maxY = roiTop + roiHeight - halfH - marginY;

      let nextLeft = roiLeft;
      let nextTop = roiTop;
      if (lensX < minX) nextLeft -= Math.max(ROI_DEADZONE, minX - lensX);
      else if (lensX > maxX) nextLeft += Math.max(ROI_DEADZONE, lensX - maxX);
      if (lensY < minY) nextTop -= Math.max(ROI_DEADZONE, minY - lensY);
      else if (lensY > maxY) nextTop += Math.max(ROI_DEADZONE, lensY - maxY);

      nextLeft = Math.round(Math.max(0, Math.min(maxLeft, nextLeft)));
      nextTop = Math.round(Math.max(0, Math.min(maxTop, nextTop)));
      if (nextLeft !== roiLeft || nextTop !== roiTop) {
        roiLeft = nextLeft;
        roiTop = nextTop;
        onDirty();
      }
    };

  return {state,update,clearLock,reset,setSnapDimensions};
}
