# -*- coding: utf-8 -*-
"""华米 / Amazfit(Zepp Life 中国区)登录, 取 apptoken + userid(只需跑一次)。

华米云无个人开放 API, 社区方案: 用 Zepp **邮箱+密码** 走 Huami SSO 拿一次性 access code,
再换 app_token / user_id。**微信/手机号/第三方登录取不到 token** —— 须先在
Zepp Life App(我的→设置→账号与安全)绑定邮箱并设置密码, 再用该邮箱在此登录。

在终端运行:  python amazfit_login.py
  · 密码用 getpass 输入, 不回显、不进聊天/日志;
  · 默认中国区(country_code=CN, app=com.xiaomi.hm.health);
  · 成功后自动探测可用的华米数据服务器(api-mifit-* 候选), 并立刻拉一次今日步数/睡眠确认。

成功后写:  ~/.claude/health_inputs/amazfit.json
  {"apptoken":"...", "userid":"...", "region":"cn2", "data_host":"api-mifit-cn2.huami.com"}
此后 sensors/amazfit_source.py 仅凭该凭据免密拉数据(token 会过期, 过期了重跑本脚本)。
"""
import os
import sys
import json
import getpass
import datetime
import urllib.parse
import urllib.request

# 本机全局走 SSH 隧道(美国出口), 中国区华米端点须绕代理直连(同佳明那个坑)。
for _v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
           "ALL_PROXY", "all_proxy"):
    os.environ.pop(_v, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CFG_FILE = os.path.join(os.path.expanduser("~"), ".claude",
                        "health_inputs", "amazfit.json")
UA = "MiFit/4.6.0 (Android 9; en_US)"
# 中国区数据服务器候选(登录后逐个试拉, 命中即写入 data_host); 国际区会再补 de2/us2。
CN_DATA_HOSTS = ["api-mifit-cn2.huami.com", "api-mifit.huami.com",
                 "api-mifit-cn.huami.com"]
INTL_DATA_HOSTS = ["api-mifit-de2.huami.com", "api-mifit-us2.huami.com"]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _post(url, data, headers=None):
    body = urllib.parse.urlencode(data).encode("utf-8")
    h = {"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        resp = opener.open(req, timeout=20)
        return resp.getcode(), resp.headers, resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        # 30x(取 Location)或 4xx 都从异常对象里读 headers/body
        return e.code, e.headers, e.read().decode("utf-8", "ignore")


def get_access_code(email, password):
    """Huami SSO: 邮箱密码 -> access code + country_code。"""
    url = ("https://api-user.huami.com/registrations/"
           + urllib.parse.quote(email, safe="") + "/tokens")
    data = {
        "state": "REDIRECTION", "client_id": "HuaMi",
        "redirect_uri": "https://s3-us-west-2.amazonaws.com/hm-registration/successsignin.html",
        "token": "access", "password": password,
    }
    code, headers, body = _post(url, data)
    loc = headers.get("Location") if headers else None
    if not loc:
        raise RuntimeError("登录失败(没拿到跳转): HTTP {} {}".format(code, body[:200]))
    q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    if "access" not in q:
        # 常见: 邮箱/密码错、该账号没设邮箱密码(微信登录)、需验证码
        raise RuntimeError("未取到 access code, 多半是邮箱/密码不对, 或该账号尚未绑定"
                           "邮箱+密码(微信/第三方登录账号需先在 App 里补绑)。返回: "
                           + json.dumps(q, ensure_ascii=False))
    return q["access"][0], (q.get("country_code", ["CN"])[0])


def login(access_code, country_code):
    """access code -> app_token + user_id(中国区 app com.xiaomi.hm.health)。"""
    url = "https://account.huami.com/v2/client/login"
    data = {
        "app_name": "com.xiaomi.hm.health", "app_version": "4.6.0",
        "code": access_code, "country_code": country_code,
        "device_id": "02:00:00:00:00:00", "device_model": "android_phone",
        "grant_type": "access_token", "third_name": "huami",
        "source": "com.xiaomi.hm.health", "lang": "zh_CN", "os_version": "1.5.0",
    }
    _c, _h, body = _post(url, data)
    try:
        info = json.loads(body).get("token_info") or {}
    except ValueError:
        raise RuntimeError("换取 app_token 失败: " + body[:200])
    app_token, user_id = info.get("app_token"), info.get("user_id")
    if not (app_token and user_id):
        raise RuntimeError("登录返回缺 app_token/user_id: " + body[:200])
    return app_token, user_id


def _try_fetch(host, app_token, user_id):
    today = datetime.date.today().isoformat()
    base = "https://{}/v1/data/band_data.json".format(host)
    qs = urllib.parse.urlencode({
        "query_type": "summary", "device_type": "android_phone",
        "userid": user_id, "from_date": today, "to_date": today})
    req = urllib.request.Request(
        base + "?" + qs, headers={"apptoken": app_token, "User-Agent": UA})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=15) as r:
            payload = json.loads(r.read().decode("utf-8", "ignore"))
        # 能解析出 data 字段(哪怕空)就算这个 host 通
        return payload if "data" in payload else None
    except Exception:
        return None


def discover_host(app_token, user_id, cn=True):
    hosts = (CN_DATA_HOSTS + INTL_DATA_HOSTS) if cn else (INTL_DATA_HOSTS + CN_DATA_HOSTS)
    for h in hosts:
        payload = _try_fetch(h, app_token, user_id)
        if payload is not None:
            return h, payload
    return None, None


def main():
    print("=== 华米 / Zepp Life 登录 (中国区, 邮箱+密码; password stays local) ===")
    print("※ 微信/手机号登录取不到 token, 须先在 Zepp Life App 绑定邮箱+设密码。\n")
    email = input("Zepp 邮箱: ").strip()
    pwd = getpass.getpass("密码 (hidden 不显示): ")

    print("\n[1/3] SSO 取 access code…")
    access, cc = get_access_code(email, pwd)
    print("    ✓ country_code =", cc)

    print("[2/3] 换取 app_token / user_id…")
    app_token, user_id = login(access, cc)
    print("    ✓ user_id =", user_id)

    print("[3/3] 探测可用数据服务器并拉今日数据…")
    host, payload = discover_host(app_token, user_id, cn=(cc.upper() == "CN"))
    if not host:
        raise RuntimeError("app_token 拿到了, 但所有候选数据服务器都没拉到数据。"
                           "可能该账号数据在另一区域, 或 band_data 接口已变。"
                           "凭据仍会保存, 可在 amazfit.json 手填 data_host 重试。")
    region = host.split("api-mifit-")[-1].split(".")[0] if "api-mifit-" in host else "cn2"

    os.makedirs(os.path.dirname(CFG_FILE), exist_ok=True)
    with open(CFG_FILE, "w", encoding="utf-8") as f:
        json.dump({"apptoken": app_token, "userid": user_id,
                   "region": region, "data_host": host}, f, ensure_ascii=False)

    # 解析今日步数/睡眠确认
    from sensors.amazfit_source import _parse_summary
    items = payload.get("data") or []
    info = _parse_summary(items[-1].get("summary")) if items else {}
    print("\n✓ 登录成功, 凭据已写", CFG_FILE)
    print("  数据服务器 :", host)
    print("  今日步数   :", info.get("steps", "暂无"))
    print("  昨夜睡眠   :", "{} 分钟".format(info["sleep_min"]) if info.get("sleep_min") else "暂无")
    print("\n现在可以跑:  python -m sensors.amazfit_source   (后台持续拉, 免密)")
    print("或重启桌前健康助手, 守护会自动带上华米源。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("\n✗ 失败:", e)
        sys.exit(1)
