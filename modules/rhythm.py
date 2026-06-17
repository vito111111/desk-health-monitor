# -*- coding: utf-8 -*-
"""智能节律 + 勿扰/会议模式。

解决"被提醒打扰"这一长期使用最大痛点：
  · 会议/通话感知：根据嘴部开合频率判断正在说话 -> 自动进入会议模式静音提醒；
  · 勿扰(手动) + 安静时段(配置时间段) -> 抑制提醒；
  · 自然停顿投递：久坐/护眼这类"休息类"提醒延到你抬头/离屏的自然停顿再弹，
    避免打断心流；超过 max_defer 兜底投递；
  · 休息依从率：记录建议起身次数 vs 实际起身次数。
纯本地，无图像留存。"""
import datetime
from collections import deque


class RhythmController:
    def __init__(self, cfg):
        r = cfg.get("rhythm", {})
        self.mar_open = r.get("talk_mar", 0.42)
        self.talk_min_openings = r.get("talk_min_openings", 5)
        self.talk_window = r.get("talk_window_sec", 12)
        self.talk_release = r.get("talk_release_sec", 6)
        self.defer_types = set(r.get("defer_types", ["need_move", "need_eye_break"]))
        self.max_defer = r.get("max_defer_sec", 150)
        self.quiet = r.get("quiet_hours", [])      # 例：["22:30-08:00"]
        self.dnd = bool(r.get("dnd", False))

        self._mar_open_prev = False
        self._open_times = deque()
        self._last_talk = None
        self._pending = {}                          # type -> 首次待投递 ts
        self.suggested = 0
        self.taken = 0
        self.metrics = {"meeting": False, "dnd": self.dnd, "quiet": False,
                        "suppressed": False, "breaks_suggested": 0, "breaks_taken": 0}

    # -- 手动勿扰开关(供看板) --
    def set_dnd(self, on):
        self.dnd = bool(on)

    # -- 依从率(由 monitor 调) --
    def note_suggested(self):
        self.suggested += 1

    def note_taken(self):
        self.taken += 1

    def _quiet_now(self, now):
        if not self.quiet:
            return False
        t = datetime.datetime.fromtimestamp(now).time()
        for span in self.quiet:
            try:
                a, b = span.split("-")
                ah, am = (int(x) for x in a.split(":"))
                bh, bm = (int(x) for x in b.split(":"))
            except (ValueError, AttributeError):
                continue
            start, end = datetime.time(ah, am), datetime.time(bh, bm)
            if start <= end:
                if start <= t < end:
                    return True
            else:                                   # 跨夜
                if t >= start or t < end:
                    return True
        return False

    def _update_talk(self, now, present, mar):
        if present and mar is not None:
            opened = mar >= self.mar_open
            if opened and not self._mar_open_prev:
                self._open_times.append(now)
            self._mar_open_prev = opened
        while self._open_times and now - self._open_times[0] > self.talk_window:
            self._open_times.popleft()
        if len(self._open_times) >= self.talk_min_openings:
            self._last_talk = now
        return self._last_talk is not None and now - self._last_talk <= self.talk_release

    def update(self, now, present, mar):
        meeting = self._update_talk(now, present, mar)
        quiet = self._quiet_now(now)
        suppressed = meeting or self.dnd or quiet
        self.metrics = {"meeting": meeting, "dnd": self.dnd, "quiet": quiet,
                        "suppressed": suppressed,
                        "breaks_suggested": self.suggested,
                        "breaks_taken": self.taken,
                        "adherence": (round(self.taken / self.suggested * 100)
                                      if self.suggested else None)}
        return self.metrics

    def gate(self, conds, now, natural_pause):
        """过滤提醒条件：会议/勿扰/安静全抑制；休息类延到自然停顿或兜底超时。"""
        if self.metrics.get("suppressed"):
            self._pending.clear()
            return {k: False for k in conds}
        out = {}
        for k, v in conds.items():
            if v and k in self.defer_types:
                self._pending.setdefault(k, now)
                if natural_pause or now - self._pending[k] >= self.max_defer:
                    out[k] = True
                    self._pending.pop(k, None)
                else:
                    out[k] = False
            else:
                if not v:
                    self._pending.pop(k, None)
                out[k] = v
        return out
