# -*- coding: utf-8 -*-
"""疲劳分析：EAR 长闭眼、PERCLOS、打哈欠 (MAR)。服务对象=使用者本人。"""
import time
from collections import deque

from .geom import eye_aspect_ratio, mouth_aspect_ratio, LEFT_EYE, RIGHT_EYE


class FatigueAnalyzer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.eyes_closed_since = None
        self.yawn_since = None
        self.blink_in_progress = False
        self.blink_times = deque()
        self.closed_samples = deque()
        self.metrics = {"ear": 0.0, "mar": 0.0, "blink_rate": 0.0,
                        "perclos": 0.0, "drowsy": False, "yawning": False}

    def update(self, pts, now):
        cfg = self.cfg
        ear = (eye_aspect_ratio(pts, LEFT_EYE) + eye_aspect_ratio(pts, RIGHT_EYE)) / 2.0
        mar = mouth_aspect_ratio(pts)
        closed = ear < cfg["ear_closed_threshold"]

        # PERCLOS
        win = cfg["perclos_window_seconds"]
        self.closed_samples.append((now, 1 if closed else 0))
        while self.closed_samples and now - self.closed_samples[0][0] > win:
            self.closed_samples.popleft()
        perclos = sum(c for _, c in self.closed_samples) / len(self.closed_samples) if self.closed_samples else 0.0

        # 闭眼计时 + 眨眼
        if closed:
            if self.eyes_closed_since is None:
                self.eyes_closed_since = now
            self.blink_in_progress = True
        else:
            if self.blink_in_progress and self.eyes_closed_since is not None:
                d = now - self.eyes_closed_since
                if cfg["blink_min_seconds"] <= d < cfg["drowsy_closed_seconds"]:
                    self.blink_times.append(now)
            self.eyes_closed_since = None
            self.blink_in_progress = False
        while self.blink_times and now - self.blink_times[0] > 60:
            self.blink_times.popleft()
        blink_rate = float(len(self.blink_times))

        # 打哈欠
        if mar >= cfg["mar_yawn_threshold"]:
            if self.yawn_since is None:
                self.yawn_since = now
        else:
            self.yawn_since = None
        yawning = self.yawn_since is not None and now - self.yawn_since >= cfg["yawn_min_seconds"]

        long_close = (self.eyes_closed_since is not None
                      and now - self.eyes_closed_since >= cfg["drowsy_closed_seconds"])
        drowsy = long_close or perclos >= cfg["perclos_drowsy_ratio"] or yawning

        self.metrics.update({"ear": ear, "mar": mar, "blink_rate": blink_rate,
                             "perclos": perclos, "drowsy": drowsy, "yawning": yawning})
        return self.metrics

    def reset_transient(self):
        self.eyes_closed_since = None
        self.yawn_since = None
        self.blink_in_progress = False
