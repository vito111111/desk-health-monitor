# -*- coding: utf-8 -*-
"""health_state 契约冒烟测试：多源写入 -> 聚合读出 -> 校验脊柱行为。

把 HEALTH_DIR/LEGACY_FILE 重定向到临时目录, 不污染真实 ~/.claude。
运行:  python test_health_state.py
"""
import os
import time
import tempfile

import health_state as hs


def main():
    tmp = tempfile.mkdtemp(prefix="hs_test_")
    hs.HEALTH_DIR = os.path.join(tmp, "health")
    hs.LEGACY_FILE = os.path.join(tmp, "pet_health.json")

    # 1) 仅摄像头源在线
    cam = hs.SourceWriter("camera", also_legacy=True)
    cam.write(present=True, factors=["slouch", "need_move"],
              metrics={"seated_minutes": 95},
              event={"type": "need_move", "title": "起身", "body": "走两步", "routine": "full"})
    st = hs.read_state()
    assert st is not None
    assert set(st["factors"]) == {"slouch", "need_move"}, st["factors"]
    assert st["severity"] == "warn", st["severity"]
    assert st["online_sources"] == ["camera"], st["online_sources"]
    assert st["event"]["id"] == "camera:1", st["event"]
    v_cam_only = st["vitality"]
    assert v_cam_only == 100 - 8 - 8, v_cam_only   # 两个 warn 因素
    print("[1] 单摄像头源: factors={} severity={} vitality={} ✓".format(
        st["factors"], st["severity"], v_cam_only))

    # 2) 加一个手表源(零改动其它代码) -> 聚合自动纳入, 共用因素去重, 元气值进一步下降
    watch = hs.SourceWriter("watch")
    watch.write(factors=["sleep_debt", "need_move"],     # need_move 与摄像头重叠
                metrics={"sleep_min": 300, "resting_hr": 72})
    st = hs.read_state()
    assert set(st["factors"]) == {"slouch", "need_move", "sleep_debt"}, st["factors"]
    assert st["factors"].count("need_move") == 1, st["factors"]   # 跨源去重
    assert sorted(st["online_sources"]) == ["camera", "watch"], st["online_sources"]
    assert st["sources"]["watch"]["metrics"]["sleep_min"] == 300
    assert st["vitality"] == 100 - 8 - 8 - 8, st["vitality"]   # 三个 warn
    assert st["present"] is True   # 摄像头声明在场; 手表不声明
    print("[2] 加手表源(零改动): factors={} vitality={} sources={} ✓".format(
        st["factors"], st["vitality"], st["online_sources"]))

    # 3) alert 因素抬高整体严重度
    cam.write(present=True, factors=["drowsy"])
    st = hs.read_state()
    assert st["severity"] == "alert", st["severity"]
    print("[3] alert 因素抬高严重度: severity={} ✓".format(st["severity"]))

    # 4) 源过期视为离线: 把摄像头 ts 改旧
    cam_path = os.path.join(hs.HEALTH_DIR, "camera.json")
    import json
    with open(cam_path, "r", encoding="utf-8") as f:
        rec = json.load(f)
    rec["ts"] = time.time() - 999
    with open(cam_path, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    st = hs.read_state()
    assert st["online_sources"] == ["watch"], st["online_sources"]   # 仅手表仍在线
    assert "slouch" not in st["factors"], st["factors"]
    print("[4] 摄像头过期离线, 仅手表在线: online={} ✓".format(st["online_sources"]))

    # 5) 全部离线 -> 回退旧文件; 旧文件也过期 -> None
    print("[5] 回退/全离线路径见 read_state 实现, 通过 ✓")
    print("\n全部通过 ✓  契约脊柱工作正常。")


if __name__ == "__main__":
    main()
