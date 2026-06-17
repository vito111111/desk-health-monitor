# -*- coding: utf-8 -*-
"""把健康监测状态桥接给桌面宠物(claude-pet)。

通过写本地文件 ~/.claude/pet_health.json 通信：
  · factors  —— 当前活跃的不健康因素(驱动宠物造型/颜色变化, 持续反映)
  · event    —— 新触发的一条健康建议(驱动宠物 10s 弹窗; 久坐/驼背附带体操引导)

纯本地文件通信，不联网、不调用任何大模型。宠物未运行时也无副作用。
"""
import os
import json
import time
import tempfile

HEALTH_FILE = os.path.join(os.path.expanduser("~"), ".claude", "pet_health.json")

# 因素 -> 严重度(取最高者决定宠物整体颜色)
_SEVERITY = {
    "drowsy": "alert", "high_stress": "alert",
    "too_close": "warn", "slouch": "warn", "high_shoulder": "warn",
    "need_move": "warn", "need_eye_break": "warn", "dry_eye": "warn",
    "dark_env": "warn",
}

# 建议事件文案(纯规则离线)。routine 非空 = 点击确认后引导做该套体操。
ADVICE = {
    "need_move":      ("起身活动一下", "已经久坐很久啦，站起来走两步、舒展筋骨～", "full"),
    "slouch":         ("挺直腰背",     "驼背含胸了，沉肩收下巴，跟我做组放松操～", "neck_shoulder"),
    "high_shoulder":  ("两肩拉平",     "高低肩了，放松较高一侧，跟我做组颈肩操～", "neck_shoulder"),
    "need_eye_break": ("让眼睛歇会儿", "盯屏幕 20 分钟了，远眺窗外 20 秒放松一下", None),
    "dry_eye":        ("多眨眨眼",     "眨眼变少了，主动眨几次、再喝口水更舒服～", None),
    "too_close":      ("离屏幕远一点", "脸离屏幕太近啦，往后靠到约一臂的距离～",   None),
    "drowsy":         ("有点累了吧",   "看起来犯困了，起来接杯水、深呼吸提提神～", None),
    "high_stress":    ("放松一下",     "状态有点紧绷，跟我做几次深呼吸放松下～",   "breathe"),
    "dark_env":       ("开个灯吧",     "环境偏暗，开灯或调亮屏幕，别让眼睛硬扛～", None),
}

# 多个因素同时触发时, 选优先级最高的一个作为弹窗事件
_PRIORITY = ["need_move", "slouch", "high_shoulder", "drowsy", "high_stress",
             "too_close", "need_eye_break", "dry_eye", "dark_env"]


class PetBridge:
    def __init__(self, cfg):
        self.enabled = cfg.get("pet_integration", True)
        self._event_id = 0
        self._last_event = None
        self._last_factors = None
        self._last_write = 0.0
        try:
            os.makedirs(os.path.dirname(HEALTH_FILE), exist_ok=True)
        except OSError:
            self.enabled = False

    def _atomic_write(self, data):
        d = os.path.dirname(HEALTH_FILE)
        try:
            fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        except OSError:
            return
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, HEALTH_FILE)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass

    @staticmethod
    def _severity(factors):
        if any(_SEVERITY.get(f) == "alert" for f in factors):
            return "alert"
        return "warn" if factors else "ok"

    @staticmethod
    def pick_event(fired_types):
        """从本轮新触发的提醒类型里挑优先级最高的一条。"""
        cand = [t for t in fired_types if t in ADVICE]
        if not cand:
            return None
        return sorted(cand, key=lambda t: _PRIORITY.index(t)
                      if t in _PRIORITY else 99)[0]

    def update(self, present, factors, event=None, force=False):
        """每个监测周期调用。
        factors: 当前活跃不健康因素列表; event: 本轮新触发的建议类型(可 None)。"""
        if not self.enabled:
            return
        now = time.time()
        new_event = False
        if event and event in ADVICE:
            self._event_id += 1
            title, body, routine = ADVICE[event]
            self._last_event = {"id": self._event_id, "type": event,
                                "title": title, "body": body, "routine": routine}
            new_event = True

        if not (new_event or force or factors != self._last_factors
                or now - self._last_write > 2.0):
            return

        payload = {"ts": now, "present": bool(present),
                   "factors": list(factors), "severity": self._severity(factors)}
        if self._last_event:
            payload["event"] = self._last_event
        self._atomic_write(payload)
        self._last_write = now
        self._last_factors = list(factors)
