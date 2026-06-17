# -*- coding: utf-8 -*-
"""每日健康日报 -> 写入 Obsidian vault(可配置)。

长期健康管理的核心：把每天的健康分、分项、趋势归档成可回溯的 Markdown 笔记。
幂等 upsert(同一天覆盖)。纯本地写文件，不联网。
"""
import os
import datetime as dt
from pathlib import Path

_SCORE_TIP = [
    (85, "🟢 状态很棒", "保持住，今天的节奏值得复制"),
    (70, "🟡 整体不错", "再补强分数最低的一项就更稳了"),
    (55, "🟠 有待改善", "重点照顾分数最低项，明天小步改进"),
    (0,  "🔴 需要关注", "别硬扛，多起身、调坐姿、给眼睛和情绪松绑"),
]
_COMP_CN = {"focus": "专注", "posture": "坐姿", "calm": "平静(压力)",
            "relax": "放松(情绪)", "move": "起身"}


def _bar(pct, width=20):
    pct = max(0, min(100, int(pct or 0)))
    fill = round(pct / 100 * width)
    return "█" * fill + "·" * (width - fill)


def _tip(score):
    for thr, head, tip in _SCORE_TIP:
        if score >= thr:
            return head, tip
    return _SCORE_TIP[-1][1], _SCORE_TIP[-1][2]


def report_dir(cfg):
    d = cfg.get("obsidian_health_dir") or ""
    if d and os.path.isdir(os.path.dirname(d) or d) is False:
        # 父目录不存在也尝试创建完整路径
        pass
    if not d:
        d = str(Path(__file__).parent / "health_reports")
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except OSError:
        d = str(Path(__file__).parent / "health_reports")
        os.makedirs(d, exist_ok=True)
        return d


def build_markdown(store, cfg, day=None):
    day = day or dt.date.today()
    hs = store.health_summary(day)
    sc = store.health_score(day)
    streak = store.streak(cfg.get("score_streak_threshold", 70))
    trend = store.weekly_trend(7)

    score = sc["score"]
    comps = sc.get("components", {})
    lines = []
    lines.append(f"---\ntype: 健康日报\ndate: {day.isoformat()}\n"
                 f"score: {score if score is not None else 'NA'}\n"
                 f"tags: [桌前健康, 健康日报]\n---\n")
    lines.append(f"# 🪑 桌前健康日报 · {day.isoformat()}\n")

    if score is None:
        lines.append(f"> 今日在岗仅 {hs['onjob_minutes']} 分钟，样本不足，暂不评分。\n")
    else:
        head, tip = _tip(score)
        lines.append(f"## 综合健康分：**{score} / 100**　{head}")
        lines.append(f"> {tip}　·　连续达标 **{streak}** 天\n")
        lines.append("| 分项 | 得分 | |")
        lines.append("|---|---|---|")
        for k, v in comps.items():
            lines.append(f"| {_COMP_CN.get(k, k)} | {v} | `{_bar(v)}` |")
        lines.append("")

    lines.append("## 今日明细")
    lines.append(f"- 在岗时长：**{hs['onjob_minutes']}** 分钟（专注 {hs['focus_minutes']} 分，"
                 f"专注率 {hs['focus_rate']}%）")
    lines.append(f"- 疲劳时长：{hs['drowsy_minutes']} 分钟　·　离岗 {hs['away_count']} 次")
    lines.append(f"- 坐姿不良占比：{hs['slouch_ratio']}%")
    if hs["avg_bpm"]:
        lines.append(f"- 平均心率：{hs['avg_bpm']} bpm　·　平均压力：{hs['avg_stress']}")
    if sc.get("avg_tension") is not None:
        lines.append(f"- 平均紧张度：{sc['avg_tension']} / 100")
    if hs["reminders"]:
        rem = "　".join(f"{t}×{n}" for t, n in hs["reminders"].items())
        lines.append(f"- 提醒触发：{rem}")
    lines.append("")

    lines.append("## 近 7 日健康分趋势")
    lines.append("| 日期 | 分 | 专注率 | 坐姿不良 | 疲劳(min) |")
    lines.append("|---|---|---|---|---|")
    for d in trend:
        sv = d.get("score")
        lines.append(f"| {d['day'][5:]} | {sv if sv is not None else '—'} "
                     f"| {d['focus_rate']}% | {d['slouch_ratio']}% | {d['drowsy_minutes']} |")
    lines.append("\n---\n*由桌前健康关怀助手自动生成 · 纯本地数据，无图像留存*")
    return "\n".join(lines)


def write_daily_note(store, cfg, day=None):
    if not cfg.get("daily_report", True):
        return None
    day = day or dt.date.today()
    md = build_markdown(store, cfg, day)
    path = os.path.join(report_dir(cfg), f"健康日报-{day.isoformat()}.md")
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(md)
        os.replace(tmp, path)
        return path
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return None
