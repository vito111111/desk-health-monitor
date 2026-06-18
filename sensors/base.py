# -*- coding: utf-8 -*-
"""自运行型数据源插件基类。

子类只需声明 name/interval 并实现 poll(now) -> payload|None, 即可被纳入统一健康状态。
摄像头是被 monitor 主循环推送的, 直接用 health_state.SourceWriter, 不继承本类。
"""
import os
import sys
import time

# 允许 `python -m sensors.xxx` 直接定位到上级目录的 health_state
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from health_state import SourceWriter  # noqa: E402


class HealthSource:
    name = "source"
    interval = 30.0          # 自轮询间隔(秒); 低频源(手表)可设很大

    def __init__(self):
        self.writer = SourceWriter(self.name)

    def poll(self, now):
        """子类实现: 返回 dict(present?/factors?/metrics?/event?) 或 None(本轮无数据)。"""
        raise NotImplementedError

    def tick(self, now=None):
        now = now or time.time()
        payload = self.poll(now)
        if payload is None:
            return
        self.writer.write(present=payload.get("present"),
                          factors=payload.get("factors"),
                          metrics=payload.get("metrics"),
                          event=payload.get("event"))

    def run_loop(self):
        print("[{}] 数据源已启动, 每 {:.0f}s 写一次健康状态…".format(self.name, self.interval))
        while True:
            try:
                self.tick()
            except Exception as e:   # 单源故障不应拖垮系统
                print("[{}] poll 异常: {}".format(self.name, e))
            time.sleep(self.interval)
