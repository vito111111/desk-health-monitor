# -*- coding: utf-8 -*-
"""在场感知：离开座位超时 -> 自动锁屏(防窥/省电)。
   出于安全，自动锁屏默认关闭(config.auto_lock=false)，仅在用户显式开启时生效。"""
import ctypes


class PresenceController:
    def __init__(self, cfg):
        self.cfg = cfg
        self.away_since = None
        self.locked = False
        self.metrics = {"away_seconds": 0.0, "auto_lock": cfg.get("auto_lock", False),
                        "locked_action": False}

    def update(self, now, face_present):
        cfg = self.cfg
        if face_present:
            self.away_since = None
            self.locked = False
            self.metrics.update({"away_seconds": 0.0, "locked_action": False})
            return self.metrics

        if self.away_since is None:
            self.away_since = now
        away = now - self.away_since
        self.metrics["away_seconds"] = round(away, 1)

        if cfg.get("auto_lock", False) and not self.locked and away >= cfg["auto_lock_seconds"]:
            self._lock_screen()
            self.locked = True
            self.metrics["locked_action"] = True
        return self.metrics

    def _lock_screen(self):
        try:
            ctypes.windll.user32.LockWorkStation()
        except Exception:
            pass
