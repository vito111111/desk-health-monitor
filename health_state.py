# -*- coding: utf-8 -*-
"""health_state —— 桌前健康系统的统一状态契约 (single source of truth)。

产品脊柱(把零散脚本变成有脊柱的系统):
  · 传感器 = 插件: 每个数据源(摄像头/手表/手柄/体脂秤…)独立写自己的命名空间文件
        ~/.claude/health/<source>.json   —— 彼此不覆盖, 增删一个源不动其它任何代码。
  · 渲染器 = 读取方: 桌宠/语音/周报 等只读聚合后的统一状态, 不关心数据来自哪个源。
  · 热路径本地、确定性: 实时判定只用规则, 不在此层调用任何大模型。

本模块是「线协议」。worker-monitor(写) 与 claude-pet(读) 各自持有一份**完全相同**的副本,
必须保持一致; schema 版本号变更时双方同步升级。纯标准库, 不联网, 不依赖任一侧的业务代码。
"""
import os
import json
import time
import glob
import tempfile

SCHEMA = "health_state/2"

_HOME = os.path.expanduser("~")
HEALTH_DIR = os.path.join(_HOME, ".claude", "health")             # 新: 每源一文件
LEGACY_FILE = os.path.join(_HOME, ".claude", "pet_health.json")   # 旧: 单文件(向后兼容)

# 数据源新鲜度: 超过即视为离线。低频源(手表/体脂秤)允许更久不更新仍有效。
DEFAULT_STALE_SEC = 8.0
SOURCE_STALE_SEC = {
    "watch": 6 * 3600,        # 手表(睡眠/静息心率/步数)一天同步几次即可
    "garmin": 6 * 3600,       # 佳明: 源名即 garmin, 每 30min 拉一次, 6h 内有效
    "amazfit": 6 * 3600,      # 华米/Amazfit: 同上
    "scale": 7 * 24 * 3600,   # 体脂秤一周一次
}

# 因素 -> 严重度。聚合时取所有在线源里最高的一档(alert > warn > ok)。
SEVERITY = {
    # 摄像头源(worker-monitor)
    "drowsy": "alert", "high_stress": "alert",
    "too_close": "warn", "slouch": "warn", "high_shoulder": "warn",
    "need_move": "warn", "need_eye_break": "warn", "dry_eye": "warn",
    "dark_env": "warn",
    # 跨源新因素(手表/穿戴; 渐进增强, 渲染端有兜底, 缺省也不崩)
    "sleep_debt": "warn", "dehydrated": "warn", "overexerted": "alert",
}

# 由因素推导 0-100 的元气值(vitality): 每个活跃因素按严重度扣分。
_VITALITY_PENALTY = {"alert": 18, "warn": 8}


# --------------------------------------------------------------------- 写端
def _atomic_write(path, data):
    d = os.path.dirname(path)
    try:
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


class SourceWriter:
    """一个数据源(插件)用它把自己的状态写进统一状态目录, 不触碰其它源的文件。

    write() 约定字段(均可选, 缺省合理):
      present  bool|None  仅"在场感知类"源(摄像头)才声明; 非在场源传 None -> 不写该字段
      factors  list[str]  当前活跃的不健康因素
      metrics  dict        原始指标 (seated_minutes / resting_hr / sleep_min / steps …)
      event    dict|None   本轮新触发的干预建议 {type,title,body,routine}; id 由本类统一分配
    """

    def __init__(self, source, also_legacy=False):
        self.source = source
        self.also_legacy = also_legacy   # 摄像头源置 True: 同时写旧文件, 保证老版宠物可用
        self._event_seq = 0
        self._last_event = None

    def write(self, *, present=None, factors=None, metrics=None, event=None):
        factors = list(factors or [])
        now = time.time()
        if event:
            self._event_seq += 1
            ev = dict(event)
            ev["id"] = "{}:{}".format(self.source, self._event_seq)  # 全局唯一, 避免跨源撞 id
            self._last_event = ev

        rec = {"schema": SCHEMA, "source": self.source, "ts": now,
               "factors": factors, "metrics": dict(metrics or {})}
        if present is not None:
            rec["present"] = bool(present)
        if self._last_event:
            rec["event"] = self._last_event
        _atomic_write(os.path.join(HEALTH_DIR, self.source + ".json"), rec)

        if self.also_legacy:
            legacy = {"ts": now, "present": bool(present),
                      "factors": factors, "severity": severity_of(factors)}
            if self._last_event:
                legacy["event"] = self._last_event
            _atomic_write(LEGACY_FILE, legacy)


# --------------------------------------------------------------------- 聚合
def severity_of(factors):
    if any(SEVERITY.get(f) == "alert" for f in factors):
        return "alert"
    return "warn" if factors else "ok"


def vitality_of(factors):
    v = 100
    for f in set(factors):
        v -= _VITALITY_PENALTY.get(SEVERITY.get(f, "warn"), 8)
    return max(0, v)


def _stale(source, age):
    return age > SOURCE_STALE_SEC.get(source, DEFAULT_STALE_SEC)


def _load_sources():
    out = {}
    for path in glob.glob(os.path.join(HEALTH_DIR, "*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        src = rec.get("source") or os.path.splitext(os.path.basename(path))[0]
        out[src] = rec
    return out


def read_state(now=None):
    """聚合所有"在线"源 -> 统一健康状态(含 factors/severity/vitality/event/sources)。

    全部源离线时回退读旧单文件(向后兼容); 仍无 -> 返回 None(渲染端按"全健康"处理)。
    """
    now = now or time.time()
    online = {}
    for src, rec in _load_sources().items():
        try:
            age = now - float(rec.get("ts", 0))
        except (TypeError, ValueError):
            continue
        if not _stale(src, age):
            online[src] = rec

    if not online:
        return _read_legacy(now)

    # 因素合并(去重保序)
    merged = []
    seen = set()
    for rec in online.values():
        for f in rec.get("factors", []):
            if f not in seen:
                seen.add(f)
                merged.append(f)

    # 在场: 任一"在场类"源在场即在场; 无源声明 present 时按在场处理
    declared = [rec["present"] for rec in online.values() if "present" in rec]
    present = any(declared) if declared else True

    # 取时间戳最新的一条干预事件
    best = None
    for rec in online.values():
        e = rec.get("event")
        if e and (best is None or rec.get("ts", 0) > best[0]):
            best = (rec.get("ts", 0), e)

    return {
        "schema": SCHEMA, "ts": now, "present": present,
        "factors": merged, "severity": severity_of(merged),
        "vitality": vitality_of(merged),
        "event": best[1] if best else None,
        "online_sources": sorted(online.keys()),
        "sources": {s: {"ts": r.get("ts"), "factors": r.get("factors", []),
                        "metrics": r.get("metrics", {})}
                    for s, r in online.items()},
    }


def _read_legacy(now):
    try:
        with open(LEGACY_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    try:
        if now - float(d.get("ts", 0)) > DEFAULT_STALE_SEC:
            return None
    except (TypeError, ValueError):
        return None
    factors = d.get("factors", [])
    d.setdefault("severity", severity_of(factors))
    d.setdefault("vitality", vitality_of(factors))
    d.setdefault("online_sources", ["camera"])
    d.setdefault("sources", {})
    return d
