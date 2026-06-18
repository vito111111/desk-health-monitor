# -*- coding: utf-8 -*-
"""佳明 Garmin Connect 交互式登录(只需跑一次)。

在终端运行:  python garmin_login.py
  · 密码用 getpass 输入, 不回显、不进聊天/不写日志;
  · 支持双重验证(MFA): 会提示输入手机/邮箱验证码;
  · 中国区佳明账号(佳明 App / 连接中国)选择 is_cn=是。

成功后:
  · token 缓存到 ~/.garminconnect(此后 sensors/garmin_source.py 免密拉数据);
  · is_cn 写入 ~/.claude/health_inputs/garmin.json(不存密码);
  · 立刻拉一次今日数据确认打通。
"""
import os
import sys
import json
import getpass
import datetime

# 本机全局走 SSH 隧道(美国出口),用美国出口连中国区佳明(garmin.cn)会超时失败。
# 佳明流量必须绕过代理直连,故在导入 garminconnect/curl_cffi 之前先清掉代理env。
for _v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
           "ALL_PROXY", "all_proxy"):
    os.environ.pop(_v, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from garminconnect import Garmin

TOKENSTORE = os.path.join(os.path.expanduser("~"), ".garminconnect")
CFG_FILE = os.path.join(os.path.expanduser("~"), ".claude",
                        "health_inputs", "garmin.json")


def main():
    print("=== Garmin 佳明账号登录 (password stays local) ===")
    email = input("Email / 佳明邮箱: ").strip()
    pwd = getpass.getpass("Password / 密码 (hidden 不显示): ")
    cn = input("China account? 中国区佳明账号(佳明App)? [y/N]: ").strip().lower().startswith("y")

    def prompt_mfa():
        return input("MFA code / 验证码 (none=just Enter 没有就回车): ").strip()

    api = Garmin(email=email, password=pwd, is_cn=cn, prompt_mfa=prompt_mfa)
    print("登录中…")
    api.login(TOKENSTORE)   # 自动落盘 token 到 TOKENSTORE

    os.makedirs(os.path.dirname(CFG_FILE), exist_ok=True)
    with open(CFG_FILE, "w", encoding="utf-8") as f:
        json.dump({"is_cn": cn}, f, ensure_ascii=False)

    today = datetime.date.today().isoformat()
    stats = api.get_stats(today) or {}
    try:
        sleep = api.get_sleep_data(today) or {}
        secs = (sleep.get("dailySleepDTO") or {}).get("sleepTimeSeconds")
        sleep_min = round(secs / 60) if secs else None
    except Exception:
        sleep_min = None

    print("\n✓ 登录成功, token 已缓存到", TOKENSTORE)
    print("  今日步数 :", stats.get("totalSteps"))
    print("  静息心率 :", stats.get("restingHeartRate"))
    print("  昨夜睡眠 :", "{} 分钟".format(sleep_min) if sleep_min else "暂无")
    print("\n现在可以跑:  python -m sensors.garmin_source   (后台持续拉, 免密)")


if __name__ == "__main__":
    main()
