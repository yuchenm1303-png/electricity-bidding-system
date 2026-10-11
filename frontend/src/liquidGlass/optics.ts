/**
 * Optical values are targets, not immediate shader uniforms: shape, glass
 * strength and zoom should all arrive together when the lens changes modes.
 * Each mode shares the same GPU renderer and underlying scene texture.
 */
export type LensMode = "free" | "control" | "brand" | "reading" | "chart";
export type OpticalProfile = {strength:number;pinch:number;aberration:number;zoom:number;wobble:number};

export function opticalProfile(mode:LensMode, snap:number, press:number, release:number):OpticalProfile {
  const clampedSnap=Math.max(0,Math.min(1,snap));
  const clampedPress=Math.max(0,Math.min(1,press));
  if(mode==="chart")return {
    strength:0.78,pinch:8.1,aberration:0.055,zoom:1.48,wobble:0.025,
  };
  if(mode==="brand")return {
    strength:0.43+0.10*clampedPress,pinch:8.1,aberration:0.015,
    zoom:1.007+0.005*clampedPress,wobble:0.022+0.012*clampedPress,
  };
  if(mode==="reading")return {
    strength:0.68+0.18*clampedPress,pinch:7.7,aberration:0.045,
    zoom:1+0.015*clampedSnap+0.012*clampedPress,wobble:0.025,
  };
  return {
    strength:0.95+0.19*clampedSnap+0.62*clampedPress,
    pinch:7.7-0.35*clampedSnap-0.85*clampedPress,
    aberration:0.10+0.03*Math.max(clampedSnap,clampedPress),
    zoom:1+0.055*clampedSnap+0.025*clampedPress,
    wobble:0.12+0.05*clampedSnap+0.06*clampedPress+0.18*Math.max(0,release),
  };
}

export function opticalRadius(
  mode:LensMode,width:number,height:number,element?:HTMLElement|null,
) {
  const half=Math.max(2,Math.min(width,height)/2);
  if(mode==="free"||mode==="chart")return half;
  if(mode==="brand")return Math.min(18,half);
  if(!element)return Math.min(16,half);
  const style=getComputedStyle(element);
  const raw=style.borderTopLeftRadius;
  const parsed=Number.parseFloat(raw);
  const radius=raw.includes("%")
    ? Math.min(width,height)*(Number.isFinite(parsed)?parsed:25)/100
    : (Number.isFinite(parsed)?parsed:12);
  // A little padding makes the lens edge sit *outside* the control corner.
  return Math.max(8,Math.min(half,radius+6));
}
