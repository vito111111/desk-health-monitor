# -*- coding: utf-8 -*-
"""佳明(Garmin Forerunner 255 等)数据源 —— 经 Garmin Connect 云拉当日睡眠/静息心率/步数。

路径: 表 → 手机 Garmin Connect App → Garmin 云 → 本脚本(非官方 garminconnect 库, 走与官方
安卓 App 相同的 SSO/OAuth 流程)。首次用账号密码登录, token 缓存到 ~/.garminconnect, 之后自动续期。

依赖:  pip install garminconnect   (本机已装 0.3.6)
首次登录:  在终端跑  python garmin_login.py   (交互输入账号/密码/验证码, 密码不进聊天/日志,
          成功后 token 缓存到 ~/.garminconnect, 并把 is_cn 写进 garmin.json)
此后本源仅凭缓存 token 拉数据, 无需密码。

配置:  ~/.claude/health_inputs/garmin.json
       {"is_cn": false}                     # 中国区佳明账号(佳明App)填 true
       可选 {"email":"...","password":"..."} # 无 token 时回退用; headless 下不支持 MFA

运行:  python -m sensors.garmin_source
任何一步失败(没装库/没 token 且无凭据/网络/登录失效) -> fetch 返回 None, 源静默离线。
"""
import os
import json
import datetime

# 佳明(中国区 garmin.cn)流量必须绕过本机 SSH 隧道代理,否则美国出口连不上中国区端点。
for _v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
           "ALL_PROXY", "all_proxy"):
    os.environ.pop(_v, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

from sensors.wearable import WearableSource

CFG_FILE = os.path.join(os.path.expanduser("~"), ".claude",
                        "health_inputs", "garmin.json")
TOKENSTORE = os.path.join(os.path.expanduser("~"), ".garminconnect")


def _read_cfg():
    try:
        with open(CFG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


class GarminSource(WearableSource):
    name = "garmin"
    interval = 1800.0   # 30 min

    def __init__(self):
        super().__init__()
        self._api = None

    def _client(self):
        if self._api is not None:
            return self._api
        from garminconnect import Garmin   # 延迟导入: 没装库时本源直接离线
        cfg = _read_cfg()
        # 0.3.6: login(tokenstore) 自动"有缓存用缓存, 否则用账号密码登录并落盘 token"。
        # headless 不弹 MFA, 故首次须用 garmin_login.py 建好 token 缓存。
        api = Garmin(email=cfg.get("email") or None,
                     password=cfg.get("password") or None,
                     is_cn=bool(cfg.get("is_cn", False)))
        api.login(TOKENSTORE)
        self._api = api
        return api

    def fetch(self, now):
        api = self._client()
        today = datetime.date.today().isoformat()
        out = {}
        try:
            stats = api.get_stats(today) or {}
            if stats.get("totalSteps") is not None:
                out["steps"] = int(stats["totalSteps"])
            if stats.get("restingHeartRate") is not None:
                out["resting_hr"] = int(stats["restingHeartRate"])
        except Exception:
            pass
        try:
            sleep = api.get_sleep_data(today) or {}
            secs = (sleep.get("dailySleepDTO") or {}).get("sleepTimeSeconds")
            if secs:
                out["sleep_min"] = round(secs / 60)
        except Exception:
            pass
        return out or None


if __name__ == "__main__":
    GarminSource().run_loop()
