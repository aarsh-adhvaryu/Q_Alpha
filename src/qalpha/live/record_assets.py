"""Styles and drawing code for the dashboard page, kept apart from the data that feeds it.

Split from :mod:`qalpha.live.record` for the reason the rest of the live layer separates
:mod:`qalpha.live.ui` from everything else: **the drawing must never be able to decide what a
number means.** This module receives a JSON blob and renders it. It performs no lookups, reads no
files, and has no opinion about which book is the bar.

No CDN and no bundler: the page is served from ``127.0.0.1`` by Python's own ``http.server`` and
has to work with the network unplugged, so the charts are hand-drawn SVG over the inlined data.
"""

from __future__ import annotations

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#17171a;--dim:#6b6b76;--line:#e3e3de;
 --up:#127a4b;--down:#b3261e;--accent:#2f5fd0;--warn:#8a6d00;--grid:#ececE6}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#141416;--card:#1c1c20;
 --ink:#ececef;--dim:#9a9aa6;--line:#2c2c33;--up:#3fbe84;--down:#ff6b5e;--accent:#7aa2ff;
 --warn:#d6b14a;--grid:#26262c}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding-block:28px;padding-left:20px;padding-right:20px}
h1{font-size:22px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:15px;margin:0 0 2px;letter-spacing:-.01em}
.sub{color:var(--dim);font-size:13px;margin:0 0 20px}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(330px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.card .note{color:var(--dim);font-size:12px;margin:2px 0 12px}
.wide{grid-column:1/-1}
.kpis{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
 margin-bottom:16px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.kpi .k{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
.kpi .v{font-size:20px;font-variant-numeric:tabular-nums;margin-top:2px}
.up{color:var(--up)}.down{color:var(--down)}.warn{color:var(--warn)}.dim{color:var(--dim)}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--dim);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.05em}
.scroll{overflow-x:auto}
.legend{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px;font-size:12px}
.legend button{display:flex;align-items:center;gap:6px;background:none;border:1px solid var(--line);
 border-radius:999px;padding:3px 10px;color:var(--ink);cursor:pointer;font:inherit}
.legend button[aria-pressed=false]{opacity:.38}
.sw{width:10px;height:10px;border-radius:3px;display:inline-block}
.chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);
 border-radius:999px;padding:3px 10px;font-size:12px;margin:0 6px 6px 0}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block}
svg{display:block;width:100%;height:auto;overflow:visible}
.tip{position:fixed;pointer-events:none;background:var(--card);border:1px solid var(--line);
 border-radius:8px;padding:6px 9px;font-size:12px;box-shadow:0 6px 20px rgba(0,0,0,.18);opacity:0;
 transition:opacity .1s;z-index:9;font-variant-numeric:tabular-nums}
.banner{border:1px solid var(--line);border-left:3px solid var(--accent);background:var(--card);
 border-radius:10px;padding:12px 14px;margin-bottom:18px;font-size:13px}
a{color:var(--accent)}
@media (max-width:520px){.wrap{padding-left:16px;padding-right:16px}h1{font-size:19px}}
"""

JS = r"""
const D = window.__QALPHA__;
const inr = n => (n<0?"-":"")+"₹"+Math.abs(Math.round(n)).toLocaleString("en-IN");
const pct = n => (n>=0?"+":"")+n.toFixed(2)+"%";
const SVG = "http://www.w3.org/2000/svg";
const el = (n,a={}) => { const e=document.createElementNS(SVG,n);
  for(const k in a) e.setAttribute(k,a[k]); return e; };
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

const tip = document.createElement("div");
tip.className = "tip";
document.body.appendChild(tip);
const show = (html,e) => { tip.innerHTML=html; tip.style.opacity=1;
  tip.style.left=Math.min(e.clientX+14, innerWidth-tip.offsetWidth-10)+"px";
  tip.style.top=(e.clientY-10)+"px"; };
const hide = () => { tip.style.opacity=0; };

function lineChart(mount, series, opts){
  opts = opts || {};
  const W=720, H=opts.height||240, P={t:14,r:14,b:26,l:66};
  const live = series.filter(s=>!s.hidden);
  const all = [].concat.apply([], live.map(s=>s.points));
  if(!all.length){ mount.innerHTML='<p class="dim">No observations yet.</p>'; return; }
  const xs=[...new Set([].concat.apply([],series.map(s=>s.points.map(p=>p.x))))].sort();
  const xi=new Map(xs.map((d,i)=>[d,i]));
  let lo=Math.min.apply(null,all.map(p=>p.y)), hi=Math.max.apply(null,all.map(p=>p.y));
  if(lo===hi){ lo-=Math.abs(lo||1)*0.01; hi+=Math.abs(hi||1)*0.01; }
  const pad=(hi-lo)*0.12; lo-=pad; hi+=pad;
  const X = i => P.l + (xs.length<2 ? (W-P.l-P.r)/2 : i*(W-P.l-P.r)/(xs.length-1));
  const Y = v => P.t + (hi-v)/(hi-lo)*(H-P.t-P.b);

  const svg=el("svg",{viewBox:"0 0 "+W+" "+H,role:"img"});
  for(let g=0;g<=4;g++){ const v=lo+(hi-lo)*g/4, y=Y(v);
    svg.appendChild(el("line",{x1:P.l,x2:W-P.r,y1:y,y2:y,stroke:css("--grid"),"stroke-width":1}));
    const t=el("text",{x:P.l-8,y:y+4,"text-anchor":"end",fill:css("--dim"),"font-size":10});
    t.textContent=inr(v); svg.appendChild(t); }
  xs.forEach((d,i)=>{ if(xs.length>1 && i%Math.ceil(xs.length/6)) return;
    const t=el("text",{x:X(i),y:H-8,"text-anchor":"middle",fill:css("--dim"),"font-size":10});
    t.textContent=d.slice(5); svg.appendChild(t); });

  live.forEach(s=>{
    const pts=s.points.slice().sort((a,b)=>a.x<b.x?-1:1);
    // FEWER THAN min_for_a_line OBSERVATIONS IS NOT A TREND. Two dots joined read as one.
    if(pts.length>=D.min_for_a_line){
      // Suspect marks are skipped by the path: the line bridges them rather than diving through.
      const d=pts.filter(p=>!p.suspect).map((p,i)=>(i?"L":"M")+X(xi.get(p.x))+","+Y(p.y)).join(" ");
      svg.appendChild(el("path",{d:d,fill:"none",stroke:s.color,"stroke-width":2,
        "stroke-linejoin":"round","stroke-linecap":"round"}));
    }
    pts.forEach(p=>{
      const c=el("circle",{cx:X(xi.get(p.x)),cy:Y(p.y),
        r:p.suspect?5:(pts.length>=D.min_for_a_line?3:5),
        fill:p.suspect?"none":s.color,stroke:p.suspect?css("--warn"):css("--card"),
        "stroke-width":p.suspect?2:1.5});
      c.style.cursor="crosshair";
      c.addEventListener("mousemove",e=>show(
        "<b>"+s.name+"</b><br>"+p.x+"<br>"+inr(p.y)+(p.extra?"<br>"+p.extra:"")+
        (p.suspect?'<br><span class="warn">suspect mark — not trusted</span>':""),e));
      c.addEventListener("mouseleave",hide);
      svg.appendChild(c);
    });
  });
  mount.innerHTML=""; mount.appendChild(svg);
}

function barChart(mount, rows){
  if(!rows.length){ mount.innerHTML='<p class="dim">Nothing to draw.</p>'; return; }
  const W=400, rowH=28, P={l:92,r:78,t:6,b:6};
  const H=P.t+P.b+rows.length*rowH;
  const max=Math.max.apply(null,rows.map(r=>Math.abs(r.value)))||1;
  const svg=el("svg",{viewBox:"0 0 "+W+" "+H,role:"img"});
  rows.forEach((r,i)=>{
    const y=P.t+i*rowH, w=Math.abs(r.value)/max*(W-P.l-P.r);
    const lab=el("text",{x:P.l-10,y:y+rowH/2+4,"text-anchor":"end",fill:css("--ink"),
      "font-size":12});
    lab.textContent=r.label; svg.appendChild(lab);
    const bar=el("rect",{x:P.l,y:y+5,width:Math.max(w,1),height:rowH-12,rx:3,
      fill:r.color||css("--accent")});
    bar.style.cursor="crosshair";
    bar.addEventListener("mousemove",e=>show("<b>"+r.label+"</b><br>"+(r.tip||inr(r.value)),e));
    bar.addEventListener("mouseleave",hide);
    svg.appendChild(bar);
    const v=el("text",{x:P.l+w+8,y:y+rowH/2+4,fill:css("--dim"),"font-size":11});
    v.textContent=r.right||inr(r.value); svg.appendChild(v);
  });
  mount.innerHTML=""; mount.appendChild(svg);
}

function donut(mount, rows){
  if(!rows.length){ mount.innerHTML='<p class="dim">Nothing held.</p>'; return; }
  const S=230, R=95, r0=58, cx=S/2, cy=S/2;
  const total=rows.reduce((a,b)=>a+b.value,0)||1;
  const svg=el("svg",{viewBox:"0 0 "+S+" "+S,role:"img"});
  let a0=-Math.PI/2;
  rows.forEach(row=>{
    const a1=a0+row.value/total*Math.PI*2;
    const big=a1-a0>Math.PI?1:0;
    const p=["M"+(cx+R*Math.cos(a0))+","+(cy+R*Math.sin(a0)),
      "A"+R+","+R+" 0 "+big+" 1 "+(cx+R*Math.cos(a1))+","+(cy+R*Math.sin(a1)),
      "L"+(cx+r0*Math.cos(a1))+","+(cy+r0*Math.sin(a1)),
      "A"+r0+","+r0+" 0 "+big+" 0 "+(cx+r0*Math.cos(a0))+","+(cy+r0*Math.sin(a0)),"Z"].join(" ");
    const seg=el("path",{d:p,fill:row.color,stroke:css("--card"),"stroke-width":1.5});
    seg.style.cursor="crosshair";
    seg.addEventListener("mousemove",e=>show("<b>"+row.label+"</b><br>"+inr(row.value)+
      " &middot; "+(row.value/total*100).toFixed(1)+"%",e));
    seg.addEventListener("mouseleave",hide);
    svg.appendChild(seg); a0=a1;
  });
  mount.innerHTML=""; mount.appendChild(svg);
}

const PALETTE=["#2f5fd0","#127a4b","#b3261e","#8a6d00","#6d4aa8","#0f7d8c","#a8541d","#5a6472"];

(function(){
  const colors={SYSTEM:css("--accent"),BASELINE_EW:css("--up"),BASELINE:css("--dim"),
    REAL:css("--warn")};
  const series=Object.keys(D.series).sort().map(name=>({
    name:name, color:colors[name]||css("--accent"), hidden:false,
    points:D.series[name].map(p=>({x:p.date,y:p.value,extra:"contributed "+inr(p.invested)}))
  }));
  const mount=document.getElementById("books-chart");
  const legend=document.getElementById("books-legend");
  const draw=()=>lineChart(mount,series);
  draw();
  legend.innerHTML="";
  series.forEach(s=>{
    const b=document.createElement("button");
    b.setAttribute("aria-pressed","true");
    b.innerHTML='<span class="sw" style="background:'+s.color+'"></span>'+s.name;
    b.onclick=()=>{ s.hidden=!s.hidden; b.setAttribute("aria-pressed",String(!s.hidden)); draw(); };
    legend.appendChild(b);
  });

  lineChart(document.getElementById("equity-chart"),[{
    name:"Model book", color:css("--accent"), hidden:false,
    points:D.equity.map(p=>({x:p.date,y:p.equity,suspect:!!p.suspect,
      extra:pct(p.return_pct)+" on contributions"}))
  }],{height:230});

  barChart(document.getElementById("holdings-chart"),
    D.holdings.filter(h=>h.value!=null).sort((a,b)=>b.value-a.value).map(h=>({
      label:h.ticker, value:h.value,
      color:(h.pnl>=0?css("--up"):css("--down")),
      right:inr(h.value),
      tip:h.quantity+" @ "+inr(h.cost)+" cost<br>mark "+inr(h.mark)+"<br>"+
        '<span class="'+(h.pnl>=0?"up":"down")+'">'+(h.pnl>=0?"+":"")+inr(h.pnl)+
        "</span> &middot; "+h.sector
    })));

  donut(document.getElementById("sector-chart"),
    D.sectors.map((s,i)=>({label:s.sector,value:s.value,color:PALETTE[i%PALETTE.length]})));
  const sl=document.getElementById("sector-legend");
  const tot=D.sectors.reduce((a,b)=>a+b.value,0)||1;
  sl.innerHTML=D.sectors.map((s,i)=>
    '<span class="chip"><span class="dot" style="background:'+PALETTE[i%PALETTE.length]+
    '"></span>'+s.sector+" "+(s.value/tot*100).toFixed(0)+"%</span>").join("");
})();
"""
