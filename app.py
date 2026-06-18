# -*- coding: utf-8 -*-
"""
桌前健康关怀助手 - 入口 (双模式)
  自用视图  http://127.0.0.1:5005/        —— 实时画面 + 关怀提醒 + 今日明细
  管理视图  http://127.0.0.1:5005/manage  —— 脱敏聚合(无原始画面)，可共享

启动：python app.py
"""
import json
import time
import threading
import webbrowser
from pathlib import Path

from flask import Flask, Response, jsonify, render_template_string, request

from monitor import Monitor
from storage import Store

BASE = Path(__file__).parent
CFG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))

store = Store(str(BASE / CFG["db_path"]), sample_interval=CFG.get("sample_interval", 30))
monitor = Monitor(CFG, store=store)
app = Flask(__name__)

CSS = r"""
:root{--bg:#0f1117;--card:#1a1d29;--line:#272b3a;--txt:#e6e8ef;--mut:#8a90a6;
 --focused:#5ac86b;--distracted:#f0a91e;--drowsy:#e63c3c;--away:#808080;--accent:#6aa6ff;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;padding:24px}
a{color:var(--accent);text-decoration:none}
h1{font-size:20px;font-weight:600}.sub{color:var(--mut);font-size:13px;margin:4px 0 18px}
.nav{margin-bottom:14px;font-size:13px}.nav b{color:var(--txt)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:18px}
.pill{display:inline-block;background:#13151f;border:1px solid var(--line);border-radius:20px;padding:3px 10px;font-size:12px;color:var(--mut)}
.grid{display:grid;grid-template-columns:1.25fr 1fr;gap:18px;max-width:1200px}
.vidwrap{border-radius:10px;overflow:hidden;background:#000}.vidwrap img{width:100%;display:block}
.statebig{font-size:32px;font-weight:700;margin:6px 0}
.dot{display:inline-block;width:14px;height:14px;border-radius:50%;margin-right:8px;vertical-align:middle}
.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:12px}
.metric{background:#13151f;border:1px solid var(--line);border-radius:10px;padding:11px}
.metric .v{font-size:20px;font-weight:700}.metric .k{font-size:11px;color:var(--mut);margin-top:2px}
.metric.warn{border-color:var(--drowsy)}.metric.warn .v{color:var(--drowsy)}
.bar{display:flex;align-items:center;margin:9px 0;font-size:13px}
.bar .lbl{width:52px;color:var(--mut)}.bar .track{flex:1;height:16px;background:#13151f;border-radius:6px;overflow:hidden;margin:0 10px}
.bar .fill{height:100%}.bar .val{width:64px;text-align:right;font-variant-numeric:tabular-nums}
.tl{display:flex;height:24px;border-radius:6px;overflow:hidden;margin-top:8px;background:#13151f}.tl span{height:100%}
.rem{display:flex;gap:10px;align-items:flex-start;background:#241c10;border:1px solid #4a3a17;border-radius:10px;padding:10px 12px;margin:8px 0}
.rem .t{font-weight:600}.rem .b{color:var(--mut);font-size:12px}
.btn{background:#23283a;border:1px solid var(--line);color:var(--txt);border-radius:8px;padding:7px 12px;cursor:pointer;font-size:13px}
.btn:hover{border-color:var(--accent)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:500}
.big{font-size:28px;font-weight:700}.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.foot{color:var(--mut);font-size:12px;margin-top:8px}
"""

PERSONAL = r"""
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>桌前健康关怀助手 · 自用</title>
<style>__CSS__</style></head><body>
<h1>桌前健康关怀助手</h1>
<div class="sub">基于笔记本摄像头 · 本地实时 · <span class="pill">隐私模式：不录像 · 不上传</span>
 · <a href="/manage">切换到管理视图 →</a></div>
<div class="grid">
 <div>
  <div class="card"><div class="vidwrap"><img src="/video"></div>
    <div class="foot" style="margin-top:10px">画面仅本机内存实时分析，落盘只有状态指标。
    <button class="btn" style="float:right" onclick="recal()">重设坐姿/距离基线</button></div>
  </div>
  <div class="card" id="remcard"><div style="color:var(--mut);font-size:13px;margin-bottom:6px">关怀提醒</div>
   <div id="reminders"><div class="foot">暂无提醒，状态良好 ✅</div></div></div>
 </div>
 <div>
  <div class="card">
   <div style="display:flex;justify-content:space-between;align-items:center">
     <div style="color:var(--mut);font-size:13px">今日健康分</div>
     <button class="btn" id="dndbtn" onclick="toggleDnd()" style="padding:4px 10px">勿扰：关</button>
   </div>
   <div style="display:flex;align-items:baseline;gap:10px;margin:6px 0">
     <span class="big" id="score" style="font-size:40px">--</span>
     <span class="foot" id="scoretip"></span>
   </div>
   <div id="scomps" style="font-size:12px;color:var(--mut)"></div>
   <div class="foot" id="rhythmline" style="margin-top:8px"></div>
  </div>
  <div class="card">
   <div style="color:var(--mut);font-size:13px">当前状态</div>
   <div class="statebig"><span class="dot" id="dot"></span><span id="state">--</span></div>
   <div class="metrics">
    <div class="metric" id="m_ear"><div class="v" id="ear">--</div><div class="k">EAR 眼睛开合</div></div>
    <div class="metric" id="m_perclos"><div class="v" id="perclos">--</div><div class="k">PERCLOS 闭眼比</div></div>
    <div class="metric" id="m_blink"><div class="v" id="blink">--</div><div class="k">眨眼 次/分</div></div>
    <div class="metric" id="m_dist"><div class="v" id="dist">--</div><div class="k">屏幕距离 cm</div></div>
    <div class="metric"><div class="v" id="screen">--</div><div class="k">连续注视 min</div></div>
    <div class="metric"><div class="v" id="seated">--</div><div class="k">连续久坐 min</div></div>
    <div class="metric" id="m_slouch"><div class="v" id="slouch" style="font-size:15px">--</div><div class="k">坐姿(驼背/高低肩)</div></div>
    <div class="metric"><div class="v" id="hr">--</div><div class="k">心率 bpm(估)</div></div>
    <div class="metric" id="m_stress"><div class="v" id="stress">--</div><div class="k">压力(估)</div></div>
    <div class="metric" id="m_tension"><div class="v" id="tension">--</div><div class="k">紧张度(估)</div></div>
    <div class="metric" id="m_env"><div class="v" id="envlum">--</div><div class="k">环境光</div></div>
   </div>
  </div>
  <div class="card">
   <div style="color:var(--mut);font-size:13px;margin-bottom:6px">今日在岗 · <span id="day"></span></div>
   <div id="bars"></div>
   <div style="color:var(--mut);font-size:13px;margin-top:12px">今日时间线</div>
   <div class="tl" id="timeline"></div>
   <div class="foot">离岗 <b id="awaycnt">0</b> 次 · 专注率 <b id="focusrate">--</b> · 帧率 <b id="fps">--</b></div>
  </div>
 </div>
</div>
<script>
const COL={focused:'#5ac86b',distracted:'#f0a91e',drowsy:'#e63c3c',away:'#808080'};
const LBL={focused:'专注',distracted:'分心',drowsy:'疲劳',away:'离岗'};
function fmt(s){s=Math.round(s);let h=(s/3600|0),m=(s%3600/60|0),x=s%60;return (h?h+'h':'')+(m||h?m+'m':'')+x+'s';}
function setWarn(id,on){document.getElementById(id).classList.toggle('warn',!!on);}
async function recal(){await fetch('/api/recalibrate',{method:'POST'});alert('请保持端正坐姿数秒，正在重新校准基线');}
let DND=false;
async function toggleDnd(){DND=!DND;await fetch('/api/dnd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({on:DND})});}
const COMPCN={focus:'专注',posture:'坐姿',calm:'平静',relax:'放松',move:'起身'};
async function tick(){try{
 const d=await (await fetch('/api/status')).json();const s=d.state;
 document.getElementById('state').textContent=LBL[s.state]||s.state;
 document.getElementById('dot').style.background=COL[s.state];
 const f=s.fatigue,e=s.eyecare,p=s.posture,r=s.rppg,af=s.affect||{},en=s.env||{},ry=s.rhythm||{};
 // 健康分
 const sc=d.score||{};
 document.getElementById('score').textContent=(sc.score==null?'--':sc.score);
 document.getElementById('scoretip').textContent=(sc.score==null?'样本积累中':('连续达标 '+(d.streak||0)+' 天'));
 document.getElementById('scomps').innerHTML=Object.entries(sc.components||{}).map(([k,v])=>
   `${COMPCN[k]||k} ${v}`).join('　');
 const rl=[]; if(ry.meeting)rl.push('🎤 会议模式(静音)'); if(ry.dnd)rl.push('🌙 勿扰'); if(ry.quiet)rl.push('😴 安静时段');
 if(ry.breaks_suggested)rl.push('起身依从 '+(ry.breaks_taken||0)+'/'+ry.breaks_suggested);
 document.getElementById('rhythmline').textContent=rl.join('　·　');
 DND=!!ry.dnd; document.getElementById('dndbtn').textContent='勿扰：'+(DND?'开':'关');
 // 紧张度/环境光
 document.getElementById('tension').textContent=af.valid?af.tension:'--';
 setWarn('m_tension',af.valid&&af.tension>=60);
 document.getElementById('envlum').textContent=(en.lum!=null?(en.dark?'偏暗':(en.bright?'过亮':'适宜')):'--');
 setWarn('m_env',en.dark||en.bright);
 document.getElementById('ear').textContent=f.ear.toFixed(2);
 document.getElementById('perclos').textContent=Math.round(f.perclos*100)+'%';
 document.getElementById('blink').textContent=Math.round(f.blink_rate);
 document.getElementById('dist').textContent=e.est_cm||'--';
 document.getElementById('screen').textContent=e.screen_minutes;
 document.getElementById('seated').textContent=p.seated_minutes;
 const pIssues=(p.issues&&p.issues.length)?p.issues.join('·'):'良好';
 document.getElementById('slouch').textContent=!p.pose_ok?'--':(p.calibrating?'校准中':pIssues);
 document.getElementById('hr').textContent=r.valid?r.bpm:'测量中';
 document.getElementById('stress').textContent=r.valid?r.stress:'--';
 setWarn('m_perclos',f.perclos>=0.4);setWarn('m_dist',e.too_close);
 setWarn('m_slouch',p.issues&&p.issues.length>0);setWarn('m_stress',r.valid&&r.stress>=60);setWarn('m_ear',f.drowsy);
 document.getElementById('fps').textContent=s.fps;
 // reminders
 const rem=s.reminders||[];
 document.getElementById('reminders').innerHTML=rem.length?rem.map(x=>
   `<div class="rem"><div><div class="t">${x.title}</div><div class="b">${x.body}</div></div></div>`).join('')
   :'<div class="foot">暂无提醒，状态良好 ✅</div>';
 // today
 const sm=d.summary;document.getElementById('day').textContent=sm.day;
 document.getElementById('awaycnt').textContent=sm.away_count;
 const order=['focused','distracted','drowsy','away'];
 const tot=order.reduce((a,k)=>a+(sm.durations[k]||0),0)||1;
 document.getElementById('bars').innerHTML=order.map(k=>{const v=sm.durations[k]||0,pct=(v/tot*100).toFixed(1);
  return `<div class="bar"><div class="lbl">${LBL[k]}</div><div class="track"><div class="fill" style="width:${pct}%;background:${COL[k]}"></div></div><div class="val">${fmt(v)}</div></div>`;}).join('');
 const onjob=(sm.durations.focused||0)+(sm.durations.distracted||0)+(sm.durations.drowsy||0);
 document.getElementById('focusrate').textContent=onjob?Math.round((sm.durations.focused||0)/onjob*100)+'%':'--';
 document.getElementById('timeline').innerHTML=sm.timeline.map(g=>{const w=(g.end-g.start)/tot*100;
  return `<span style="width:${w}%;background:${COL[g.state]}" title="${LBL[g.state]}"></span>`;}).join('');
}catch(err){}}
setInterval(tick,1000);tick();
</script></body></html>
"""

MANAGE = r"""
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>桌前健康关怀助手 · 管理视图</title>
<style>__CSS__</style></head><body>
<h1>团队/个人健康概览 · 管理视图</h1>
<div class="sub"><span class="pill">脱敏聚合 · 无原始画面 · 可共享</span>
 · 使用前请告知并征得被监测者同意 · <a href="/">← 返回自用视图</a></div>
<div class="card" style="max-width:1100px">
 <div style="color:var(--mut);font-size:13px;margin-bottom:10px">今日健康 KPI · <span id="day"></span></div>
 <div class="kpis">
  <div><div class="big" id="focusmin">--</div><div class="foot">专注时长(min)</div></div>
  <div><div class="big" id="focusrate">--</div><div class="foot">专注率</div></div>
  <div><div class="big" id="drowsymin">--</div><div class="foot">疲劳时长(min)</div></div>
  <div><div class="big" id="slouch">--</div><div class="foot">驼背时间占比</div></div>
  <div><div class="big" id="bpm">--</div><div class="foot">平均心率(估)</div></div>
  <div><div class="big" id="stress">--</div><div class="foot">平均压力(估)</div></div>
  <div><div class="big" id="away">--</div><div class="foot">离岗次数</div></div>
  <div><div class="big" id="remtot">--</div><div class="foot">关怀提醒次数</div></div>
 </div>
</div>
<div class="card" style="max-width:1100px">
 <div style="color:var(--mut);font-size:13px;margin-bottom:8px">近 7 日趋势</div>
 <table><thead><tr><th>日期</th><th>健康分</th><th>专注(min)</th><th>专注率</th><th>疲劳(min)</th><th>驼背占比</th><th>均心率</th><th>均压力</th><th>提醒</th></tr></thead>
 <tbody id="trend"></tbody></table>
 <div class="foot">数据均为本机本地计算的聚合指标，不含任何图像或可识别原始记录。</div>
</div>
<script>
function remSum(o){return Object.values(o||{}).reduce((a,b)=>a+b,0);}
async function load(){try{
 const d=await (await fetch('/api/health')).json();const t=d.today;
 document.getElementById('day').textContent=t.day;
 document.getElementById('focusmin').textContent=t.focus_minutes;
 document.getElementById('focusrate').textContent=t.focus_rate+'%';
 document.getElementById('drowsymin').textContent=t.drowsy_minutes;
 document.getElementById('slouch').textContent=t.slouch_ratio+'%';
 document.getElementById('bpm').textContent=t.avg_bpm||'--';
 document.getElementById('stress').textContent=t.avg_stress||'--';
 document.getElementById('away').textContent=t.away_count;
 document.getElementById('remtot').textContent=remSum(t.reminders);
 document.getElementById('trend').innerHTML=d.week.map(w=>
  `<tr><td>${w.day}</td><td><b>${w.score==null?'—':w.score}</b></td><td>${w.focus_minutes}</td><td>${w.focus_rate}%</td><td>${w.drowsy_minutes}</td><td>${w.slouch_ratio}%</td><td>${w.avg_bpm||'--'}</td><td>${w.avg_stress||'--'}</td><td>${remSum(w.reminders)}</td></tr>`).join('');
}catch(e){}}
load();setInterval(load,5000);
</script></body></html>
"""


@app.route("/")
def index():
    return render_template_string(PERSONAL.replace("__CSS__", CSS))


@app.route("/manage")
def manage():
    return render_template_string(MANAGE.replace("__CSS__", CSS))


@app.route("/video")
def video():
    def gen():
        boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        while True:
            jpg = monitor.get_jpeg()
            if jpg:
                yield boundary + jpg + b"\r\n"
            time.sleep(1.0 / max(1, CFG["target_fps"]))
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/status")
def status():
    return jsonify({"state": monitor.snapshot(), "summary": store.daily_summary(),
                    "score": store.health_score(),
                    "streak": store.streak(CFG.get("score_streak_threshold", 70))})


@app.route("/api/dnd", methods=["POST"])
def dnd():
    on = bool((request.get_json(silent=True) or {}).get("on", False))
    monitor.set_dnd(on)
    return jsonify({"ok": True, "dnd": on})


@app.route("/api/health")
def health():
    return jsonify({"today": store.health_summary(), "week": store.weekly_trend(7)})


@app.route("/api/recalibrate", methods=["POST"])
def recalibrate():
    monitor.recalibrate()
    return jsonify({"ok": True})


def main():
    threading.Thread(target=monitor.run, daemon=True).start()
    url = f"http://{CFG['dashboard_host']}:{CFG['dashboard_port']}"
    print(f"\n  桌前健康关怀助手已启动")
    print(f"    自用视图  {url}/")
    print(f"    管理视图  {url}/manage")
    print("  隐私模式：仅本地计算状态指标，不保存视频/图像。Ctrl+C 退出。\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    app.run(host=CFG["dashboard_host"], port=CFG["dashboard_port"],
            threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
