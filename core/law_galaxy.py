"""법령 은하 — 32개 법령을 중심 노드로 둔 3D 관계도 (자체 완결 HTML).

법령군을 3D 공간에 흩고, 각 법령을 그 군의 궤도에, 조문을 다시 법령 주위에 둔다.
법령군 간 인용만 호(arc)로 잇는다 — 시행령→모법은 위임 구조상 당연해서 그리면
나머지를 덮는다.

**외부 라이브러리를 쓰지 않는다.** 캔버스에 회전·원근 투영을 직접 계산한다.
CDN을 물면 폐쇄망·오프라인·Artifacts(CSP)에서 통째로 깨지는데, 이 도구가 놓일
자리가 대개 그런 곳이다. 좌표는 파이썬이 결정적으로 계산해 JSON으로 심는다 —
브라우저에서 난수를 돌리면 열 때마다 그림이 달라진다.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from core import law_abbrev
from core.law_map import family

ROOT = Path(__file__).resolve().parents[1]
_GRAPH = ROOT / "data" / "law-citation-graph.json"

_FAMILY_COLOR: dict[str, str] = {
    "소득세법": "#5b8cff", "법인세법": "#3ddc84", "부가가치세법": "#ffb03a",
    "상속세 및 증여세법": "#c084fc", "조세특례제한법": "#ff6b8a",
    "국제조세조정에 관한 법률": "#2dd4bf", "관세법": "#fbbf24",
    "국세기본법": "#94a3b8", "국세징수법": "#cbd5e1",
    "농어촌특별세법": "#f472b6", "종합부동산세법": "#60a5fa",
}
_TIER = {"": 0, "시행령": 1, "시행규칙": 2}      # 모법 → 령 → 칙 순으로 바깥 궤도


def _tier(law_name: str) -> int:
    for suffix, idx in (("시행규칙", 2), ("시행령", 1)):
        if law_name.endswith(suffix):
            return idx
    return 0


def build(min_edge: int = 8, max_articles_per_law: int = 220) -> dict:
    """법령·조문 좌표와 법령군 간 인용 엣지.

    조문은 법령당 상한을 둔다. 조특령(450조)까지 전부 찍으면 점이 뭉쳐 은하가
    아니라 얼룩이 된다 — 연결이 많은 조문부터 남긴다.
    """
    edges = json.loads(_GRAPH.read_text(encoding="utf-8"))["edges"]

    # 인용 원문의 표기 흔들림('소득세법 ', '소득세법시행령')이 별도 노드가 되지
    # 않도록 추적 목록의 정식 명칭으로 맞춘다. 목록에 없는 법령(지방세법 등)은
    # 조문 데이터가 없어 점을 찍을 수 없으므로 노드로 만들지 않는다.
    from core.law_freshness import load_manifest

    canonical = {
        str(e.get("name", "")).replace(" ", ""): str(e.get("name", ""))
        for e in load_manifest().get("laws", [])
    }

    def norm(name: str) -> str:
        return canonical.get(str(name).replace(" ", "").strip(), "")

    laws: Counter[str] = Counter()
    degree: dict[str, Counter[str]] = defaultdict(Counter)
    pair: Counter[tuple[str, str]] = Counter()
    for e in edges:
        a, b = norm(e.get("source_law", "")), norm(e.get("target_law", ""))
        if not a or not b:
            continue
        laws[a] += 1
        laws[b] += 0
        degree[a][str(e.get("source_jo", ""))] += 1
        if a != b and family(a) != family(b):
            pair[(a, b)] += 1

    names = sorted(laws)
    fams = sorted({family(n) for n in names})
    fam_index = {f: i for i, f in enumerate(fams)}

    # 법령군을 구(球) 위에 균등 배치 — 황금각이라 개수가 바뀌어도 고르게 퍼진다
    nodes: list[dict] = []
    positions: dict[str, tuple[float, float, float]] = {}
    for name in names:
        fam = family(name)
        i = fam_index[fam]
        n = len(fams)
        y = 1 - 2 * (i + 0.5) / n
        rad = math.sqrt(max(0.0, 1 - y * y))
        theta = math.pi * (3 - math.sqrt(5)) * i
        fx, fy, fz = math.cos(theta) * rad, y, math.sin(theta) * rad
        # 같은 군의 모법·령·칙은 중심에서 밖으로 계단 배치
        t = _tier(name)
        scale = 300 + t * 46
        jitter = 0.10 * t
        x = fx * scale + math.cos(theta + jitter) * 26 * t
        yy = fy * scale + jitter * 34
        z = fz * scale + math.sin(theta + jitter) * 26 * t
        positions[name] = (x, yy, z)
        nodes.append({
            "id": name,
            "label": law_abbrev.law(name),
            "family": fam,
            "color": _FAMILY_COLOR.get(fam, "#8fa3bf"),
            "tier": t,
            "count": laws[name],
            "x": round(x, 1), "y": round(yy, 1), "z": round(z, 1),
        })

    # 조문 — 소속 법령 주위 구면에 결정적으로 배치
    dust: list[dict] = []
    for name in names:
        top = [jo for jo, _n in degree[name].most_common(max_articles_per_law)]
        cx, cy, cz = positions[name]
        color = _FAMILY_COLOR.get(family(name), "#8fa3bf")
        for k, jo in enumerate(sorted(top, key=lambda s: (len(s), s))):
            y = 1 - 2 * (k + 0.5) / max(len(top), 1)
            rad = math.sqrt(max(0.0, 1 - y * y))
            th = math.pi * (3 - math.sqrt(5)) * k
            r = 46 + (k % 7) * 5
            dust.append({
                "x": round(cx + math.cos(th) * rad * r, 1),
                "y": round(cy + y * r, 1),
                "z": round(cz + math.sin(th) * rad * r, 1),
                "c": color,
                "law": law_abbrev.law(name),
                "jo": law_abbrev.jo_key(jo),
            })

    links = [
        {"a": a, "b": b, "n": n}
        for (a, b), n in sorted(pair.items(), key=lambda kv: -kv[1])
        if n >= min_edge
    ]
    return {"nodes": nodes, "dust": dust, "links": links, "families": fams}


_HTML = """<div id="galaxy-wrap" style="position:relative;width:100%;height:__H__px;
 background:radial-gradient(ellipse at 50% 45%,#101a2e 0%,#070b14 70%);
 border-radius:10px;overflow:hidden;font-family:Pretendard,-apple-system,sans-serif">
<canvas id="galaxy" style="display:block;width:100%;height:100%;cursor:grab"></canvas>
<div id="hud" style="position:absolute;top:12px;left:14px;color:#cbd5e1;font-size:12px;
 line-height:1.7;pointer-events:none;text-shadow:0 1px 3px #000">
 <div style="font-size:14px;font-weight:700;color:#f1f5f9">법령 은하 — __NLAW__개 법령 · __NDUST__개 조문</div>
 <div style="opacity:.75">드래그 회전 · 휠 확대 · 법령 클릭 시 인용 강조 · 빈 곳 클릭 해제</div>
 <div id="pick" style="margin-top:6px;color:#7dd3fc;min-height:18px"></div></div>
<div id="legend" style="position:absolute;right:14px;top:12px;color:#94a3b8;font-size:11px;
 line-height:1.8;text-align:right;pointer-events:none;text-shadow:0 1px 3px #000"></div>
</div>
<script>
(function(){
 const D=__DATA__, cv=document.getElementById('galaxy'), ctx=cv.getContext('2d');
 const hudPick=document.getElementById('pick'), legend=document.getElementById('legend');
 legend.innerHTML=D.families.map(f=>{
   const c=(D.nodes.find(n=>n.family===f)||{}).color||'#888';
   return '<div><span style="color:'+c+'">\\u25cf</span> '+f+'</div>';}).join('');

 let rx=-0.32, ry=0.6, zoom=1, drag=null, sel=null, auto=true;
 function size(){const r=cv.getBoundingClientRect(),d=window.devicePixelRatio||1;
   cv.width=r.width*d; cv.height=r.height*d; ctx.setTransform(d,0,0,d,0,0);}
 size(); addEventListener('resize',size);

 function proj(p){
   const cy=Math.cos(ry),sy=Math.sin(ry),cx=Math.cos(rx),sx=Math.sin(rx);
   let x=p.x*cy - p.z*sy, z=p.x*sy + p.z*cy, y=p.y*cx - z*sx; z=p.y*sx + z*cx;
   const r=cv.getBoundingClientRect(), f=760*zoom, d=f/(f+z+900);
   return {sx:r.width/2 + x*d, sy:r.height/2 + y*d, d:d, z:z};
 }
 function draw(){
   const r=cv.getBoundingClientRect();
   ctx.clearRect(0,0,r.width,r.height);
   if(auto) ry+=0.0016;

   const P={}; D.nodes.forEach(n=>P[n.id]=proj(n));
   // 조문 먼저 — 뒤쪽부터 그려 깊이가 보이게
   const dust=D.dust.map(p=>({p:p,q:proj(p)})).sort((a,b)=>b.q.z-a.q.z);
   for(const o of dust){
     const dim = sel && o.p.law!==sel.label ? 0.10 : 0.62;
     ctx.globalAlpha=dim*Math.max(0.15,o.q.d);
     ctx.fillStyle=o.p.c;
     ctx.beginPath(); ctx.arc(o.q.sx,o.q.sy,Math.max(0.5,1.5*o.q.d),0,6.283); ctx.fill();
   }
   // 법령군 간 인용
   for(const l of D.links){
     const a=P[l.a], b=P[l.b]; if(!a||!b) continue;
     const on = !sel || sel.id===l.a || sel.id===l.b;
     ctx.globalAlpha = on ? Math.min(0.10+l.n/900,0.5) : 0.03;
     ctx.strokeStyle = (D.nodes.find(n=>n.id===l.a)||{}).color||'#888';
     ctx.lineWidth = on ? Math.max(0.6, Math.min(l.n/90,3.4)) : 0.5;
     const mx=(a.sx+b.sx)/2, my=(a.sy+b.sy)/2, r2=cv.getBoundingClientRect();
     ctx.beginPath(); ctx.moveTo(a.sx,a.sy);
     ctx.quadraticCurveTo(mx+(r2.width/2-mx)*0.25, my+(r2.height/2-my)*0.25, b.sx,b.sy);
     ctx.stroke();
   }
   // 법령 노드
   const order=D.nodes.map(n=>({n:n,q:P[n.id]})).sort((a,b)=>b.q.z-a.q.z);
   for(const o of order){
     const n=o.n,q=o.q, on = !sel || sel.id===n.id;
     const rr=Math.max(3,(5+Math.min(n.count/260,9))*q.d);
     ctx.globalAlpha=on?1:0.25;
     const g=ctx.createRadialGradient(q.sx,q.sy,0,q.sx,q.sy,rr*3.2);
     g.addColorStop(0,n.color); g.addColorStop(1,'rgba(0,0,0,0)');
     ctx.fillStyle=g; ctx.beginPath(); ctx.arc(q.sx,q.sy,rr*3.2,0,6.283); ctx.fill();
     ctx.fillStyle=n.color; ctx.beginPath(); ctx.arc(q.sx,q.sy,rr,0,6.283); ctx.fill();
     if(q.d>0.55 || sel&&sel.id===n.id){
       ctx.globalAlpha=on?0.96:0.3;
       ctx.font='600 '+Math.max(10,12*q.d)+'px Pretendard,sans-serif';
       ctx.fillStyle='#eef4ff'; ctx.textAlign='center';
       ctx.fillText(n.label, q.sx, q.sy-rr-6);
     }
     o.rr=rr;
   }
   D.__hit = order;
   requestAnimationFrame(draw);
 }
 // 회전 중 손을 떼면 그 자리 법령이 선택되던 문제 — mousemove 발생 여부(플래그)에
 // 기대지 말고 누른 지점에서 실제로 얼마나 움직였는지로 가른다. 손떨림 몇 px은
 // 클릭으로, 그 이상은 회전으로 본다.
 const CLICK_SLOP=6;
 cv.addEventListener('mousedown',e=>{
   drag={x:e.clientX,y:e.clientY,ox:e.clientX,oy:e.clientY};auto=false;cv.style.cursor='grabbing';});
 addEventListener('mouseup',e=>{
   if(drag && Math.hypot(e.clientX-drag.ox, e.clientY-drag.oy) <= CLICK_SLOP){
     const r=cv.getBoundingClientRect(), mx=e.clientX-r.left, my=e.clientY-r.top;
     let best=null,bd=26;
     for(const o of (D.__hit||[])){const d=Math.hypot(o.q.sx-mx,o.q.sy-my); if(d<bd){bd=d;best=o.n;}}
     sel = best && (!sel || sel.id!==best.id) ? best : null;
     hudPick.textContent = sel ? sel.label+' — 인용 '+sel.count+'건' : '';
   }
   drag=null; cv.style.cursor='grab';
 });
 addEventListener('mousemove',e=>{
   if(!drag) return;
   ry+=(e.clientX-drag.x)*0.005; rx+=(e.clientY-drag.y)*0.005;
   rx=Math.max(-1.4,Math.min(1.4,rx)); drag.x=e.clientX; drag.y=e.clientY;
 });
 cv.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(0.35,Math.min(3.4,zoom*(e.deltaY<0?1.1:0.9)));},{passive:false});
 draw();
})();
</script>"""


def render_html(data: dict, height: int = 720) -> str:
    """자체 완결 HTML 조각. 외부 요청이 없어 폐쇄망·CSP 환경에서도 뜬다."""
    return (
        _HTML.replace("__DATA__", json.dumps(data, ensure_ascii=False))
        .replace("__H__", str(height))
        .replace("__NLAW__", str(len(data["nodes"])))
        .replace("__NDUST__", f"{len(data['dust']):,}")
    )


def render_page(data: dict, height: int = 760) -> str:
    """브라우저에서 바로 여는 단독 페이지."""
    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>법령 은하</title>"
        "<style>body{margin:0;background:#070b14;padding:16px}</style></head><body>"
        + render_html(data, height)
        + "</body></html>"
    )
