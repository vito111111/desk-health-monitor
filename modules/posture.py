# -*- coding: utf-8 -*-
"""坐姿分析（精准版）+ 久坐提醒。

MediaPipe Pose 取头肩关键点，计算多个**尺度/旋转稳健**的指标，
经 EMA 平滑 + 迟滞双阈值 + 持续时间确认后，识别典型坐姿问题：
  · 驼背/含胸(forward_head)  —— 颈部纵向缩短 或 头相对肩明显前探变大
  · 高低肩(high_shoulder)    —— 两肩连线相对自身基线倾斜
  · 歪头(head_tilted)        —— 两耳连线倾斜
  · 身体偏移(body_leaned)    —— 头相对肩中线左右偏

相比旧版单指标单阈值：加了对称性指标、平滑、迟滞、持续时间与可见度门控，
基线由"端正坐姿"校准得到(可随时重设)。Pose 较重，由 monitor 节流调用(~3fps)。
"""
import math
from collections import deque

from .vision import PoseLandmarkerWrap

NOSE, L_EAR, R_EAR, L_SH, R_SH = 0, 7, 8, 11, 12


def _ema(prev, x, a):
    return x if prev is None else (1 - a) * prev + a * x


class _Flag:
    """带"进入/退出需各自持续 N 秒"的迟滞状态机，消除抖动。"""

    def __init__(self, enter_hold, exit_hold):
        self.state = False
        self.enter_hold = enter_hold
        self.exit_hold = exit_hold
        self._t_enter = None
        self._t_clear = None

    def update(self, enter_cond, clear_cond, now):
        if not self.state:
            if enter_cond:
                self._t_enter = self._t_enter or now
                if now - self._t_enter >= self.enter_hold:
                    self.state = True
                    self._t_clear = None
            else:
                self._t_enter = None
        else:
            if clear_cond:
                self._t_clear = self._t_clear or now
                if now - self._t_clear >= self.exit_hold:
                    self.state = False
                    self._t_enter = None
            else:
                self._t_clear = None
        return self.state

    def reset(self):
        self.state = False
        self._t_enter = self._t_clear = None


class PostureAnalyzer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.pose = PoseLandmarkerWrap()
        p = cfg.get("posture", {})
        self.p = p
        self.calib_frames = p.get("calib_frames", 25)
        self.alpha = p.get("smooth_alpha", 0.35)
        self.min_vis = p.get("min_visibility", 0.6)
        self.enter_hold = p.get("enter_hold_sec", 2.5)
        self.exit_hold = p.get("exit_hold_sec", 2.0)
        # 阈值
        self.neck_drop_enter = p.get("neck_drop_enter", cfg.get("slouch_drop_ratio", 0.16))
        self.neck_drop_exit = p.get("neck_drop_exit", 0.10)
        self.fwd_rise_enter = p.get("fwd_rise_enter", 0.16)
        self.fwd_rise_exit = p.get("fwd_rise_exit", 0.10)
        self.tilt_enter_deg = p.get("shoulder_tilt_deg", 6.0)
        self.tilt_exit_deg = p.get("shoulder_tilt_exit_deg", 3.5)
        self.head_tilt_deg = p.get("head_tilt_deg", 9.0)
        self.lean_enter = p.get("body_lean_ratio", 0.16)

        # 基线(端正坐姿校准得到)
        self.base = None
        self._calib = {k: deque(maxlen=self.calib_frames)
                       for k in ("neck", "fwd", "tilt", "htilt", "lean")}
        # 平滑值
        self._s = {k: None for k in ("neck", "fwd", "tilt", "htilt", "lean")}
        # 迟滞标志
        self.f_fwd = _Flag(self.enter_hold, self.exit_hold)
        self.f_high = _Flag(self.enter_hold, self.exit_hold)
        self.f_htilt = _Flag(self.enter_hold, self.exit_hold)
        self.f_lean = _Flag(self.enter_hold, self.exit_hold)

        self.seated_since = None
        self.last_move_ts = None
        self.metrics = self._blank_metrics()

    @staticmethod
    def _blank_metrics():
        return {"pose_ok": False, "calibrating": False,
                "slouch": False, "forward_head": False, "high_shoulder": False,
                "head_tilted": False, "body_leaned": False, "high_side": "",
                "issues": [], "shoulder_tilt_deg": 0.0, "head_tilt_deg": 0.0,
                "neck_ratio": 0.0, "fwd_ratio": 0.0, "body_lean_val": 0.0,
                "need_move": False, "seated_minutes": 0.0}

    # ---------------- 原始指标(尺度/旋转稳健) ----------------
    def _raw(self, lm):
        lsh, rsh = lm[L_SH], lm[R_SH]
        lear, rear, nose = lm[L_EAR], lm[R_EAR], lm[NOSE]
        sw = math.hypot(lsh.x - rsh.x, lsh.y - rsh.y) + 1e-6
        mid_sh_x = (lsh.x + rsh.x) / 2.0
        mid_sh_y = (lsh.y + rsh.y) / 2.0
        mid_ear_x = (lear.x + rear.x) / 2.0
        mid_ear_y = (lear.y + rear.y) / 2.0
        ear_w = math.hypot(lear.x - rear.x, lear.y - rear.y)
        return {
            # 颈部纵向长度/肩宽：驼背前倾会变小
            "neck": (mid_sh_y - mid_ear_y) / sw,
            # 头宽/肩宽：探头前倾(头更近相机)会变大
            "fwd": ear_w / sw,
            # 肩线相对水平的倾角(度)：高低肩
            "tilt": math.degrees(math.atan2(rsh.y - lsh.y, rsh.x - lsh.x)),
            # 耳线倾角(度)：歪头
            "htilt": math.degrees(math.atan2(rear.y - lear.y, rear.x - lear.x)),
            # 头相对肩中线左右偏移/肩宽：身体偏移
            "lean": (mid_ear_x - mid_sh_x) / sw,
            # 朝向校验：转身时一耳遮挡, ear_w/sw 异常小
            "_facing": ear_w / sw,
        }

    def update(self, rgb, now, on_screen, ts_ms):
        cfg = self.cfg
        m = self.metrics
        lm = self.pose.detect(rgb, ts_ms)

        ok = False
        if lm:
            vis = min(lm[L_SH].visibility, lm[R_SH].visibility,
                      lm[L_EAR].visibility, lm[R_EAR].visibility)
            raw = self._raw(lm)
            # 朝向门控：明显转身(双耳过近)时不评判，保持上次状态
            facing_ok = raw["_facing"] > 0.18
            if vis >= self.min_vis and facing_ok:
                ok = True
                a = self.alpha
                for k in ("neck", "fwd", "tilt", "htilt", "lean"):
                    self._s[k] = _ema(self._s[k], raw[k], a)
                self._judge(now)
            # 可见度/朝向不足：不更新标志(维持迟滞状态)，但标记 pose_ok=False

        m["pose_ok"] = ok
        m["calibrating"] = ok and self.base is None
        if ok:
            m["shoulder_tilt_deg"] = round(self._s["tilt"] -
                                           (self.base["tilt"] if self.base else 0), 1)
            m["head_tilt_deg"] = round(self._s["htilt"] -
                                       (self.base["htilt"] if self.base else 0), 1)
            m["neck_ratio"] = round(self._s["neck"], 3)
            m["fwd_ratio"] = round(self._s["fwd"], 3)
            m["body_lean_val"] = round(self._s["lean"] -
                                       (self.base["lean"] if self.base else 0), 3)

        # 久坐计时
        if on_screen:
            if self.seated_since is None:
                self.seated_since = now
        else:
            self.seated_since = None
            self.last_move_ts = now
        seated_min = (now - self.seated_since) / 60.0 if self.seated_since else 0.0
        m["seated_minutes"] = round(seated_min, 1)
        m["need_move"] = seated_min >= cfg["sedentary_minutes"]
        return m

    def _judge(self, now):
        m = self.metrics
        s = self._s
        # 基线未就绪：收集端正坐姿样本
        if self.base is None:
            for k in ("neck", "fwd", "tilt", "htilt", "lean"):
                self._calib[k].append(s[k])
            if len(self._calib["neck"]) >= self.calib_frames:
                self.base = {k: sorted(self._calib[k])[len(self._calib[k]) // 2]
                             for k in self._calib}
            # 校准中不下判断
            for f in (self.f_fwd, self.f_high, self.f_htilt, self.f_lean):
                f.reset()
            self._set_issue_flags()
            return

        b = self.base
        # 驼背/含胸：颈缩短 或 头前探变大
        neck_lo_enter = b["neck"] * (1 - self.neck_drop_enter)
        neck_lo_clear = b["neck"] * (1 - self.neck_drop_exit)
        fwd_hi_enter = b["fwd"] * (1 + self.fwd_rise_enter)
        fwd_hi_clear = b["fwd"] * (1 + self.fwd_rise_exit)
        fwd_enter = (s["neck"] < neck_lo_enter) or (s["fwd"] > fwd_hi_enter)
        fwd_clear = (s["neck"] > neck_lo_clear) and (s["fwd"] < fwd_hi_clear)
        self.f_fwd.update(fwd_enter, fwd_clear, now)

        # 高低肩：肩线倾角相对基线偏移
        tilt_dev = abs(s["tilt"] - b["tilt"])
        self.f_high.update(tilt_dev > self.tilt_enter_deg,
                           tilt_dev < self.tilt_exit_deg, now)
        m["high_side"] = "" if not self.f_high.state else (
            "L" if (s["tilt"] - b["tilt"]) < 0 else "R")

        # 歪头：耳线倾角
        ht_dev = abs(s["htilt"] - b["htilt"])
        self.f_htilt.update(ht_dev > self.head_tilt_deg,
                            ht_dev < self.head_tilt_deg * 0.6, now)

        # 身体偏移
        lean_dev = abs(s["lean"] - b["lean"])
        self.f_lean.update(lean_dev > self.lean_enter,
                           lean_dev < self.lean_enter * 0.6, now)

        self._set_issue_flags()

    def _set_issue_flags(self):
        m = self.metrics
        m["forward_head"] = self.f_fwd.state
        m["slouch"] = self.f_fwd.state          # 兼容旧链路(提醒/宠物)
        m["high_shoulder"] = self.f_high.state
        m["head_tilted"] = self.f_htilt.state
        m["body_leaned"] = self.f_lean.state
        issues = []
        if self.f_fwd.state:
            issues.append("驼背/含胸")
        if self.f_high.state:
            issues.append("高低肩")
        if self.f_htilt.state:
            issues.append("歪头")
        if self.f_lean.state:
            issues.append("身体偏移")
        m["issues"] = issues

    def took_break(self, now):
        self.seated_since = now

    def recalibrate(self):
        self.base = None
        for d in self._calib.values():
            d.clear()
        for k in self._s:
            self._s[k] = None
        for f in (self.f_fwd, self.f_high, self.f_htilt, self.f_lean):
            f.reset()
        self.metrics = self._blank_metrics()

    def close(self):
        self.pose.close()
