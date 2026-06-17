# -*- coding: utf-8 -*-
"""共享几何/关键点工具。"""
import math
import numpy as np
import cv2

# Face Mesh 关键点索引
LEFT_EYE = [33, 160, 158, 133, 153, 144]
RIGHT_EYE = [362, 385, 387, 263, 373, 380]
MOUTH = {"top": 13, "bottom": 14, "left": 78, "right": 308}
# 双眼外角 (用于估算与屏幕的距离)
EYE_OUTER_L = 33
EYE_OUTER_R = 263
# 额头 ROI 角点 (rPPG 取肤色区), 用 face mesh 上额区域
FOREHEAD = [10, 67, 297, 109, 338]
# 头部姿态 solvePnP
POSE_IDS = [1, 152, 33, 263, 61, 291]


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def eye_aspect_ratio(pts, ids):
    p = [pts[i] for i in ids]
    vert = dist(p[1], p[5]) + dist(p[2], p[4])
    horz = 2.0 * dist(p[0], p[3])
    return vert / horz if horz > 0 else 0.0


def mouth_aspect_ratio(pts):
    vert = dist(pts[MOUTH["top"]], pts[MOUTH["bottom"]])
    horz = dist(pts[MOUTH["left"]], pts[MOUTH["right"]])
    return vert / horz if horz > 0 else 0.0


_POSE_MODEL = np.array([
    [0.0, 0.0, 0.0], [0.0, -63.6, -12.5], [-43.3, 32.7, -26.0],
    [43.3, 32.7, -26.0], [-28.9, -28.9, -24.1], [28.9, -28.9, -24.1],
], dtype=np.float64)


def head_pose(pts, w, h):
    """返回 (yaw, pitch) 角度。yaw>0 看右，pitch>0 低头(近似)。"""
    image_pts = np.array([[pts[i][0], pts[i][1]] for i in POSE_IDS], dtype=np.float64)
    cam = np.array([[w, 0, w / 2.0], [0, w, h / 2.0], [0, 0, 1]], dtype=np.float64)
    ok, rvec, tvec = cv2.solvePnP(_POSE_MODEL, image_pts, cam, np.zeros((4, 1)),
                                  flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        return 0.0, 0.0
    rot, _ = cv2.Rodrigues(rvec)
    sy = math.sqrt(rot[0, 0] ** 2 + rot[1, 0] ** 2)
    pitch = math.degrees(math.atan2(-rot[2, 0], sy))
    yaw = math.degrees(math.atan2(rot[1, 0], rot[0, 0]))
    if yaw > 90:
        yaw -= 180
    elif yaw < -90:
        yaw += 180
    return yaw, pitch
