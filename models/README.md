# MediaPipe 模型

本目录的 `.task` 模型文件较大，未随仓库分发。**首次运行前**下载到本目录即可
（仅这一次需要联网，之后纯离线运行）：

| 文件 | 下载地址 |
|---|---|
| `face_landmarker.task` | https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task |
| `pose_landmarker_lite.task` | https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task |

PowerShell 一键下载：

```powershell
$base = "https://storage.googleapis.com/mediapipe-models"
iwr "$base/face_landmarker/face_landmarker/float16/1/face_landmarker.task" -OutFile face_landmarker.task
iwr "$base/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task" -OutFile pose_landmarker_lite.task
```
