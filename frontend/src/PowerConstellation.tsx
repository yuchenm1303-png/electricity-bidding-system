import { useEffect, useRef, useState } from "react";
import "./constellation.css";

// An intentionally fictional demonstration network. The spatial links,
// node categories and animated signals do not represent PMSS live measurements.
type NodeKind = "发电节点" | "负荷节点" | "联络枢纽";
type GridNode = { id: string; kind: NodeKind; x: number; y: number; z: number };
const NODES: GridNode[] = [
  {id:"G01",kind:"发电节点",x:-1.63,y:-.10,z:-.35},
  {id:"T01",kind:"联络枢纽",x:-1.31,y:-.48,z:.42},
  {id:"L01",kind:"负荷节点",x:-1.32,y:.42,z:-.06},
  {id:"T02",kind:"联络枢纽",x:-.96,y:-.09,z:.05},
  {id:"L02",kind:"负荷节点",x:-.98,y:.72,z:.46},
  {id:"G02",kind:"发电节点",x:-.73,y:-.73,z:-.52},
  {id:"T03",kind:"联络枢纽",x:-.56,y:.28,z:-.54},
  {id:"L03",kind:"负荷节点",x:-.43,y:-.19,z:.67},
  {id:"T04",kind:"联络枢纽",x:-.21,y:-.52,z:.12},
  {id:"G03",kind:"发电节点",x:-.17,y:.71,z:.19},
  {id:"T05",kind:"联络枢纽",x:.08,y:.06,z:-.36},
  {id:"L04",kind:"负荷节点",x:.10,y:.46,z:.68},
  {id:"T06",kind:"联络枢纽",x:.43,y:-.37,z:-.60},
  {id:"L05",kind:"负荷节点",x:.55,y:.81,z:-.28},
  {id:"G04",kind:"发电节点",x:.67,y:.21,z:.32},
  {id:"T07",kind:"联络枢纽",x:.85,y:-.04,z:-.19},
  {id:"L06",kind:"负荷节点",x:.91,y:-.70,z:.61},
  {id:"T08",kind:"联络枢纽",x:1.20,y:.40,z:-.32},
  {id:"G05",kind:"发电节点",x:1.32,y:-.40,z:-.67},
  {id:"L07",kind:"负荷节点",x:1.59,y:.04,z:.40},
  {id:"T09",kind:"联络枢纽",x:1.62,y:.66,z:-.16},
  {id:"L08",kind:"负荷节点",x:.05,y:-.87,z:-.17},
];
const LINKS: [number,number][] = [
  [0,1],[0,3],[1,3],[1,5],[2,3],[2,4],[3,6],[3,7],[4,6],[5,8],
  [6,7],[6,9],[6,10],[7,8],[7,10],[8,10],[8,21],[9,10],[9,11],
  [10,11],[10,12],[10,14],[11,13],[12,14],[12,15],[12,21],
  [13,14],[13,17],[14,15],[14,17],[15,16],[15,17],[15,18],
  [16,18],[17,19],[17,20],[18,19],[19,20],
];
const NODE_TITLE: Record<NodeKind,string> = {
  "发电节点": "GENERATION", "负荷节点": "LOAD", "联络枢纽": "SUBSTATION",
};
type ScreenNode = { x: number; y: number; depth: number };
const linkCount = (index: number) => LINKS.filter(([a,b]) => a === index || b === index).length;

export default function PowerConstellation() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [focused, setFocused] = useState(10);
  const [hovered, setHovered] = useState<number | null>(null);
  const activeIndex = hovered ?? focused;
  const active = NODES[activeIndex];

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha:true });
    if (!ctx) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const coarse = window.matchMedia("(pointer: coarse)");
    let w = 0, h = 0, raf = 0, frame = 0, lastPaint = 0, shown = true;
    let yaw = -.51, pitch = -.22, angularVelocity = .00055;
    let isDragging = false, dragDistance = 0, lastX = 0, lastY = 0;
    let selected = 10;
    let highlight = selected;
    let mouseX = -999, mouseY = -999;
    let projected: ScreenNode[] = [];

    const position = (n: GridNode, angle: number, elevation: number, scale: number): ScreenNode => {
      const x = n.x * .80 * Math.cos(angle) - n.z * 1.26 * Math.sin(angle);
      const z = n.x * .80 * Math.sin(angle) + n.z * 1.26 * Math.cos(angle);
      const y = n.y * 1.19 * Math.cos(elevation) - z * Math.sin(elevation);
      const depth = n.y * 1.19 * Math.sin(elevation) + z * Math.cos(elevation);
      const perspective = 4.3 / (4.3 + depth * .58);
      return { x:w*.49 + x*scale*perspective, y:h*.49 + y*scale*perspective, depth };
    };
    function paint() {
      if (!ctx || !w || !h) return;
      ctx.clearRect(0,0,w,h);
      const scale = Math.min(w * .263, h * .355);
      const angle = yaw + (reduced.matches ? 0 : Math.sin(frame * .003) * .018);
      const elevation = pitch;
      projected = NODES.map(n => position(n,angle,elevation,scale));
      const dark = document.documentElement.dataset.theme === "dark";
      const aura = ctx.createRadialGradient(w*.50,h*.50, 0, w*.50,h*.50,w*.46);
      aura.addColorStop(0,dark?"rgba(78,105,232,.19)":"rgba(137,154,255,.095)");
      aura.addColorStop(.58,dark?"rgba(84,118,221,.065)":"rgba(173,190,255,.038)");
      aura.addColorStop(1,"rgba(201,216,255,0)");
      ctx.fillStyle = aura;
      ctx.fillRect(0,0,w,h);

      const ordered = LINKS.map(([a,b],i) => ({a,b,i,depth:(projected[a].depth+projected[b].depth)/2}))
        .sort((a,b) => b.depth-a.depth);
      ordered.forEach(({a,b,depth}) => {
        const p=projected[a],q=projected[b];
        const adjacent = a===highlight || b===highlight;
        const alpha=Math.max(dark ? .30 : .16,Math.min(dark ? .79 : .61,(dark ? .52 : .31)-depth*.13+(adjacent?.16:.19)));
        const line=ctx.createLinearGradient(p.x,p.y,q.x,q.y);
        line.addColorStop(0,(dark?"rgba(104,151,252,":"rgba(101,126,218,")+(alpha*.65).toFixed(3)+")");
        line.addColorStop(.5,(dark?"rgba(130,163,254,":"rgba(95,127,226,")+(alpha).toFixed(3)+")");
        line.addColorStop(1,(dark?"rgba(140,150,249,":"rgba(141,151,225,")+(alpha*.7).toFixed(3)+")");
        ctx.beginPath();
        ctx.moveTo(p.x,p.y);
        ctx.lineTo(q.x,q.y);
        ctx.lineWidth=adjacent?1.55:.95;
        ctx.strokeStyle=line;
        ctx.stroke();
      });

      // Small moving glints suggest direction, but do not claim actual MW flows.
      if (!reduced.matches) LINKS.forEach(([a,b],i) => {
        const adjacent = a===highlight || b===highlight;
        if (i % 2 === 1 && !adjacent) return;
        const t=(frame*.005 + i*.119)%1;
        const p=projected[a],q=projected[b];
        const x=p.x+(q.x-p.x)*t;
        const y=p.y+(q.y-p.y)*t;
        ctx.beginPath();
        ctx.arc(x,y,adjacent?1.9:1.2,0,Math.PI*2);
        ctx.fillStyle=adjacent?(dark?"rgba(147,184,255,.95)":"rgba(73,94,235,.74)"):(dark?"rgba(130,172,253,.65)":"rgba(90,118,238,.40)");
        ctx.fill();
      });

      const orderedNodes = projected.map((p,i)=>({p,i})).sort((a,b)=>b.p.depth-a.p.depth);
      orderedNodes.forEach(({p,i}) => {
        const isActive = i===highlight;
        const radius = NODES[i].kind==="联络枢纽" ? 3.4 : 2.7;
        const visibility = Math.max(.55, Math.min(.95,.76-p.depth*.14));
        if (isActive) {
          ctx.beginPath();ctx.arc(p.x,p.y,21,0,Math.PI*2);
          ctx.fillStyle=dark?"rgba(135,164,255,.12)":"rgba(110,125,240,.055)";ctx.fill();
          ctx.beginPath();ctx.arc(p.x,p.y,12,0,Math.PI*2);
          ctx.strokeStyle=dark?"rgba(145,172,255,.54)":"rgba(95,109,230,.30)";ctx.lineWidth=1;ctx.stroke();
        }
        ctx.beginPath();
        ctx.arc(p.x,p.y,radius + 3.5,0,Math.PI*2);
        ctx.fillStyle=dark?"rgba(125,155,255,.20)":"rgba(95,110,226,.09)";
        ctx.fill();
        ctx.beginPath();ctx.arc(p.x,p.y,radius,0,Math.PI*2);
        ctx.fillStyle = NODES[i].kind==="发电节点" ? (dark?"rgba(127,146,254,":"rgba(77,93,221,")+visibility+")"
          : NODES[i].kind==="负荷节点" ? (dark?"rgba(180,193,255,":"rgba(150,160,215,")+visibility+")"
          : (dark?"rgba(105,192,246,":"rgba(94,137,230,")+visibility+")";
        ctx.fill();
        ctx.beginPath();ctx.arc(p.x,p.y,1.1,0,Math.PI*2);
        ctx.fillStyle="#fff";ctx.fill();
        if ((isActive || i===0 || i===14 || i===19) && p.x > 38 && p.x < w - 55) {
          ctx.font="600 10px Inter,system-ui,sans-serif";
          ctx.letterSpacing="1px";
          ctx.fillStyle=dark?(isActive?"rgba(203,216,255,.95)":"rgba(162,184,235,.83)"):(isActive?"rgba(67,82,156,.86)":"rgba(117,131,174,.64)");
          ctx.fillText(NODES[i].id,p.x+11,p.y-12);
        }
      });
    }

    function resize() {
      const rect=canvas!.getBoundingClientRect();
      const ratio=Math.min(window.devicePixelRatio||1,2);
      w=rect.width;h=rect.height;
      canvas!.width=Math.round(w*ratio);
      canvas!.height=Math.round(h*ratio);
      ctx!.setTransform(ratio,0,0,ratio,0,0);
      paint();
    }
    function nearest(x:number,y:number) {
      let index:null|number=null, distance=17;
      projected.forEach((p,i)=>{
        const d=Math.hypot(p.x-x,p.y-y);
        if(d<distance) {distance=d;index=i;}
      });
      return index;
    }
    function move(e:PointerEvent) {
      const rect=canvas!.getBoundingClientRect();
      mouseX=e.clientX-rect.left;mouseY=e.clientY-rect.top;
      if (isDragging) {
        const dx=e.clientX-lastX,dy=e.clientY-lastY;
        dragDistance+=Math.hypot(dx,dy);
        yaw+=dx*.005;pitch=Math.max(-.68,Math.min(.68,pitch+dy*.004));
        lastX=e.clientX;lastY=e.clientY;
        canvas!.style.cursor="grabbing";
        paint();
      } else {
        const index=nearest(mouseX,mouseY);
        highlight=index??selected;
        setHovered(index);
        canvas!.style.cursor=index!==null?"pointer":"grab";
      }
    }
    function down(e:PointerEvent) {
      if (e.button!==0) return;
      isDragging=true;dragDistance=0;lastX=e.clientX;lastY=e.clientY;
      canvas!.setPointerCapture(e.pointerId);
    }
    function up(e:PointerEvent) {
      if(!isDragging) return;
      isDragging=false;canvas!.style.cursor="grab";
      if (canvas!.hasPointerCapture(e.pointerId)) canvas!.releasePointerCapture(e.pointerId);
      if(dragDistance<6) {
        const index=nearest(mouseX,mouseY);
        if(index!==null){selected=index;highlight=index;setFocused(index);setHovered(null);}
      } else {
        highlight=selected;setHovered(null);
      }
      paint();
    }
    function leave() {if(!isDragging){highlight=selected;setHovered(null);paint();}}
    function keys(e:KeyboardEvent) {
      if(e.key==="ArrowLeft"){yaw-=.13;e.preventDefault();}
      else if(e.key==="ArrowRight"){yaw+=.13;e.preventDefault();}
      else if(e.key==="ArrowUp"){pitch=Math.max(-.68,pitch-.1);e.preventDefault();}
      else if(e.key==="ArrowDown"){pitch=Math.min(.68,pitch+.1);e.preventDefault();}
      else if(e.key==="Enter"||e.key===" "){
        selected=(selected+1)%NODES.length;highlight=selected;setHovered(null);setFocused(selected);e.preventDefault();
      }else return;
      paint();
    }
    function tick(now:number) {
      if(shown && !reduced.matches && now-lastPaint > (coarse.matches ? 40 : 30)) {
        frame++;
        if(!isDragging) yaw += angularVelocity;
        paint();
        lastPaint=now;
      }
      raf=requestAnimationFrame(tick);
    }
    const observer=new IntersectionObserver(items=>{shown=items[0]?.isIntersecting??false;},{threshold:.01});
    observer.observe(canvas);
    const refresh=()=>paint();
    const themeObserver = new MutationObserver(refresh);
    themeObserver.observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
    reduced.addEventListener("change",refresh);
    canvas.addEventListener("pointermove",move);
    canvas.addEventListener("pointerdown",down);
    canvas.addEventListener("pointerup",up);
    canvas.addEventListener("pointercancel",up);
    canvas.addEventListener("pointerleave",leave);
    canvas.addEventListener("keydown",keys);
    window.addEventListener("resize",resize);
    resize();
    raf=requestAnimationFrame(tick);
    return ()=>{
      cancelAnimationFrame(raf);observer.disconnect();themeObserver.disconnect();
      reduced.removeEventListener("change",refresh);
      canvas.removeEventListener("pointermove",move);
      canvas.removeEventListener("pointerdown",down);
      canvas.removeEventListener("pointerup",up);
      canvas.removeEventListener("pointercancel",up);
      canvas.removeEventListener("pointerleave",leave);
      canvas.removeEventListener("keydown",keys);
      window.removeEventListener("resize",resize);
    };
  },[]);

  return <div className="pb-constellation">
    <div className="pb-constellation-header" aria-hidden="true">
      <span className="pb-constellation-kicker"><span className="pb-constellation-status"/> INTERACTIVE GRID / 3D</span>
      <span className="pb-constellation-meta">DEMO TOPOLOGY</span>
    </div>
    <canvas
      ref={canvasRef}
      className="pb-field-canvas"
      tabIndex={0}
      role="img"
      aria-label="交互式三维电网星座：拖动旋转，点击发电、负荷与联络节点查看说明。方向键旋转，回车切换节点。"
    />
    <div className="pb-constellation-detail" aria-live="polite">
      <span className="pb-constellation-detail-index">NODE / {active.id}</span>
      <strong>{active.kind}</strong>
      <span className="pb-constellation-detail-sub">{NODE_TITLE[active.kind]} · {linkCount(activeIndex)} 条连接</span>
    </div>
    <div className="pb-constellation-hint" aria-hidden="true">
      <span className="pb-constellation-line"/>
      拖动旋转 · 点击节点
    </div>
  </div>;


}
