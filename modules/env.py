# -*- coding: utf-8 -*-
"""环境光检测（护眼）。取摄像头画面平均亮度估计环境照度：
   暗光下盯屏是长期眼疲劳主因 -> 持续偏暗给"开灯"提醒；过亮(眩光)也提示。
   仅用一个标量(灰度均值)，零额外成本；不保存任何图像。"""


def _ema(prev, x, a):
    return x if prev is None else (1 - a) * prev + a * x


class EnvLightAnalyzer:
    def __init__(self, cfg):
        e = cfg.get("env", {})
        self.dark_lum = e.get("dark_lum", 55)      # 低于此(0-255)判偏暗
        self.bright_lum = e.get("bright_lum", 230)  # 高于此判过亮/眩光
        self.alpha = e.get("smooth_alpha", 0.05)
        self.hold = e.get("hold_sec", 12)          # 持续多久才确认
        self.lum = None
        self._dark_since = None
        self._bright_since = None
        self.metrics = {"lum": 0, "dark": False, "bright": False}

    def update(self, gray_mean, now):
        self.lum = _ema(self.lum, float(gray_mean), self.alpha)

        if self.lum < self.dark_lum:
            self._dark_since = self._dark_since or now
        else:
            self._dark_since = None
        if self.lum > self.bright_lum:
            self._bright_since = self._bright_since or now
        else:
            self._bright_since = None

        self.metrics = {
            "lum": round(self.lum, 1),
            "dark": bool(self._dark_since and now - self._dark_since >= self.hold),
            "bright": bool(self._bright_since and now - self._bright_since >= self.hold),
        }
        return self.metrics
