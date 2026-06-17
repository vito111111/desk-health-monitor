# -*- coding: utf-8 -*-
"""用眼健康：屏幕距离过近(防近视)、20-20-20 护眼、眨眼过少(干眼)。"""
from collections import deque

from .geom import dist, EYE_OUTER_L, EYE_OUTER_R


class EyeCareAnalyzer:
    def __init__(self, cfg):
        self.cfg = cfg
        # 距离基线：用双眼外角像素间距代表远近(越大越近)。启动时校准。
        self.baseline_eye_px = None
        self._calib = deque(maxlen=60)
        self.continuous_screen_since = None      # 连续注视屏幕起点(20-20-20)
        self.last_break_ts = None
        self.low_blink_since = None
        self.metrics = {"eye_px": 0.0, "distance_ratio": 1.0, "est_cm": 0,
                        "too_close": False, "need_eye_break": False,
                        "dry_eye": False, "screen_minutes": 0.0}

    def calibrate(self, eye_px):
        """采集前若干帧作为'舒适距离'基线。"""
        self._calib.append(eye_px)
        if len(self._calib) >= 30:
            self.baseline_eye_px = sorted(self._calib)[len(self._calib) // 2]  # 中位数

    def update(self, pts, now, on_screen, blink_rate):
        cfg = self.cfg
        eye_px = dist(pts[EYE_OUTER_L], pts[EYE_OUTER_R])
        if self.baseline_eye_px is None:
            self.calibrate(eye_px)
            ratio = 1.0
        else:
            ratio = eye_px / self.baseline_eye_px if self.baseline_eye_px else 1.0

        # 粗略 cm：假设基线对应舒适距离 cfg['comfort_distance_cm']
        est_cm = cfg["comfort_distance_cm"] / ratio if ratio > 0 else cfg["comfort_distance_cm"]
        too_close = est_cm < cfg["min_distance_cm"]

        # 20-20-20：连续注视屏幕计时
        if on_screen:
            if self.continuous_screen_since is None:
                self.continuous_screen_since = now
        else:
            # 离屏(离岗或长时间分心)即视为休息，重置
            self.continuous_screen_since = None
            self.last_break_ts = now
        screen_minutes = (now - self.continuous_screen_since) / 60.0 if self.continuous_screen_since else 0.0
        need_eye_break = screen_minutes >= cfg["eye_break_minutes"]

        # 干眼：眨眼率持续偏低
        if blink_rate < cfg["dry_eye_blink_rate"]:
            if self.low_blink_since is None:
                self.low_blink_since = now
        else:
            self.low_blink_since = None
        dry_eye = self.low_blink_since is not None and now - self.low_blink_since >= cfg["dry_eye_seconds"]

        self.metrics.update({"eye_px": eye_px, "distance_ratio": ratio, "est_cm": round(est_cm),
                             "too_close": too_close, "need_eye_break": need_eye_break,
                             "dry_eye": dry_eye, "screen_minutes": round(screen_minutes, 1)})
        return self.metrics

    def took_break(self, now):
        self.continuous_screen_since = now  # 用户确认休息后重新计时
