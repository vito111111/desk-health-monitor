# -*- coding: utf-8 -*-
"""主动健康干预 —— 三路传感输入 × 循证健康干预模型 × JITAI 投递架构。

【输入数据 = 三路传感流】
  1) 手表数据(穿戴): 静息心率、睡眠时长、(心率)            <- sensors/garmin|amazfit
  2) 运动数据(活动): 每日步数、久坐时长、起身依从            <- 穿戴步数 + 摄像头久坐
  3) 视频监测数据(摄像头): 疲劳、坐姿、用眼、压力(rPPG)、情绪紧张  <- modules/*

【健康干预模型 = 每个领域对齐一个公认循证标准】(domain → model)
  · 睡眠     Sleep     ← NSF/AASM 成人 7–9h 睡眠时长指南(睡眠债累积)
  · 活动     Activity  ← WHO 身体活动指南(≥150min/周中等强度;每坐 30–60min 打断久坐;~7–8k 步/日)
  · 心血管   Cardio    ← 静息心率趋势 + 恢复(Firstbeat 恢复/HRV 思路): 静息 HR 持续/趋势性升高=恢复不足
  · 压力恢复 Stress    ← 压力–恢复平衡(allostatic load 异稳态负荷): 慢性高压力/高紧张=负荷累积
  · 人体工学 Ergonomic ← 办公人体工学(RULA/REBA 简化 + 微休息): 持续不良坐姿=肌肉骨骼风险
  · 视疲劳   Visual    ← 数字视疲劳 20-20-20 法则(AAO): 长时间近距离用屏

【投递架构 = JITAI(Just-In-Time Adaptive Intervention, 适时自适应干预)】
  决策点 decision point = 周期评估;  裁剪变量 tailoring vars = 三路传感状态;
  决策规则 decision rules = 下方各领域阈值(assess_risks);  干预选项 = 现在/本周行动;
  接受度 receptivity = 智能节律门控(rhythm: 会议/勿扰/自然停顿才推送) —— 不打扰才有效。

分工(与本项目一贯设计一致):
  · 风险判定 = 本地确定性规则(assess_risks), 不依赖网络/大模型, 永远可用, 可回溯到具体阈值;
  · 文案/陪伴层 = claude CLI 把风险信号按 JITAI 润色成健康教练口吻的行动建议; CLI 不可用 -> 模板兜底。

⚠ 医疗安全边界: 产出是基于上述循证模型与统计规律的"一般健康提示", **不是医疗诊断**。
  涉及持续不适/异常指标时统一引导"请咨询医生", LLM 提示词明确禁止下诊断/开药。

产出:
  · ~/.claude/health_intervention.json   (管理视图 / 桌宠读取)
  · Obsidian: 健康干预-YYYY-MM-DD.md       (可回溯归档, 标注领域+依据模型)
  · urgent_event(): 有 alert 级风险时返回主动推送事件, 经接受度门控后投递
"""
import os
import json
import shutil
import datetime as dt
import subprocess

HOME = os.path.expanduser("~")
# 注意: 放在 ~/.claude 而非 ~/.claude/health/, 否则会被 health_state 的源聚合(glob health/*.json)误当作一个数据源。
STATE_FILE = os.path.join(HOME, ".claude", "health_intervention.json")

DISCLAIMER = ("本建议基于桌面健康监测的统计规律，属一般健康提示，非医疗诊断；"
              "若有持续不适或指标异常，请咨询专业医生。")

# 风险阈值(可被 config.json 的 intervention 块覆盖)
DEFAULTS = {
    "sleep_debt_min": 360,        # 夜间睡眠 < 6h 记一次睡眠不足
    "sleep_debt_days": 3,         # 近 7 日睡眠不足天数 ≥ 此 -> 慢性睡眠债(alert)
    "resting_hr_warn": 75,        # 静息心率持续高于此 -> 关注
    "resting_hr_rise": 6,         # 近 7 日静息心率上升幅度 ≥ 此 -> 上升趋势
    "low_steps": 3000,            # 单日步数低于此记一次活动不足
    "low_steps_days": 3,          # 近 7 日活动不足天数 ≥ 此 -> 久坐少动
    "stress_warn": 60,            # 平均压力/紧张度 ≥ 此 -> 长期紧绷
    "stress_days": 3,
    "slouch_ratio_warn": 30,      # 坐姿不良占比 ≥ 此(%)
    "slouch_days": 3,
    "low_score": 55,              # 健康分 < 此
    "low_score_days": 3,
    "eye_strain_reminders": 4,    # 当日用眼提醒(远眺/干眼)次数 ≥ 此 -> 视疲劳
}

_RISK_LABEL = {
    "sleep_debt": "睡眠不足", "resting_hr": "静息心率偏高", "low_activity": "久坐少动",
    "chronic_stress": "长期紧绷", "posture": "坐姿不良", "visual_strain": "用眼疲劳",
    "low_score": "整体健康分偏低",
}

# 每个风险键 -> (健康领域, 依据的循证模型, 主要输入数据流)。让每条建议可回溯到标准。
RISK_MODEL = {
    "sleep_debt":     ("睡眠",     "NSF/AASM 成人 7–9h 睡眠时长指南",        "手表"),
    "resting_hr":     ("心血管",   "静息心率趋势 + 恢复(Firstbeat/HRV 思路)", "手表"),
    "low_activity":   ("活动",     "WHO 身体活动指南(久坐打断 + 步数)",       "运动"),
    "chronic_stress": ("压力恢复", "压力–恢复平衡(异稳态负荷 allostatic load)", "视频"),
    "posture":        ("人体工学", "办公人体工学 RULA/REBA + 微休息",         "视频"),
    "visual_strain":  ("视疲劳",   "数字视疲劳 20-20-20 法则(AAO)",          "视频"),
    "low_score":      ("综合",     "多维健康分(本系统综合模型)",              "综合"),
}


# --------------------------------------------------------------- 统计摘要
def build_digest(store, days=7):
    """把 Store 的聚合压成一个紧凑 JSON 摘要(喂规则引擎和 LLM)。"""
    today = store.health_summary()
    score = store.health_score()
    trend = store.weekly_trend(days)
    wear_today = store.wearable_summary()
    wear_trend = store.wearable_trend(days)
    wt = wear_today or {}
    # JITAI 裁剪变量: 显式按三路传感流归类(手表 / 运动 / 视频)
    streams = {
        "手表(穿戴)": {"静息心率": wt.get("resting_hr"), "昨夜睡眠分钟": wt.get("sleep_min")},
        "运动(活动)": {"今日步数": wt.get("steps"),
                       "久坐提醒次数": (today["reminders"] or {}).get("need_move", 0)},
        "视频(摄像头)": {"专注率": today["focus_rate"], "坐姿不良占比": today["slouch_ratio"],
                         "平均压力": today["avg_stress"], "平均紧张度": score.get("avg_tension"),
                         "疲劳分钟": today["drowsy_minutes"]},
    }
    return {
        "date": today["day"],
        "streams": streams,
        "today": {
            "score": score.get("score"),
            "components": score.get("components", {}),
            "onjob_minutes": today["onjob_minutes"],
            "focus_rate": today["focus_rate"],
            "slouch_ratio": today["slouch_ratio"],
            "drowsy_minutes": today["drowsy_minutes"],
            "avg_bpm": today["avg_bpm"], "avg_stress": today["avg_stress"],
            "avg_tension": score.get("avg_tension"),
            "reminders": today["reminders"],
        },
        "week": [{"day": d["day"], "score": d.get("score"),
                  "focus_rate": d["focus_rate"], "slouch_ratio": d["slouch_ratio"],
                  "drowsy_minutes": d["drowsy_minutes"],
                  "avg_stress": d["avg_stress"]} for d in trend],
        "wearable_today": wear_today,
        "wearable_week": wear_trend,
    }


# --------------------------------------------------------------- 规则风险评估
def _cfg(cfg):
    out = dict(DEFAULTS)
    out.update((cfg or {}).get("intervention", {}) or {})
    return out


def _mk(key, level, title, evidence):
    """组装一条风险, 自动附上领域/依据模型/数据流(来自 RISK_MODEL)。"""
    domain, model, stream = RISK_MODEL.get(key, ("综合", "", "综合"))
    return {"key": key, "level": level, "title": title, "evidence": evidence,
            "domain": domain, "model": model, "stream": stream}


def assess_risks(digest, cfg=None):
    """JITAI 决策规则: 三路传感裁剪变量 -> 各领域循证阈值 -> 风险信号列表。
    每项 {key, level, title, evidence, domain, model, stream}。
    level: alert(需主动干预) > warn(留意) > info。"""
    p = _cfg(cfg)
    risks = []
    today = digest.get("today", {})
    week = digest.get("week", [])
    wweek = digest.get("wearable_week", [])

    # 1) 睡眠 (手表 ← NSF/AASM 7–9h): 近 7 日睡眠不足天数
    sleep_short = [w for w in wweek
                   if w.get("sleep_min") is not None and w["sleep_min"] < p["sleep_debt_min"]]
    if sleep_short:
        last = digest.get("wearable_today") or {}
        chronic = len(sleep_short) >= p["sleep_debt_days"]
        risks.append(_mk(
            "sleep_debt", "alert" if chronic else "warn",
            "睡眠不足" + ("(已连续多日)" if chronic else ""),
            "近7日有 {} 天睡眠 < 6 小时{}".format(
                len(sleep_short),
                "；昨夜 {}h{}m".format(last["sleep_min"] // 60, last["sleep_min"] % 60)
                if last.get("sleep_min") is not None else "")))

    # 2) 心血管 (手表 ← 静息HR趋势/恢复): 静息心率偏高 或 一周上升趋势(恢复不足)
    rhr = [w["resting_hr"] for w in wweek if w.get("resting_hr") is not None]
    if rhr:
        latest = rhr[-1]
        rose = len(rhr) >= 2 and (rhr[-1] - min(rhr)) >= p["resting_hr_rise"]
        high = latest >= p["resting_hr_warn"]
        if high or rose:
            ev = []
            if high:
                ev.append("当前静息心率 {} bpm(≥{})".format(latest, p["resting_hr_warn"]))
            if rose:
                ev.append("一周内上升 {} bpm(恢复不足信号)".format(rhr[-1] - min(rhr)))
            risks.append(_mk("resting_hr", "warn", "静息心率偏高", "；".join(ev)))

    # 3) 活动 (运动 ← WHO 身体活动指南): 近 7 日步数过低天数
    low_steps = [w for w in wweek
                 if w.get("steps") is not None and w["steps"] < p["low_steps"]]
    if len(low_steps) >= p["low_steps_days"]:
        risks.append(_mk("low_activity", "warn", "久坐少动",
                         "近7日有 {} 天步数 < {}(低于 WHO 活动量参考)".format(
                             len(low_steps), p["low_steps"])))

    # 4) 压力恢复 (视频 rPPG/紧张 ← 异稳态负荷): 多日平均压力高
    stressed = [w for w in week
                if w.get("avg_stress") is not None and w["avg_stress"] >= p["stress_warn"]]
    if len(stressed) >= p["stress_days"]:
        risks.append(_mk("chronic_stress", "warn", "长期紧绷",
                         "近7日有 {} 天平均压力偏高(负荷累积)".format(len(stressed))))

    # 5) 人体工学 (视频坐姿 ← RULA/REBA + 微休息): 多日驼背占比高
    slouchy = [w for w in week if (w.get("slouch_ratio") or 0) >= p["slouch_ratio_warn"]]
    if len(slouchy) >= p["slouch_days"]:
        risks.append(_mk("posture", "warn", "坐姿不良",
                         "近7日有 {} 天坐姿不良占比 ≥ {}%".format(
                             len(slouchy), p["slouch_ratio_warn"])))

    # 6) 视疲劳 (视频用眼 ← 20-20-20): 当日用眼相关提醒频繁
    rem = today.get("reminders", {}) or {}
    eye_n = (rem.get("need_eye_break", 0) or 0) + (rem.get("dry_eye", 0) or 0)
    if eye_n >= p.get("eye_strain_reminders", 4):
        risks.append(_mk("visual_strain", "warn", "用眼疲劳",
                         "今日用眼提醒 {} 次(久未远眺/眨眼偏少)".format(eye_n)))

    # 7) 综合 (多维健康分): 多日偏低
    low = [w for w in week if w.get("score") is not None and w["score"] < p["low_score"]]
    if len(low) >= p["low_score_days"]:
        risks.append(_mk("low_score", "alert", "整体健康分偏低",
                         "近7日有 {} 天健康分 < {}".format(len(low), p["low_score"])))
    return risks


def overall_level(risks):
    if any(r["level"] == "alert" for r in risks):
        return "alert"
    if any(r["level"] == "warn" for r in risks):
        return "warn"
    return "ok"


# --------------------------------------------------------------- LLM 文案层
def _ask_claude(digest, risks):
    exe = shutil.which("claude")
    if not exe:
        return None
    payload = {"统计摘要(三路传感)": digest, "本地循证规则识别的风险信号": risks}
    prompt = (
        "你是用户的桌面健康教练(陪伴角色, 不是医生), 采用 JITAI(适时自适应干预)方法。\n"
        "输入数据来自三路传感流: 手表(静息心率/睡眠)、运动(步数/久坐)、视频监测(疲劳/坐姿/用眼/压力/紧张)。\n"
        "下方 JSON 含统计摘要, 以及本地规则按循证模型(睡眠 NSF/AASM、活动 WHO、心血管恢复、"
        "压力-恢复异稳态负荷、人体工学 RULA/REBA、视疲劳 20-20-20)识别出的风险信号(每条带 domain/model)。\n"
        "请据此写一段**主动健康干预建议**, 要求:\n"
        "1) 先用一句话点出当前最值得关注的 1-2 个信号, 并自然带出它属于哪个领域(温暖、不贩卖焦虑);\n"
        "2) 给出'现在就能做'的 2-3 个具体小动作, 和'本周'的 1-2 个改善方向, 要贴合对应循证模型、可执行;\n"
        "3) 口吻像贴心的伙伴, 简体中文, 总长 160 字以内, 用自然段不要用 markdown 标题;\n"
        "4) **严禁医疗诊断、严禁判断疾病、严禁推荐药物或保健品**; 若数据提示明显异常, "
        "只需温和建议'去咨询医生', 不要展开。\n"
        "只输出建议正文本身。\n\n" + json.dumps(payload, ensure_ascii=False))
    # Windows 下 claude 是 .CMD: 经 comspec 包一层; 提示词走 stdin 避免转义。
    if exe.lower().endswith((".cmd", ".bat")):
        cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", exe, "-p"]
    else:
        cmd = [exe, "-p"]
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True,
                           text=True, timeout=150, encoding="utf-8")
        text = (r.stdout or "").strip()
        return text or None
    except (OSError, subprocess.SubprocessError):
        return None


def _template(digest, risks):
    """LLM 不可用时的规则兜底文案。"""
    if not risks:
        s = digest.get("today", {}).get("score")
        return ("最近的健康数据看起来挺稳{}，没有明显的风险信号，继续保持现在的节奏就好～"
                "记得累了就起身走两步、给眼睛和肩颈松松绑。"
                .format("(健康分 {})".format(s) if s is not None else ""))
    tips = {
        "sleep_debt": "今晚争取早睡 30 分钟、睡前少看屏幕(对齐 7–9h 睡眠)",
        "resting_hr": "安排几次深呼吸/散步帮助恢复，留意睡眠与压力；持续偏高建议咨询医生",
        "low_activity": "每坐 30–60 分钟起身走 2 分钟，今天补一段 10 分钟快走(凑够 WHO 活动量)",
        "chronic_stress": "每小时做一次 1 分钟深呼吸，给自己排一段无打扰的恢复时间",
        "posture": "屏幕抬到平视、靠背坐满，每 30 分钟挺直一次(人体工学微休息)",
        "visual_strain": "用 20-20-20：每 20 分钟看 20 英尺外 20 秒，主动多眨眼",
        "low_score": "挑分数最低的一项先改，今天只做一个小改进",
    }
    worst = "、".join(_RISK_LABEL.get(r["key"], r["key"]) for r in risks[:2])
    actions = "；".join(tips.get(r["key"], "") for r in risks[:3] if tips.get(r["key"]))
    return "最近主要要留意：{}。可以先这样做——{}。一步步来，别给自己太大压力～".format(worst, actions)


# --------------------------------------------------------------- 生成 / 输出
def generate(store, cfg=None, use_llm=True, days=7):
    digest = build_digest(store, days)
    risks = assess_risks(digest, cfg)
    level = overall_level(risks)
    advice = (_ask_claude(digest, risks) if use_llm else None) or _template(digest, risks)
    return {
        "ts": _now_ts(),
        "date": digest["date"],
        "level": level,
        "risks": risks,
        "advice": advice,
        "disclaimer": DISCLAIMER,
    }


def _now_ts():
    # 与项目其它处一致用 time.time(); 单列以便测试注入。
    import time
    return time.time()


def write_state(result):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


def read_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def archive_obsidian(result, cfg):
    d = (cfg or {}).get("obsidian_health_dir")
    if not d or not os.path.isdir(d):
        return None
    day = result["date"]
    path = os.path.join(d, "健康干预-{}.md".format(day))
    badge = {"alert": "🔴 需要关注", "warn": "🟡 留意", "ok": "🟢 状态平稳"}.get(result["level"], "")
    lines = [
        "---", "type: 健康干预", "date: {}".format(day),
        "level: {}".format(result["level"]), "tags: [桌前健康, 健康干预]", "---", "",
        "# 🩺 主动健康干预 · {}　{}".format(day, badge), "",
        "> {}".format(result["advice"]), "",
    ]
    if result["risks"]:
        lines.append("## 识别到的风险信号(领域 · 依据模型 · 数据流)")
        for r in result["risks"]:
            mark = "🔴" if r["level"] == "alert" else "🟡"
            tag = "（{} · {} · {}）".format(
                r.get("domain", ""), r.get("model", ""), r.get("stream", ""))
            lines.append("- {} **{}** — {}　{}".format(
                mark, r["title"], r["evidence"], tag))
        lines.append("")
    lines.append("## 方法")
    lines.append("> 三路传感(手表/运动/视频) × 循证领域模型(睡眠 NSF/AASM · 活动 WHO · "
                 "心血管恢复 · 压力-恢复 · 人体工学 RULA/REBA · 视疲劳 20-20-20) × "
                 "JITAI 适时自适应干预(接受度门控)。")
    lines.append("")
    lines.append("---")
    lines.append("*{}*".format(result["disclaimer"]))
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
        return path
    except OSError:
        return None


def urgent_event(result):
    """有 alert 级风险时, 返回一个主动推送事件(供 reminders/桌宠), 否则 None。"""
    alerts = [r for r in result.get("risks", []) if r["level"] == "alert"]
    if not alerts:
        return None
    r = alerts[0]
    return {
        "type": "health_intervention",
        "title": "健康提醒 · {}".format(r["title"]),
        "body": result["advice"][:60],
        "routine": None,
    }


def run_once(store, cfg, use_llm=True):
    """生成 + 落盘 + 归档 一条龙; 返回 result。"""
    result = generate(store, cfg, use_llm=use_llm)
    write_state(result)
    archive_obsidian(result, cfg)
    return result


if __name__ == "__main__":
    import json as _json
    from pathlib import Path
    from storage import Store
    base = Path(__file__).parent
    cfg = _json.loads((base / "config.json").read_text(encoding="utf-8"))
    st = Store(str(base / cfg["db_path"]))
    res = run_once(st, cfg, use_llm=True)
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("level:", res["level"])
    print("risks:", [r["title"] for r in res["risks"]])
    print("advice:", res["advice"])
