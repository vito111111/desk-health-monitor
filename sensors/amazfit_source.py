# -*- coding: utf-8 -*-
"""华米 / Amazfit(A2011 等, Zepp App)数据源 —— 经 Huami 云 band_data 拉当日步数/睡眠。

路径: 表 → 手机 Zepp App → Huami 云 → 本脚本。Huami 无个人开放 API, 走社区方案:
  1) 用 huami-token 工具(github.com/argrento/huami-token)拿到 apptoken 与 userid(一次性);
  2) 本源用该 token 查 band_data 日汇总接口。

凭据:  ~/.claude/health_inputs/amazfit.json
       {"apptoken": "...", "userid": "...", "region": "de2"}   # region: de2(国际)/us2/cn
运行:  python -m sensors.amazfit_source

说明: Huami 接口对区域/鉴权较敏感, token 会过期; 任何失败 -> fetch 返回 None, 源静默离线。
band_data 的 summary 解析是社区已知格式(stp.ttl 步数 / slp 深+浅睡分钟), 不同固件偶有字段差异,
若你的表解析不全, 调 _parse_summary 即可, 其余链路无需动。
"""
import os
import json
import datetime
import urllib.parse
import urllib.request

# 中国区华米端点同样须绕过本机 SSH 隧道代理(美国出口连不上)。
for _v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
           "ALL_PROXY", "all_proxy"):
    os.environ.pop(_v, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

from sensors.wearable import WearableSource

CFG_FILE = os.path.join(os.path.expanduser("~"), ".claude",
                        "health_inputs", "amazfit.json")


def _parse_summary(summary):
    """band_data 的 summary 字段(JSON 字符串) -> {steps?, sleep_min?}。纯函数, 可离线单测。"""
    if isinstance(summary, str):
        try:
            summary = json.loads(summary)
        except ValueError:
            return {}
    if not isinstance(summary, dict):
        return {}
    out = {}
    stp = summary.get("stp") or {}
    if isinstance(stp, dict) and stp.get("ttl") is not None:
        out["steps"] = int(stp["ttl"])
    slp = summary.get("slp") or {}
    if isinstance(slp, dict):
        mins = 0
        for k in ("dp", "lt"):   # 深睡 + 浅睡(分钟)
            v = slp.get(k)
            if isinstance(v, (int, float)):
                mins += v
        if mins > 0:
            out["sleep_min"] = int(mins)
    return out


def _read_cfg():
    try:
        with open(CFG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


class AmazfitSource(WearableSource):
    name = "amazfit"
    interval = 1800.0

    def fetch(self, now):
        cfg = _read_cfg()
        token, userid = cfg.get("apptoken"), cfg.get("userid")
        if not (token and userid):
            return None
        # 优先用登录脚本探测到的 data_host(中国区如 api-mifit-cn2.huami.com);
        # 否则回退 region 拼接(老配置兼容)。
        host = cfg.get("data_host")
        if not host:
            region = cfg.get("region", "de2")
            host = "api-mifit-{}.huami.com".format(region)
        today = datetime.date.today().isoformat()
        base = "https://{}/v1/data/band_data.json".format(host)
        qs = urllib.parse.urlencode({
            "query_type": "summary", "device_type": "android_phone",
            "userid": userid, "from_date": today, "to_date": today})
        req = urllib.request.Request(
            base + "?" + qs,
            headers={"apptoken": token, "User-Agent": "MiFit/4.6.0 (Android)"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        items = payload.get("data") or []
        if not items:
            return None
        # 取最新一天
        latest = sorted(items, key=lambda d: d.get("date", ""))[-1]
        return _parse_summary(latest.get("summary")) or None


if __name__ == "__main__":
    AmazfitSource().run_loop()
