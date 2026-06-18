# -*- coding: utf-8 -*-
"""穿戴设备源公共层。

各品牌源(garmin / amazfit / watch_stub)只需实现 fetch(now) -> {sleep_min?, resting_hr?, steps?}
或 None, 共用本层把指标归一化为统一因素。新增一个品牌 = 加一个 fetch, 映射零重复。
"""
from sensors.base import HealthSource

SLEEP_DEBT_MIN = 360     # 夜间睡眠 < 6h 视为睡眠不足 -> sleep_debt
LOW_STEPS = 1500         # 当日步数过低 -> need_move(与摄像头同名因素, 聚合端自动去重)


def derive_factors(metrics):
    factors = []
    s = metrics.get("sleep_min")
    if isinstance(s, (int, float)) and 0 < s < SLEEP_DEBT_MIN:
        factors.append("sleep_debt")
    st = metrics.get("steps")
    if isinstance(st, (int, float)) and st < LOW_STEPS:
        factors.append("need_move")
    return factors


class WearableSource(HealthSource):
    """穿戴源基类: 低频拉云端日汇总。子类实现 fetch(), 失败/无数据返回 None -> 该源离线。"""
    interval = 1800.0   # 默认 30 min 拉一次(手表数据本就低频, 6h 内有效)

    def fetch(self, now):
        raise NotImplementedError

    def poll(self, now):
        try:
            metrics = self.fetch(now)
        except Exception as e:
            print("[{}] 拉取失败(忽略, 源转离线): {}".format(self.name, e))
            return None
        if not metrics:
            return None
        return {"factors": derive_factors(metrics), "metrics": metrics}
