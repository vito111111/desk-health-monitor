# -*- coding: utf-8 -*-
"""冒烟测试：跑监控循环数秒，验证摄像头/各模块/快照。不依赖网页。"""
import json, time, threading, traceback
from pathlib import Path
from monitor import Monitor
from storage import Store

CFG = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))
store = Store(str(Path(__file__).parent / "smoke_test.db"))
mon = Monitor(CFG, store=store)

err = {}
def run():
    try:
        mon.run()
    except Exception as e:
        err["e"] = traceback.format_exc()

t = threading.Thread(target=run, daemon=True); t.start()
time.sleep(7)
mon.stop(); time.sleep(1.5)

if err:
    print("RUN ERROR:\n", err["e"])
else:
    snap = mon.snapshot()
    print("running:", mon.running)
    print("jpeg bytes:", len(mon.get_jpeg() or b""))
    print("state:", snap["state"], snap["label"])
    print("fatigue:", {k: round(v,3) if isinstance(v,float) else v for k,v in snap["fatigue"].items()})
    print("eyecare:", snap["eyecare"])
    print("posture:", snap["posture"])
    print("rppg:", snap["rppg"])
    print("presence:", snap["presence"])
    print("reminders:", [r["type"] for r in snap["reminders"]])
    print("daily_summary:", store.daily_summary())
    print("health_summary:", store.health_summary())
print("SMOKE DONE")
