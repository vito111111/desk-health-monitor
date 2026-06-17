# -*- coding: utf-8 -*-
"""rPPG 非接触生命体征(估算/参考)：额头肤色绿通道随心跳的微弱变化，
   去趋势 + 带通(0.7-4Hz) + FFT 取峰 -> 心率。压力指数基于心率相对个人基线的偏移。
   说明：消费级摄像头估算，仅供参考，非医疗用途。"""
import numpy as np
from collections import deque
from scipy.signal import butter, filtfilt, detrend

from .geom import FOREHEAD


class RppgAnalyzer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.buf = deque(maxlen=cfg["rppg_buffer"])   # (ts, green_mean)
        self.last_calc = 0.0
        self.resting_hr = None
        self.metrics = {"bpm": 0, "stress": 0, "quality": 0.0, "valid": False}

    def _roi_green(self, frame, pts):
        xs = [pts[i][0] for i in FOREHEAD]
        ys = [pts[i][1] for i in FOREHEAD]
        x1, x2 = int(min(xs)), int(max(xs))
        ytop = int(min(ys))
        # 额头：从额线往上取一条带
        y1 = max(0, ytop - int((x2 - x1) * 0.45))
        y2 = max(y1 + 1, ytop)
        x1 = max(0, x1); x2 = min(frame.shape[1], x2)
        if x2 <= x1 or y2 <= y1:
            return None
        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return None
        return float(roi[:, :, 1].mean())  # 绿通道

    def update(self, frame, pts, now):
        g = self._roi_green(frame, pts)
        if g is not None:
            self.buf.append((now, g))

        if now - self.last_calc < self.cfg["rppg_calc_interval"]:
            return self.metrics
        self.last_calc = now

        if len(self.buf) < self.cfg["rppg_min_samples"]:
            return self.metrics

        ts = np.array([t for t, _ in self.buf])
        sig = np.array([v for _, v in self.buf])
        dur = ts[-1] - ts[0]
        if dur <= 0:
            return self.metrics
        fs = len(ts) / dur
        if fs < 5:  # 帧率太低无法估算
            self.metrics["valid"] = False
            return self.metrics

        try:
            sig = detrend(sig)
            sig = (sig - sig.mean()) / (sig.std() + 1e-6)
            lo, hi = 0.7, 4.0  # 42-240 bpm
            b, a = butter(3, [lo / (fs / 2), hi / (fs / 2)], btype="band")
            filt = filtfilt(b, a, sig)
            # 频谱
            n = len(filt)
            freqs = np.fft.rfftfreq(n, d=1.0 / fs)
            spec = np.abs(np.fft.rfft(filt * np.hanning(n)))
            band = (freqs >= lo) & (freqs <= hi)
            if not band.any():
                return self.metrics
            peak_i = np.argmax(spec[band])
            peak_freq = freqs[band][peak_i]
            bpm = int(round(peak_freq * 60))
            # 信号质量：峰值能量占带内总能量比
            quality = float(spec[band][peak_i] / (spec[band].sum() + 1e-6))

            if 42 <= bpm <= 180 and quality > self.cfg["rppg_quality_min"]:
                if self.resting_hr is None:
                    self.resting_hr = bpm
                else:
                    # 缓慢更新静息基线(取较低值方向)
                    self.resting_hr = min(self.resting_hr, bpm) * 0.05 + self.resting_hr * 0.95
                # 压力指数：心率高于静息越多越高(0-100)
                excess = max(0.0, bpm - self.resting_hr)
                stress = int(min(100, excess / 0.4))
                self.metrics.update({"bpm": bpm, "stress": stress,
                                     "quality": round(quality, 2), "valid": True})
            else:
                self.metrics.update({"quality": round(quality, 2), "valid": False})
        except Exception:
            self.metrics["valid"] = False
        return self.metrics
