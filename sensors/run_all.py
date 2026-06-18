# -*- coding: utf-8 -*-
"""穿戴源统一守护启动器 —— 把已配置好的穿戴设备源(佳明/华米)在后台常驻拉取。

由 client.py 在健康助手启动时自动拉起(也可手动 `python -m sensors.run_all`)。
设计:
  · 单例端口锁(GUARD_PORT): 已在运行则直接退出, 避免客户端重启造成重复拉取进程。
  · 仅启用"已就绪"的源: 佳明需 token 缓存 ~/.garminconnect; 华米需 amazfit.json 凭据。
  · 每个源跑在 daemon 线程里(各自 run_loop 按自身 interval 低频拉, 失败优雅离线)。
  · 任一源不可用/崩溃都不影响其它源, 也不影响主程序。
"""
import os
import socket
import threading

# 穿戴源(尤其中国区佳明 garmin.cn)流量必须绕过本机 SSH 隧道代理。
for _v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
           "ALL_PROXY", "all_proxy"):
    os.environ.pop(_v, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

GUARD_PORT = 50574   # 单例锁端口(与桌宠 50573 错开)
_HOME = os.path.expanduser("~")
GARMIN_TOKEN = os.path.join(_HOME, ".garminconnect")
AMAZFIT_CFG = os.path.join(_HOME, ".claude", "health_inputs", "amazfit.json")


def _acquire_guard():
    """绑定本地守护端口当单例锁; 已被占用 -> 已有实例在跑, 返回 None。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", GUARD_PORT))
        s.listen(1)
        return s   # 持有引用 = 持有锁(进程存活期间不释放)
    except OSError:
        s.close()
        return None


def _enabled_sources():
    srcs = []
    if os.path.exists(GARMIN_TOKEN):
        from sensors.garmin_source import GarminSource
        srcs.append(GarminSource())
    if os.path.exists(AMAZFIT_CFG):
        from sensors.amazfit_source import AmazfitSource
        srcs.append(AmazfitSource())
    return srcs


def main():
    guard = _acquire_guard()
    if guard is None:
        print("[run_all] 已有穿戴源守护在运行, 退出。")
        return
    sources = _enabled_sources()
    if not sources:
        print("[run_all] 暂无已就绪的穿戴源(佳明未登录 / 华米未配置), 退出。")
        return
    names = ", ".join(s.name for s in sources)
    print("[run_all] 穿戴源守护启动: {}".format(names))
    threads = []
    for src in sources:
        t = threading.Thread(target=src.run_loop, name=src.name, daemon=True)
        t.start()
        threads.append(t)
    # 主线程驻留(daemon 线程随进程退出)。
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
