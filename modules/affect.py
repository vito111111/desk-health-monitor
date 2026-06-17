# -*- coding: utf-8 -*-
"""情绪/紧张度趋势。基于 MediaPipe FaceLandmarker 的 52 维表情系数(blendshapes)，
聚合出"紧张度"(皱眉/眯眼/抿嘴/下压)与"正向情绪"(微笑) 两个 0-100 指标，EMA 平滑。
纯本地，不保存任何图像；只产出标量指标用于长期趋势。"""


def _ema(prev, x, a):
    return x if prev is None else (1 - a) * prev + a * x


class AffectAnalyzer:
    def __init__(self, cfg):
        a = cfg.get("affect", {})
        self.alpha = a.get("smooth_alpha", 0.08)
        self.tension = None
        self.positive = None
        self.metrics = {"tension": 0, "positive": 0, "valid": False}

    def update(self, blendshapes):
        if not blendshapes:
            return self.metrics
        d = {b.category_name: b.score for b in blendshapes}

        def avg(*names):
            vals = [d.get(n, 0.0) for n in names]
            return sum(vals) / len(vals) if vals else 0.0

        brow = avg("browDownLeft", "browDownRight")          # 皱眉
        squint = avg("eyeSquintLeft", "eyeSquintRight")      # 眯眼
        press = avg("mouthPressLeft", "mouthPressRight")     # 抿嘴
        frown = avg("mouthFrownLeft", "mouthFrownRight")     # 嘴角下拉
        raw_t = min(1.0, 0.42 * brow + 0.22 * squint + 0.21 * press + 0.15 * frown)
        smile = avg("mouthSmileLeft", "mouthSmileRight")

        self.tension = _ema(self.tension, raw_t, self.alpha)
        self.positive = _ema(self.positive, smile, self.alpha)
        self.metrics = {"tension": round(self.tension * 100),
                        "positive": round(self.positive * 100),
                        "valid": True}
        return self.metrics

    def reset(self):
        self.metrics = {"tension": self.metrics["tension"],
                        "positive": self.metrics["positive"], "valid": False}
