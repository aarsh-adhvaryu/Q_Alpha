"""Styles and drawing code for the dashboard page, kept apart from the data that feeds it.

Split from :mod:`qalpha.live.record` because **the drawing must never be able to decide what a
number means.** This module receives a JSON blob and renders it. It performs no lookups, reads no
files, and has no opinion about which book is the bar.

No CDN and no bundler: the page is served from ``127.0.0.1`` by Python's own ``http.server`` and
has to work with the network unplugged, so the charts are hand-drawn SVG over the inlined data.

The layout follows a brokerage terminal — a market strip and tabs across the top, the holdings down
the left, a statement's figures and table in the middle — in the app's own colours and mark.
"""

from __future__ import annotations

CSS = """
:root{--bg:#131313;--panel:#1b1b1b;--card:#1b1b1b;--raise:#242424;--ink:#e3e3e3;--dim:#8d8d8d;
 --line:#2b2b2b;--up:#4caf7a;--down:#e5534b;--accent:#4a8df0;--brand:#ff6a3d;--warn:#d6a73a;
 --grid:#262626}
@media (prefers-color-scheme:light){:root:not([data-theme=dark]){--bg:#f5f5f4;--panel:#fff;
 --card:#fff;--raise:#f3f3f1;--ink:#1f1f1f;--dim:#6d6d6d;--line:#e6e6e3;--up:#1f8a4c;
 --down:#c7372f;--accent:#2f6fd6;--brand:#e8552a;--warn:#8a6d00;--grid:#eeeeea}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent);text-decoration:none}
.top{position:sticky;top:0;z-index:5;display:grid;
 grid-template-columns:minmax(240px,420px) auto 1fr auto;align-items:center;gap:18px;
 padding:0 24px;height:56px;background:var(--panel);border-bottom:1px solid var(--line)}
.strip{font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
 font-variant-numeric:tabular-nums}
.brand{display:flex;align-items:center;gap:9px;font-weight:700;letter-spacing:-.01em}
.mark{width:13px;height:13px;background:var(--brand);transform:rotate(45deg);border-radius:3px}
.tabs{display:flex;gap:2px;justify-content:flex-end;overflow-x:auto}
.tabs a{color:var(--ink);padding:17px 12px;border-bottom:2px solid transparent;white-space:nowrap}
.tabs a:hover{color:var(--brand)}
.tabs a[aria-current=page]{color:var(--brand);border-bottom-color:var(--brand)}
.who{display:flex;gap:10px;align-items:center;font-size:12px;white-space:nowrap}
.state{border:1px solid var(--line);border-radius:999px;padding:2px 10px;color:var(--dim)}
.state.on{color:var(--up);border-color:var(--up)}
.shell{display:grid;grid-template-columns:minmax(300px,430px) 1fr;min-height:calc(100vh - 56px)}
.side{border-right:1px solid var(--line);background:var(--panel)}
.side-h{padding:14px 18px;color:var(--dim);font-size:12px;border-bottom:1px solid var(--line)}
.wl{display:grid;grid-template-columns:1fr auto 62px 66px 84px;gap:8px;align-items:center;
 padding:12px 18px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums;
 font-size:13.5px}
.wl:hover{background:var(--raise)}
.wl span{text-align:right}.wl .nm{text-align:left;font-weight:500}
.wl .qty{color:var(--dim);font-size:12px}
.pad{padding:12px 18px;font-size:12px}
.main{padding:22px 28px 60px;min-width:0}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.sub{color:var(--dim);font-size:12.5px;margin:0 0 14px}
.tab{display:none}.tab.show{display:block}
h2{font-size:17px;font-weight:500;margin:0 0 4px}
h3{font-size:15px;font-weight:500;margin:0 0 8px}
h3.sec{margin:22px 0 10px}
.panel,.card{background:var(--panel);border:1px solid var(--line);border-radius:6px;
 padding:18px 20px;margin-bottom:16px}
.note,.card .note{color:var(--dim);font-size:12px;margin:2px 0 12px}
.duo{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));
 margin-bottom:16px}
.duo>.panel{margin-bottom:0}
.big{font-size:40px;font-weight:300;letter-spacing:-.02em;line-height:1.15;
 font-variant-numeric:tabular-nums;margin:4px 0 2px}
.big small{font-size:13px;margin-left:6px;font-weight:400}
.kv{display:flex;justify-content:space-between;border-top:1px solid var(--line);padding:9px 0 0;
 margin-top:10px;font-size:13px;font-variant-numeric:tabular-nums}
.kv span{color:var(--dim)}.kv b{font-weight:500}
.figs{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
 background:var(--panel);border:1px solid var(--line);border-radius:6px;margin-bottom:16px}
.fig{padding:14px 18px;border-right:1px solid var(--line)}
.fig .k{color:var(--dim);font-size:12.5px}
.fig .v{font-size:21px;font-variant-numeric:tabular-nums;margin-top:3px;display:flex;gap:8px;
 align-items:center;flex-wrap:wrap}
.pill{font-size:11px;padding:1px 6px;border-radius:3px;background:var(--raise)}
.tiles{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
 margin-bottom:16px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:12px 14px;
 font-variant-numeric:tabular-nums}
.tile .k{font-size:12px;color:var(--dim)}.tile .v{font-size:20px}.small{font-size:11.5px}
.dec{display:flex;gap:10px;align-items:center;padding:7px 0;border-bottom:1px solid var(--line)}
.tag{font-size:11px;padding:1px 7px;border-radius:3px;background:var(--raise);color:var(--accent)}
.alloc{display:flex;height:56px;border-radius:3px;overflow:hidden;background:var(--raise)}
.alloc div{height:100%;min-width:2px}
.alloc-foot{display:flex;justify-content:space-between;align-items:center;margin-top:10px;
 flex-wrap:wrap;gap:8px}
.alloc-total{font-size:18px;font-variant-numeric:tabular-nums}
.alloc-mode{display:flex;gap:14px;font-size:13px;color:var(--dim)}
.alloc-mode input{accent-color:var(--accent)}
.up{color:var(--up)}.down{color:var(--down)}.warn{color:var(--warn)}.dim{color:var(--dim)}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:11px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--dim);font-weight:400;font-size:12.5px}
tr.total td{font-weight:600;border-bottom:none}
.scroll{overflow-x:auto;margin-bottom:14px}
.legend{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px;font-size:12px}
.legend button{display:flex;align-items:center;gap:6px;background:none;border:1px solid var(--line);
 border-radius:999px;padding:3px 10px;color:var(--ink);cursor:pointer;font:inherit}
.legend button[aria-pressed=false]{opacity:.38}
.sw{width:10px;height:10px;border-radius:3px;display:inline-block}
.chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);
 border-radius:999px;padding:3px 10px;font-size:12px;margin:0 6px 6px 0}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block}
svg{display:block;width:100%;height:auto;overflow:visible}
.tip{position:fixed;pointer-events:none;background:var(--raise);border:1px solid var(--line);
 border-radius:6px;padding:6px 9px;font-size:12px;box-shadow:0 6px 20px rgba(0,0,0,.35);opacity:0;
 transition:opacity .1s;z-index:9;font-variant-numeric:tabular-nums}
.banner{border:1px solid var(--line);border-left:3px solid var(--brand);background:var(--panel);
 border-radius:6px;padding:11px 14px;margin-bottom:16px;font-size:13px}
.grid{display:grid;gap:16px}.wide{grid-column:1/-1}
ul{padding-left:18px}
@media (max-width:1100px){.top{grid-template-columns:1fr auto;height:auto;padding:8px 16px;
 row-gap:4px}.strip{grid-column:1/-1}.tabs{grid-column:1/-1;justify-content:flex-start}
 .tabs a{padding:10px}.shell{grid-template-columns:1fr}
 .side{border-right:none;border-bottom:1px solid var(--line)}}
@media (max-width:520px){.main{padding:16px}.big{font-size:32px}
 .wl{grid-template-columns:1fr 64px 80px;padding:10px 16px}.wl .qty,.wl span:nth-child(3){display:none}}
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
        fill:p.suspect?"none":s.color,stroke:p.suspect?css("--warn"):css("--panel"),
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
    const seg=el("path",{d:p,fill:row.color,stroke:css("--panel"),"stroke-width":1.5});
    seg.style.cursor="crosshair";
    seg.addEventListener("mousemove",e=>show("<b>"+row.label+"</b><br>"+inr(row.value)+
      " &middot; "+(row.value/total*100).toFixed(1)+"%",e));
    seg.addEventListener("mouseleave",hide);
    svg.appendChild(seg); a0=a1;
  });
  mount.innerHTML=""; mount.appendChild(svg);
}

const PALETTE=["#4f6ef7","#03a9f4","#2196f3","#9c27b0","#673ab7","#3f51b5","#00bcd4","#009688",
  "#8bc34a","#ff9800"];

(function(){
  const colors={SYSTEM:css("--brand"),BASELINE_EW:css("--up"),BASELINE:css("--dim"),
    REAL:css("--accent")};
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

  // The same book values, without the legend, on the dashboard.
  const overview=document.getElementById("overview-chart");
  if(overview) lineChart(overview,series,{height:220});

  barChart(document.getElementById("holdings-chart"),
    D.holdings.filter(h=>h.value!=null).sort((a,b)=>b.value-a.value).map(h=>({
      label:h.ticker, value:h.value,
      color:(h.pnl>=0?css("--up"):css("--down")),
      right:inr(h.value),
      tip:h.quantity+" @ "+inr(h.cost)+" paid<br>last close "+inr(h.mark)+"<br>"+
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

  // Allocation: one segment per holding, by current value or by what was paid. A holding with no
  // close makes the current-value bar unknown rather than drawing the others as the whole.
  const exact = n => "₹"+n.toLocaleString("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2});
  document.querySelectorAll("[data-alloc]").forEach(bar=>{
    const foot=bar.nextElementSibling, total=foot.querySelector("[data-alloc-total]");
    const held=D.holdings.slice().sort((a,b)=>a.ticker<b.ticker?-1:1);
    const paint=mode=>{
      const rows=held.map((h,i)=>({h:h,i:i,v:mode==="value"?h.value:h.invested}));
      bar.innerHTML="";
      if(!rows.length){ total.innerHTML='<span class="dim">Nothing held.</span>'; return; }
      if(rows.some(r=>r.v==null)){
        total.innerHTML='<span class="dim">unknown — a holding has no close</span>'; return; }
      const sum=rows.reduce((a,r)=>a+r.v,0)||1;
      rows.forEach(r=>{ const d=document.createElement("div");
        d.style.width=(r.v/sum*100)+"%"; d.style.background=PALETTE[r.i%PALETTE.length];
        d.addEventListener("mousemove",e=>show("<b>"+r.h.ticker+"</b><br>"+exact(r.v)+
          " &middot; "+(r.v/sum*100).toFixed(1)+"%",e));
        d.addEventListener("mouseleave",hide); bar.appendChild(d); });
      total.textContent=exact(sum);
    };
    foot.querySelectorAll("input").forEach(inp=>inp.addEventListener("change",()=>paint(inp.value)));
    paint("value");
  });

  // Tabs: the address names the open section, so the reload after a run lands where it was.
  const tabs=[...document.querySelectorAll("section.tab")];
  const links=[...document.querySelectorAll(".tabs a")];
  const open=()=>{
    // Sections are "tab-<name>", not "<name>": an id equal to the hash makes the browser jump to it.
    const want=(location.hash||"#dashboard").slice(1);
    const hit=tabs.some(t=>t.id==="tab-"+want)?want:"dashboard";
    tabs.forEach(t=>t.classList.toggle("show",t.id==="tab-"+hit));
    links.forEach(a=>{ if(a.getAttribute("href")==="#"+hit) a.setAttribute("aria-current","page");
      else a.removeAttribute("aria-current"); });
    window.scrollTo(0,0);
  };
  addEventListener("hashchange",open); open();
})();
"""
