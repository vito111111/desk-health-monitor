# -*- coding: utf-8 -*-
"""关怀提醒管理：按类型冷却节流，避免刷屏。提醒都面向使用者本人。"""
import ctypes

REMINDER_TEXT = {
    "drowsy": ("😴 你看起来有些疲劳", "起身活动一下，或闭眼休息片刻"),
    "slouch": ("🪑 坐姿提醒（驼背/含胸）", "背部挺直，沉肩、收下巴，头部回正"),
    "high_shoulder": ("⚖ 高低肩提醒", "两肩不等高，放松较高一侧、双肩下沉拉平"),
    "need_move": ("🚶 久坐提醒", "已连续久坐，建议起身走动、伸展一下"),
    "need_eye_break": ("👀 该护眼了 (20-20-20)", "看向 6 米外远处放松 20 秒"),
    "dry_eye": ("💧 眨眼提醒", "眨眼频率偏低，主动多眨眼缓解干涩"),
    "too_close": ("📏 离屏幕太近了", "请坐远一点，保护视力"),
    "high_stress": ("🌿 放松一下", "心率偏高，深呼吸几次，舒缓压力"),
    "dark_env": ("💡 光线偏暗", "环境太暗易加重眼疲劳，开个灯或调亮环境"),
}


class ReminderManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.cooldowns = cfg.get("reminder_cooldowns", {})
        self.default_cd = cfg.get("reminder_default_cooldown", 120)
        self.last_fired = {}
        self.active = {}  # type -> {title, body, ts}

    def evaluate(self, conditions, now):
        """conditions: {type: bool}; 返回本次新触发的提醒列表。"""
        fired = []
        for typ, on in conditions.items():
            if on:
                cd = self.cooldowns.get(typ, self.default_cd)
                if now - self.last_fired.get(typ, -1e9) >= cd:
                    self.last_fired[typ] = now
                    title, body = REMINDER_TEXT.get(typ, (typ, ""))
                    rec = {"type": typ, "title": title, "body": body, "ts": now}
                    self.active[typ] = rec
                    fired.append(rec)
                    if self.cfg.get("sound_alert", True):
                        self._beep()
            else:
                self.active.pop(typ, None)
        return fired

    def current(self):
        return list(self.active.values())

    def _beep(self):
        try:
            ctypes.windll.user32.MessageBeep(0x40)  # MB_ICONASTERISK
        except Exception:
            pass
