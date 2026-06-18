# -*- coding: utf-8 -*-
"""状态/提醒/指标存储与聚合 (SQLite, 仅存指标不存图像)。
   支持双模式：自用视图取实时+当日明细；管理视图取聚合(可脱敏共享)。"""
import sqlite3
import threading
import time
import datetime as dt


class Store:
    def __init__(self, path, sample_interval=30):
        self.path = path
        # 采样心跳间隔(秒)。聚合在岗时长时据此判断监测进程是否真在运行：
        # 采样断档超过 live_gap 即视为监测停止，不计入在岗，避免跨夜/中途关停导致虚高。
        self.sample_interval = sample_interval
        self.live_gap = sample_interval * 3
        self.lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        c = self._conn
        c.execute("CREATE TABLE IF NOT EXISTS events("
                  "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, state TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS reminders("
                  "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, type TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS samples("
                  "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, bpm INTEGER, "
                  "stress INTEGER, slouch INTEGER, seated REAL, screen REAL)")
        # 迁移：情绪紧张度列(老库自动补列)
        try:
            c.execute("ALTER TABLE samples ADD COLUMN tension INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        # 穿戴设备日数据(佳明/华米): 每天每源一行, 幂等 upsert(同日覆盖, 缺项保留旧值)
        c.execute("CREATE TABLE IF NOT EXISTS wearable_daily("
                  "day TEXT, source TEXT, steps INTEGER, resting_hr INTEGER, "
                  "sleep_min INTEGER, ts REAL, PRIMARY KEY(day, source))")
        c.commit()

    # ---------- 写入 ----------
    def log_state(self, state, ts=None):
        ts = ts or time.time()
        with self.lock:
            self._conn.execute("INSERT INTO events(ts, state) VALUES(?,?)", (ts, state))
            self._conn.commit()

    def log_reminder(self, typ, ts=None):
        ts = ts or time.time()
        with self.lock:
            self._conn.execute("INSERT INTO reminders(ts, type) VALUES(?,?)", (ts, typ))
            self._conn.commit()

    def log_sample(self, bpm, stress, slouch, seated, screen, tension=0, ts=None):
        ts = ts or time.time()
        with self.lock:
            self._conn.execute(
                "INSERT INTO samples(ts,bpm,stress,slouch,seated,screen,tension) "
                "VALUES(?,?,?,?,?,?,?)",
                (ts, int(bpm or 0), int(stress or 0), 1 if slouch else 0,
                 float(seated or 0), float(screen or 0), int(tension or 0)))
            self._conn.commit()

    def log_wearable(self, source, metrics, ts=None, day=None):
        """穿戴源日数据 upsert(同日同源覆盖)。缺项(如睡眠尚未同步)用 COALESCE 保留旧值,
        避免半天没睡眠数据时把早先已拉到的值清空。"""
        ts = ts or time.time()
        d = (day or dt.date.today()).isoformat()
        steps = metrics.get("steps")
        rhr = metrics.get("resting_hr")
        sleep = metrics.get("sleep_min")
        with self.lock:
            self._conn.execute(
                "INSERT INTO wearable_daily(day,source,steps,resting_hr,sleep_min,ts) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(day,source) DO UPDATE SET "
                "steps=COALESCE(excluded.steps,wearable_daily.steps),"
                "resting_hr=COALESCE(excluded.resting_hr,wearable_daily.resting_hr),"
                "sleep_min=COALESCE(excluded.sleep_min,wearable_daily.sleep_min),"
                "ts=excluded.ts",
                (d, source, steps, rhr, sleep, ts))
            self._conn.commit()

    # ---------- 聚合 ----------
    def _day_bounds(self, day=None):
        d = day or dt.date.today()
        start = dt.datetime.combine(d, dt.time.min).timestamp()
        return start, start + 86400

    def _live_intervals(self, start, end):
        """监测进程真实在运行的时间段，依据采样心跳(每 sample_interval 秒一条)推断。
        采样断档超过 live_gap 视为监测已停止，该段不计入在岗。
        起点回看 live_gap 以衔接跨夜会话；每段末尾延长一个采样周期(进程在最后一条
        采样之后通常还活着约一个周期才退出)。"""
        with self.lock:
            rows = self._conn.execute(
                "SELECT ts FROM samples WHERE ts>=? AND ts<? ORDER BY ts",
                (start - self.live_gap, end)).fetchall()
        if not rows:
            return []
        segs = []
        seg_start = prev = rows[0][0]
        for (ts,) in rows[1:]:
            if ts - prev > self.live_gap:
                segs.append((seg_start, prev + self.sample_interval))
                seg_start = ts
            prev = ts
        segs.append((seg_start, prev + self.sample_interval))
        clipped = [(max(s, start), min(e, end)) for s, e in segs]
        return [(s, e) for s, e in clipped if e > s]

    def daily_summary(self, day=None):
        start, end = self._day_bounds(day)
        clip_end = min(end, time.time())
        live = self._live_intervals(start, clip_end)
        with self.lock:
            rows = self._conn.execute(
                "SELECT ts,state FROM events WHERE ts < ? ORDER BY ts", (end,)).fetchall()
        durations = {"focused": 0.0, "distracted": 0.0, "drowsy": 0.0, "away": 0.0}
        timeline, away_count = [], 0
        counted_away = set()
        for i, (ts, state) in enumerate(rows):
            nxt = rows[i + 1][0] if i + 1 < len(rows) else clip_end
            es, ee = max(ts, start), min(nxt, clip_end)
            if ee <= es:
                continue
            # 仅统计与监测在线时段的交集，剔除进程关停期间的虚假时长
            for ls, le in live:
                s, e = max(es, ls), min(ee, le)
                if e <= s:
                    continue
                durations[state] = durations.get(state, 0.0) + (e - s)
                timeline.append({"state": state, "start": s, "end": e})
                if state == "away" and ts >= start and ts not in counted_away:
                    away_count += 1
                    counted_away.add(ts)
        return {"durations": durations, "timeline": timeline,
                "away_count": away_count,
                "day": (day or dt.date.today()).isoformat()}

    def reminder_counts(self, day=None):
        start, end = self._day_bounds(day)
        with self.lock:
            rows = self._conn.execute(
                "SELECT type, COUNT(*) FROM reminders WHERE ts>=? AND ts<? GROUP BY type",
                (start, end)).fetchall()
        return {t: n for t, n in rows}

    def health_summary(self, day=None):
        """管理视图：当日健康聚合(可脱敏共享，不含原始画面)。"""
        start, end = self._day_bounds(day)
        with self.lock:
            agg = self._conn.execute(
                "SELECT AVG(NULLIF(bpm,0)), AVG(stress), AVG(slouch), COUNT(*) "
                "FROM samples WHERE ts>=? AND ts<?", (start, end)).fetchone()
        avg_bpm, avg_stress, slouch_ratio, n = agg
        ds = self.daily_summary(day)
        d = ds["durations"]
        onjob = d["focused"] + d["distracted"] + d["drowsy"]
        return {
            "day": ds["day"],
            "focus_minutes": round(d["focused"] / 60, 1),
            "onjob_minutes": round(onjob / 60, 1),
            "focus_rate": round(d["focused"] / onjob * 100, 1) if onjob else 0.0,
            "drowsy_minutes": round(d["drowsy"] / 60, 1),
            "away_count": ds["away_count"],
            "avg_bpm": round(avg_bpm, 0) if avg_bpm else None,
            "avg_stress": round(avg_stress, 0) if avg_stress else None,
            "slouch_ratio": round((slouch_ratio or 0) * 100, 1),
            "reminders": self.reminder_counts(day),
        }

    def wearable_summary(self, day=None):
        """当日穿戴数据(跨源合并: 步数取最大, 静息心率/睡眠取最近写入的非空值)。
        无任何穿戴源数据时返回 None。"""
        d = (day or dt.date.today()).isoformat()
        with self.lock:
            rows = self._conn.execute(
                "SELECT source,steps,resting_hr,sleep_min,ts FROM wearable_daily "
                "WHERE day=? ORDER BY ts", (d,)).fetchall()
        if not rows:
            return None
        out = {"day": d, "sources": [], "steps": None,
               "resting_hr": None, "sleep_min": None}
        for src, steps, rhr, sleep, ts in rows:
            out["sources"].append(src)
            if steps is not None:
                out["steps"] = max(out["steps"] or 0, steps)
            if rhr is not None:
                out["resting_hr"] = rhr      # 按 ts 升序, 最后一条即最近
            if sleep is not None:
                out["sleep_min"] = sleep
        return out

    def wearable_trend(self, days=7):
        today = dt.date.today()
        out = []
        for i in range(days - 1, -1, -1):
            d = today - dt.timedelta(days=i)
            ws = self.wearable_summary(d) or {"day": d.isoformat(),
                                              "steps": None, "resting_hr": None,
                                              "sleep_min": None, "sources": []}
            out.append(ws)
        return out

    def avg_tension(self, day=None):
        start, end = self._day_bounds(day)
        with self.lock:
            row = self._conn.execute(
                "SELECT AVG(NULLIF(tension,0)) FROM samples WHERE ts>=? AND ts<?",
                (start, end)).fetchone()
        return row[0]

    def health_score(self, day=None):
        """综合健康分(0-100) + 各分项。当日在岗不足时返回 None(样本不足)。
        权重：专注 0.30 · 坐姿 0.28 · 平静(压力) 0.18 · 放松(表情) 0.14 · 起身 0.10。"""
        hs = self.health_summary(day)
        if hs["onjob_minutes"] < 10:
            return {"score": None, "components": {}, "avg_tension": None,
                    "onjob_minutes": hs["onjob_minutes"]}
        focus = hs["focus_rate"]
        posture = max(0.0, 100 - hs["slouch_ratio"])
        stress = hs["avg_stress"]
        calm = max(0.0, min(100.0, 100 - (stress if stress is not None else 30)))
        at = self.avg_tension(day)
        relax = max(0.0, min(100.0, 100 - (at if at is not None else 30)))
        move_rem = hs["reminders"].get("need_move", 0)
        move = max(0.0, 100 - move_rem * 12)
        w = {"focus": 0.30, "posture": 0.28, "calm": 0.18, "relax": 0.14, "move": 0.10}
        score = (w["focus"] * focus + w["posture"] * posture + w["calm"] * calm +
                 w["relax"] * relax + w["move"] * move)
        return {"score": round(score),
                "components": {"focus": round(focus), "posture": round(posture),
                               "calm": round(calm), "relax": round(relax),
                               "move": round(move)},
                "avg_tension": round(at) if at else None,
                "onjob_minutes": hs["onjob_minutes"]}

    def streak(self, threshold=70, max_days=90):
        """连续达标(分≥threshold)天数。今天无数据则不计断。"""
        today = dt.date.today()
        n = 0
        for i in range(max_days):
            s = self.health_score(today - dt.timedelta(days=i))["score"]
            if s is None:
                if i == 0:
                    continue
                break
            if s >= threshold:
                n += 1
            else:
                break
        return n

    def weekly_trend(self, days=7):
        today = dt.date.today()
        out = []
        for i in range(days - 1, -1, -1):
            d = today - dt.timedelta(days=i)
            row = self.health_summary(d)
            row["score"] = self.health_score(d)["score"]
            out.append(row)
        return out
