# -*- coding: utf-8 -*-
"""摄像头健康数据源 —— 把 worker-monitor 的实时判定写进统一健康状态契约。

它是众多传感器插件中的一个(source="camera"), 通过 health_state.SourceWriter 写
  ~/.claude/health/camera.json          —— 新: 多源聚合的脊柱
并同时写旧的 ~/.claude/pet_health.json  —— 向后兼容, 老版桌宠仍可用。

本文件只承载"摄像头源特有"的领域知识: 干预建议文案(ADVICE)与优先级。其余通用的
原子写入、多源聚合、严重度/元气值推导, 全部下沉到 health_state(双方共持的线协议)。
纯本地、不联网、不调用任何大模型。宠物未运行时也无副作用。
"""
import time

from health_state import SourceWriter, SEVERITY  # noqa: F401  (SEVERITY 供外部参考)

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
    """名称保留向后兼容(monitor.py 仍 `from pet_bridge import PetBridge`)。
    本质是 camera 数据源适配器: 被 monitor 主循环每帧推送, 不自轮询。"""

    def __init__(self, cfg):
        self.enabled = cfg.get("pet_integration", True)
        self._writer = SourceWriter("camera", also_legacy=True)
        self._last_factors = None
        self._last_write = 0.0

    @staticmethod
    def pick_event(fired_types):
        """从本轮新触发的提醒类型里挑优先级最高的一条。"""
        cand = [t for t in fired_types if t in ADVICE]
        if not cand:
            return None
        return sorted(cand, key=lambda t: _PRIORITY.index(t)
                      if t in _PRIORITY else 99)[0]

    def push_event(self, ev):
        """主动推送一条非周期事件(如健康干预 alert)到桌宠, 复用 camera 源的事件通道。
        ev: {type,title,body,routine}。沿用上次的 factors, 不改变健康因素本身。"""
        if not self.enabled or not ev:
            return
        self._writer.write(present=None, factors=list(self._last_factors or []),
                           event=ev)
        self._last_write = time.time()

    def update(self, present, factors, event=None, metrics=None, force=False):
        """每个监测周期调用。
        factors: 当前活跃不健康因素列表; event: 本轮新触发的建议类型(可 None);
        metrics: 摄像头侧原始指标(seated_minutes/screen_minutes/bpm/stress…), 进 sources.camera。"""
        if not self.enabled:
            return
        now = time.time()
        ev_payload = None
        if event and event in ADVICE:
            title, body, routine = ADVICE[event]
            ev_payload = {"type": event, "title": title,
                          "body": body, "routine": routine}

        # 节流: 仅在有新事件 / 因素变化 / 强制 / 超 2s 未写 时落盘(摄像头循环 ~10fps)
        if not (ev_payload or force or factors != self._last_factors
                or now - self._last_write > 2.0):
            return

        self._writer.write(present=present, factors=list(factors),
                           metrics=metrics, event=ev_payload)
        self._last_write = now
        self._last_factors = list(factors)
