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
        # 持续确认：问题须连续存在 sustain 秒才值得打断，过滤瞬时/轻微波动(如轻微高低肩)
        self.sustain = cfg.get("reminder_sustain_seconds", {})
        self.default_sustain = cfg.get("reminder_default_sustain", 5)
        self.last_fired = {}
        self.on_since = {}  # type -> 本轮连续为真的起始时刻
        self.active = {}  # type -> {title, body, ts}

    def evaluate(self, conditions, now):
        """conditions: {type: bool}; 返回本次新触发的提醒列表。
        仅当某问题连续存在达到 sustain 秒、且距上次提醒超过冷却时才触发，避免刷屏。"""
        fired = []
        for typ, on in conditions.items():
            if on:
                # 记录连续为真的起点；持续不够久则不打断
                self.on_since.setdefault(typ, now)
                sustain = self.sustain.get(typ, self.default_sustain)
                if now - self.on_since[typ] < sustain:
                    continue
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
                # 问题消失：清除连续计时，下次须重新连续累计
                self.on_since.pop(typ, None)
                self.active.pop(typ, None)
        return fired

    def current(self):
        return list(self.active.values())

    def _beep(self):
        try:
            ctypes.windll.user32.MessageBeep(0x40)  # MB_ICONASTERISK
        except Exception:
            pass
