# -*- coding: utf-8 -*-
"""
桌前健康关怀助手 - 桌面客户端
把原有 Web 看板封装成原生应用窗口（Edge WebView2，无浏览器地址栏），
并常驻系统托盘。关闭窗口 = 最小化到托盘，监控继续；托盘菜单可退出。

启动：pythonw client.py   （由桌面图标调用，无黑窗口）
"""
import os
# 本地回环不走系统代理(若设置了 HTTP_PROXY/Tinyproxy 等)
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")
import sys
import time
import socket
import subprocess
import threading
from pathlib import Path

import webview
import pystray
from PIL import Image

from app import app, monitor, CFG

BASE = Path(__file__).parent
HOST = CFG.get("dashboard_host", "127.0.0.1")
PORT = CFG.get("dashboard_port", 5005)
URL = f"http://{HOST}:{PORT}"
ICON = BASE / "app.ico"

window = None
tray = None
_hidden_once = False

# 桌面宠物(claude-pet)：健康联动的展示端
PET_DIR = Path(os.path.expanduser("~")) / "claude-pet"
PET_PY = PET_DIR / "pet.py"
PET_PORT = 50573          # 宠物单例守卫端口；已监听=已在运行


def ensure_pet():
    """确保桌面宠物在运行(它会读取健康状态并联动)。已运行则跳过。"""
    if not CFG.get("pet_integration", True) or not PET_PY.exists():
        return
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as t:
            t.settimeout(0.3)
            if t.connect_ex(("127.0.0.1", PET_PORT)) == 0:
                return  # 已在运行
    except OSError:
        pass
    try:
        pyw = sys.executable  # 本进程即 pythonw
        subprocess.Popen([pyw, str(PET_PY), "--resident"],
                         cwd=str(PET_DIR),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass


def _serve():
    app.run(host=HOST, port=PORT, threaded=True, debug=False, use_reloader=False)


def _wait_port(timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            if s.connect_ex((HOST, PORT)) == 0:
                return True
        time.sleep(0.2)
    return False


# ---------- 窗口 / 托盘 行为 ----------
def on_closing():
    """点 X 不退出，隐藏到托盘，摄像头与监控继续。"""
    global _hidden_once
    window.hide()
    if tray and not _hidden_once:
        _hidden_once = True
        try:
            tray.notify("已最小化到托盘，监控继续运行。\n右键托盘图标可彻底退出。", "桌前健康助手")
        except Exception:
            pass
    return False  # 取消真正的关闭


def show_personal(icon=None, item=None):
    window.load_url(URL + "/")
    window.show()
    try:
        window.restore()
    except Exception:
        pass


def show_manage(icon=None, item=None):
    window.load_url(URL + "/manage")
    window.show()


def recalibrate(icon=None, item=None):
    try:
        monitor.recalibrate()
        if tray:
            tray.notify("已重新校准：请保持端正坐姿与舒适距离几秒。", "桌前健康助手")
    except Exception:
        pass


def quit_app(icon=None, item=None):
    try:
        monitor.stop()
    except Exception:
        pass
    time.sleep(0.4)  # 让采集循环走到 finally 释放摄像头
    try:
        if tray:
            tray.stop()
    except Exception:
        pass
    try:
        window.destroy()
    except Exception:
        pass
    os._exit(0)


def build_tray():
    img = Image.open(ICON)
    menu = pystray.Menu(
        pystray.MenuItem("显示主界面", show_personal, default=True),
        pystray.MenuItem("管理视图", show_manage),
        pystray.MenuItem("重新校准坐姿/距离", recalibrate),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", quit_app),
    )
    return pystray.Icon("desk_health", img, "桌前健康关怀助手", menu)


def main():
    global window, tray
    # 后台启动 Web 服务 + 摄像头监控
    threading.Thread(target=_serve, daemon=True).start()
    threading.Thread(target=monitor.run, daemon=True).start()
    ensure_pet()   # 拉起桌面宠物(健康联动展示端)
    if not _wait_port():
        # 服务起不来：兜底用浏览器
        import webbrowser
        webbrowser.open(URL)
        return

    # 系统托盘（独立线程）
    tray = build_tray()
    tray.run_detached()

    # 原生应用窗口
    window = webview.create_window(
        "桌前健康关怀助手", URL + "/",
        width=1180, height=820, min_size=(900, 640))
    window.events.closing += on_closing

    try:
        webview.start(icon=str(ICON))
    except TypeError:
        # 老版本 pywebview 不接受 icon 参数
        webview.start()
    except Exception:
        # WebView2 运行时缺失等：兜底浏览器
        import webbrowser
        webbrowser.open(URL)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return

    # 走到这里说明窗口已被销毁
    quit_app()


if __name__ == "__main__":
    main()
