/**
 * Optical values are targets, not immediate shader uniforms: shape, glass
 * strength and zoom should all arrive together when the lens changes modes.
 * Each mode shares the same GPU renderer and underlying scene texture.
 */
export type LensMode = "free" | "control" | "brand" | "reading" | "chart" | "hero" | "grid";
export type OpticalProfile = {strength:number;pinch:number;aberration:number;zoom:number;wobble:number;reflection:number};

export function opticalProfile(mode:LensMode, snap:number, press:number, release:number):OpticalProfile {
  const clampedSnap=Math.max(0,Math.min(1,snap));
  const clampedPress=Math.max(0,Math.min(1,press));
  if(mode==="chart")return {
    strength:1.4,pinch:7.7,aberration:0.12,zoom:1.48,wobble:0.025,reflection:0.8,
  };
  if(mode==="hero")return {
    // Framer-style expressive refraction, only on decorative backgrounds.
    strength:3.5,pinch:5.5,aberration:0.18,zoom:1,wobble:0.12,reflection:0,
  };
  if(mode==="grid")return {
    strength:1.7,pinch:7.7,aberration:0.12,zoom:1.6,wobble:0.06,reflection:0.8,
  };
  if(mode==="brand")return {
    strength:0.43+0.10*clampedPress,pinch:8.1,aberration:0.015,
    zoom:1.007+0.005*clampedPress,wobble:0.022+0.012*clampedPress,reflection:1,
  };
  if(mode==="reading")return {
    strength:0.68+0.18*clampedPress,pinch:7.7,aberration:0.045,
    zoom:1+0.015*clampedSnap+0.012*clampedPress,wobble:0.025,reflection:1,
  };
  return {
    strength:0.95+0.19*clampedSnap+0.62*clampedPress,
    pinch:7.7-0.35*clampedSnap-0.85*clampedPress,
    aberration:0.10+0.03*Math.max(clampedSnap,clampedPress),
    zoom:1+0.055*clampedSnap+0.025*clampedPress,
    wobble:0.12+0.05*clampedSnap+0.06*clampedPress+0.18*Math.max(0,release),
    reflection:1,
  };
}

export function opticalRadius(
  mode:LensMode,width:number,height:number,element?:HTMLElement|null,
) {
  const half=Math.max(2,Math.min(width,height)/2);
  if(mode==="free"||mode==="chart"||mode==="hero"||mode==="grid")return half;
  // The full Smirel wordmark remains a softly rounded, independent surface.
  if(mode==="brand")return Math.min(24,half);
  if(!element)return Math.min(half,Math.max(12,half*0.92));
  const style=getComputedStyle(element);
  const raw=style.borderTopLeftRadius||"0";
  const parsed=Number.parseFloat(raw);
  const radius=raw.includes("%")
    ? Math.min(width,height)*(Number.isFinite(parsed)?parsed:25)/100
    : (Number.isFinite(parsed)?parsed:12);
  // Glass extends beyond the CSS box. A control's original corner radius
  // is therefore too square for the larger glass geometry. A near-pill
  // radius respects its *lens* height, with no overshoot on compact targets.
  if(mode==="control")return Math.min(half,Math.max(radius+12,half*0.94));
  // Keep typing areas slightly squarer so their frame stays easy to read.
  return Math.min(half,Math.max(radius+9,half*0.72));
}
