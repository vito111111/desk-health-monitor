# -*- coding: utf-8 -*-
"""MediaPipe Tasks API 封装 (0.10.35 已移除旧版 solutions)。
   提供 FaceLandmarker / PoseLandmarker 的构建与帧推理(VIDEO 模式)。"""
from pathlib import Path

import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

MODELS = Path(__file__).parent.parent / "models"


def _to_mp_image(rgb):
    return mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)


class FaceLandmarkerWrap:
    """468/478 点人脸网格(含虹膜)。VIDEO 模式，需单调递增时间戳。"""
    def __init__(self):
        opts = mp_vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(
                model_asset_path=str(MODELS / "face_landmarker.task")),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_faces=1, min_face_detection_confidence=0.5,
            min_tracking_confidence=0.5,
            output_face_blendshapes=True)   # 52 维表情系数(情绪/紧张度)
        self.lm = mp_vision.FaceLandmarker.create_from_options(opts)
        self.last_blendshapes = None        # detect 后存最近一帧表情系数

    def detect(self, rgb, ts_ms):
        res = self.lm.detect_for_video(_to_mp_image(rgb), ts_ms)
        self.last_blendshapes = (res.face_blendshapes[0]
                                 if res.face_blendshapes else None)
        if res.face_landmarks:
            return res.face_landmarks[0]   # list[NormalizedLandmark]
        return None

    def close(self):
        self.lm.close()


class PoseLandmarkerWrap:
    """33 点人体姿态(轻量模型)。"""
    def __init__(self):
        opts = mp_vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(
                model_asset_path=str(MODELS / "pose_landmarker_lite.task")),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_poses=1, min_pose_detection_confidence=0.5,
            min_tracking_confidence=0.5)
        self.lm = mp_vision.PoseLandmarker.create_from_options(opts)

    def detect(self, rgb, ts_ms):
        res = self.lm.detect_for_video(_to_mp_image(rgb), ts_ms)
        if res.pose_landmarks:
            return res.pose_landmarks[0]
        return None

    def close(self):
        self.lm.close()
