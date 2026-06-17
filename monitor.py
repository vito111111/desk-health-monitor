# -*- coding: utf-8 -*-
"""
桌前健康关怀助手 - 核心编排引擎
基于笔记本摄像头，本地实时分析，服务使用者本人。整合 5 个关怀模块：
  疲劳监测 / 久坐坐姿 / 用眼健康 / 在场感知 / rPPG 心率压力

隐私设计：默认不保存任何视频或图像帧，仅把"状态指标"写入本地数据库。
"""
import time
import threading

import cv2

from modules.vision import FaceLandmarkerWrap
from modules.geom import head_pose
from modules.fatigue import FatigueAnalyzer
from modules.eyecare import EyeCareAnalyzer
from modules.posture import PostureAnalyzer
from modules.rppg import RppgAnalyzer
from modules.presence import PresenceController
from modules.affect import AffectAnalyzer
from modules.env import EnvLightAnalyzer
from modules.rhythm import RhythmController
from reminders import ReminderManager
from pet_bridge import PetBridge
import report

# 在岗状态(用于专注时间线)
STATE_AWAY, STATE_DROWSY, STATE_DISTRACTED, STATE_FOCUSED = "away", "drowsy", "distracted", "focused"
STATE_LABELS = {STATE_AWAY: "离岗", STATE_DROWSY: "疲劳", STATE_DISTRACTED: "分心", STATE_FOCUSED: "专注"}
STATE_COLORS = {STATE_AWAY: (128, 128, 128), STATE_DROWSY: (60, 60, 230),
                STATE_DISTRACTED: (30, 170, 240), STATE_FOCUSED: (90, 200, 90)}
ASCII_STATE = {STATE_AWAY: "AWAY", STATE_DROWSY: "DROWSY",
               STATE_DISTRACTED: "DISTRACTED", STATE_FOCUSED: "FOCUSED"}


class Monitor:
    def __init__(self, config, store=None):
        self.cfg = config
        self.store = store
        self.lock = threading.Lock()
        self.running = False
        self._stop = threading.Event()
        self._jpeg = None

        self.fatigue = FatigueAnalyzer(config)
        self.eyecare = EyeCareAnalyzer(config)
        self.posture = PostureAnalyzer(config)
        self.rppg = RppgAnalyzer(config)
        self.presence = PresenceController(config)
        self.affect = AffectAnalyzer(config)
        self.env = EnvLightAnalyzer(config)
        self.rhythm = RhythmController(config)
        self.reminders = ReminderManager(config)
        self.pet_bridge = PetBridge(config)

        self.state = STATE_AWAY
        self.last_face_ts = 0.0
        self.look_away_since = None
        self.fps = 0.0
        self.active_reminders = []
        self._await_break = False   # 已建议起身、等待用户实际起身(依从率)

    def _decide_state(self, now, present, drowsy, looking_away):
        cfg = self.cfg
        if not present:
            if now - self.last_face_ts >= cfg["away_seconds"]:
                return STATE_AWAY
            return self.state if self.state != STATE_AWAY else STATE_FOCUSED
        if drowsy:
            return STATE_DROWSY
        if self.look_away_since is not None and now - self.look_away_since >= cfg["distracted_grace_seconds"]:
            return STATE_DISTRACTED
        return STATE_FOCUSED

    def run(self):
        cfg = self.cfg
        cap = cv2.VideoCapture(cfg["camera_index"], cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg["frame_width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg["frame_height"])
        if not cap.isOpened():
            raise RuntimeError(f"无法打开摄像头 index={cfg['camera_index']}")

        face_lm = FaceLandmarkerWrap()

        self.running = True
        interval = 1.0 / max(1, cfg["target_fps"])
        start = time.time()
        last_t = start
        last_pose_t = 0.0
        last_sample_t = 0.0
        last_report_t = start
        pose_m = self.posture.metrics
        face_ts = pose_ts = 0   # 各自单调递增的毫秒时间戳

        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue
                now = time.time()
                frame = cv2.flip(frame, 1)
                h, w = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                ts_ms = max(face_ts + 1, int((now - start) * 1000))
                face_ts = ts_ms
                face = face_lm.detect(rgb, ts_ms)

                present = face is not None
                yaw = pitch = 0.0
                fat = self.fatigue.metrics
                eye = self.eyecare.metrics
                rp = self.rppg.metrics

                if present:
                    self.last_face_ts = now
                    pts = [(p.x * w, p.y * h) for p in face]
                    yaw, pitch = head_pose(pts, w, h)
                    looking_away = abs(yaw) >= cfg["distracted_yaw_deg"] or abs(pitch) >= cfg["distracted_pitch_deg"]
                    if looking_away:
                        if self.look_away_since is None:
                            self.look_away_since = now
                    else:
                        self.look_away_since = None
                    looking_at_screen = not looking_away

                    fat = self.fatigue.update(pts, now)
                    eye = self.eyecare.update(pts, now, looking_at_screen, fat["blink_rate"])
                    rp = self.rppg.update(frame, pts, now)

                    if now - last_pose_t >= cfg["pose_interval"]:
                        pose_ts = max(pose_ts + 1, int((now - start) * 1000))
                        pose_m = self.posture.update(rgb, now, present, pose_ts)
                        last_pose_t = now
                else:
                    self.fatigue.reset_transient()
                    self.look_away_since = None
                    if now - last_pose_t >= cfg["pose_interval"]:
                        pose_ts = max(pose_ts + 1, int((now - start) * 1000))
                        pose_m = self.posture.update(rgb, now, present, pose_ts)
                        last_pose_t = now

                pres_m = self.presence.update(now, present)
                env_m = self.env.update(float(frame.mean()), now)
                aff = self.affect.update(face_lm.last_blendshapes) if present else self.affect.metrics
                rhy = self.rhythm.update(now, present, fat.get("mar") if present else None)

                drowsy = present and fat["drowsy"]
                new_state = self._decide_state(now, present,
                                               drowsy, self.look_away_since is not None)
                if new_state != self.state:
                    # 依从率：建议起身后真的起身(离岗)算一次完成
                    if new_state == STATE_AWAY and self._await_break:
                        self.rhythm.note_taken()
                        self._await_break = False
                    self.state = new_state
                    if self.store:
                        self.store.log_state(new_state, now)

                # 不健康因素(真实状态, 驱动宠物造型/颜色, 不受勿扰影响)
                conds = {
                    "drowsy": drowsy,
                    "slouch": present and pose_m.get("slouch", False),
                    "high_shoulder": present and pose_m.get("high_shoulder", False),
                    "need_move": pose_m.get("need_move", False),
                    "need_eye_break": present and eye.get("need_eye_break", False),
                    "dry_eye": present and eye.get("dry_eye", False),
                    "too_close": present and eye.get("too_close", False),
                    "high_stress": rp.get("valid") and rp.get("stress", 0) >= cfg["high_stress_threshold"],
                    "dark_env": present and env_m.get("dark", False),
                }
                # 智能节律门控：会议/勿扰/安静抑制；休息类延到自然停顿
                natural_pause = (not present) or (self.look_away_since is not None)
                gated = self.rhythm.gate(conds, now, natural_pause)
                fired = self.reminders.evaluate(gated, now)
                for r in fired:
                    if self.store:
                        self.store.log_reminder(r["type"], now)
                    if r["type"] == "need_eye_break":
                        self.eyecare.took_break(now)
                    if r["type"] == "need_move":
                        self.rhythm.note_suggested()
                        self._await_break = True
                self.active_reminders = self.reminders.current()

                # 桥接到桌面宠物：真实因素 + 本轮新触发(经门控)的建议事件
                factors = [k for k, v in conds.items() if v]
                ev = self.pet_bridge.pick_event([r["type"] for r in fired])
                self.pet_bridge.update(present, factors, event=ev)

                # 周期采样(给管理视图趋势)
                if now - last_sample_t >= cfg["sample_interval"] and self.store:
                    self.store.log_sample(
                        rp.get("bpm", 0), rp.get("stress", 0),
                        pose_m.get("slouch", False), pose_m.get("seated_minutes", 0),
                        eye.get("screen_minutes", 0),
                        tension=aff.get("tension", 0) if aff.get("valid") else 0, ts=now)
                    last_sample_t = now

                # 周期归档健康日报(Obsidian)
                if (self.store and cfg.get("daily_report", True)
                        and now - last_report_t >= cfg.get("report_interval", 600)):
                    try:
                        report.write_daily_note(self.store, cfg)
                    except Exception:
                        pass
                    last_report_t = now

                dt = now - last_t
                last_t = now
                if dt > 0:
                    self.fps = 0.8 * self.fps + 0.2 * (1.0 / dt)

                self._render(frame, yaw, pitch, fat, eye, pose_m, rp)

                sleep = interval - (time.time() - now)
                if sleep > 0:
                    time.sleep(sleep)
        finally:
            cap.release()
            face_lm.close()
            self.posture.close()
            self.running = False
            # 退出前归档一次当日健康日报
            if self.store and self.cfg.get("daily_report", True):
                try:
                    report.write_daily_note(self.store, self.cfg)
                except Exception:
                    pass

    def _render(self, frame, yaw, pitch, fat, eye, pose_m, rp):
        st = self.state
        color = STATE_COLORS[st]
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (0, 0), (w, 38), color, -1)
        cv2.putText(frame, ASCII_STATE[st], (10, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        # 右上角关怀告警(ASCII, 中文交给网页看板)
        flags = []
        if pose_m.get("slouch"): flags.append("SLOUCH")
        if pose_m.get("high_shoulder"): flags.append("UNEVEN-SH")
        if eye.get("too_close"): flags.append("TOO-CLOSE")
        if eye.get("need_eye_break"): flags.append("EYE-BREAK")
        if pose_m.get("need_move"): flags.append("MOVE")
        if self.env.metrics.get("dark"): flags.append("DARK")
        if self.rhythm.metrics.get("meeting"): flags.append("MEETING")
        if flags:
            cv2.putText(frame, " ".join(flags), (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 220, 255), 2)
        l1 = f"EAR {fat['ear']:.2f} blink/min {fat['blink_rate']:.0f} PERCLOS {fat['perclos']*100:.0f}%"
        l2 = f"dist {eye['est_cm']}cm screen {eye['screen_minutes']}min seated {pose_m.get('seated_minutes',0)}min"
        hr = f"HR {rp['bpm']}bpm stress {rp['stress']}" if rp.get("valid") else "HR --(measuring)"
        l3 = f"yaw {yaw:.0f} pitch {pitch:.0f}  {hr}  fps {self.fps:.0f}"
        for i, t in enumerate([l1, l2, l3]):
            cv2.putText(frame, t, (10, h - 52 + i * 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            with self.lock:
                self._jpeg = buf.tobytes()

    def get_jpeg(self):
        with self.lock:
            return self._jpeg

    def snapshot(self):
        return {
            "state": self.state, "label": STATE_LABELS[self.state],
            "fps": round(self.fps, 1),
            "fatigue": dict(self.fatigue.metrics),
            "eyecare": dict(self.eyecare.metrics),
            "posture": dict(self.posture.metrics),
            "rppg": dict(self.rppg.metrics),
            "presence": dict(self.presence.metrics),
            "affect": dict(self.affect.metrics),
            "env": dict(self.env.metrics),
            "rhythm": dict(self.rhythm.metrics),
            "reminders": list(self.active_reminders),
        }

    def set_dnd(self, on):
        self.rhythm.set_dnd(on)

    def recalibrate(self):
        now = time.time()
        self.posture.recalibrate()
        self.eyecare.baseline_eye_px = None
        self.eyecare._calib.clear()

    def stop(self):
        self._stop.set()
