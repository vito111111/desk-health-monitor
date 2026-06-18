# -*- coding: utf-8 -*-
"""Switch Joy-Con 体感源(骨架) —— 把"被验证的运动"接入统一健康状态。

定位: 它补上核心闭环里缺失的"干预真实完成"度量。绑在大腿上的 Joy-Con 用陀螺仪角度
数深蹲, 完成后上报为正向活动(metrics.squats / active), 并可触发庆祝事件。

【现状】这是骨架: 真正读 Joy-Con 需要
   pip install joycon-python hidapi pyglm
   且手柄已通过蓝牙与本机配对。未装库/未配对 -> fetch 返回 None, 源静默离线(同 garmin/amazfit)。
真机联调那一步需要硬件在场, 留作下一步; 接口与聚合链路已就位, 接上即生效, 不动渲染端。

【双角色】Joy-Con 不只是源, 也能当"执行器/渲染器": 读 read_state() 的 severity, 久坐时
   joycon.set_rumble(...) 发震动提醒; 那部分属渲染层, 不在本文件。

运行(有硬件时):  python -m sensors.controller_stub
"""
import time

from sensors.base import HealthSource

# 大腿上的 Joy-Con: 站立时手柄近垂直, 深蹲到底时近水平 -> direction[1] 越界即一次蹲起
_DOWN_ENTER = 0.7
_UP_EXIT = 0.2


class ControllerSource(HealthSource):
    name = "controller"
    interval = 0.05   # 体感要高频; 真机联调时用 run_loop 持续读

    def __init__(self):
        super().__init__()
        self._jc = None
        self._is_down = False
        self._squats = 0
        self._last_active = 0.0

    def _joycon(self):
        if self._jc is not None:
            return self._jc
        from pyjoycon import GyroTrackingJoyCon, get_L_id   # 没装库 -> 抛错 -> 源离线
        jid = get_L_id()
        if jid[0] is None:
            raise RuntimeError("未检测到 Joy-Con(L), 请确认蓝牙已配对")
        self._jc = GyroTrackingJoyCon(*jid)
        return self._jc

    def poll(self, now):
        try:
            jc = self._joycon()
        except Exception:
            return None   # 没装库/未配对 -> 源静默离线, 不影响系统
        thigh = jc.direction[1]   # 大腿角度分量
        if thigh > _DOWN_ENTER and not self._is_down:
            self._is_down = True
        elif thigh < _UP_EXIT and self._is_down:
            self._is_down = False
            self._squats += 1
            self._last_active = now
        active = (now - self._last_active) < 120   # 2 min 内有动作算"活动中"
        event = None
        if self._squats and self._squats % 10 == 0 and self._is_down is False:
            event = {"type": "exercise_done", "title": "做得好！",
                     "body": "完成 {} 个深蹲，元气回来啦～".format(self._squats),
                     "routine": None}
        # 体感是"正向活动"源: 不报不健康因素; 活动数据进 metrics, 供元气加成/周报
        return {"factors": [], "metrics": {"squats": self._squats,
                                           "active": bool(active)},
                "event": event}


if __name__ == "__main__":
    ControllerSource().run_loop()
