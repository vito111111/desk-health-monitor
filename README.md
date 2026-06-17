# 桌前健康关怀助手 · desk-health-monitor

> 给长期在电脑前工作的人，一个**只服务你自己**的本地健康助手。
> 用笔记本自带摄像头，在本机实时关怀你的疲劳、坐姿、用眼、压力与作息——
> **不录像、不截图、不上传、不调用任何大模型**，纯本地运行，断网照常工作。

这不是"监控员工"的工具，而是面向**使用者本人**的健康关怀：它把摄像头看到的，
即时算成"该歇会儿了""坐直一点""光线太暗了"这样的温柔提醒，并能联动桌面宠物
做 10 秒弹窗与跟练引导。

## 关怀什么

| 模块 | 看什么 | 怎么帮你 |
|---|---|---|
| **疲劳监测** | EAR 闭眼时长、PERCLOS、打哈欠(MAR)、眨眼频率 | 犯困了提醒接杯水、深呼吸 |
| **久坐坐姿** | 肩部倾斜(高低肩)、颈部前探(驼背/含胸)、头偏、体侧倾、久坐时长 | 高低肩/驼背逐项识别并提示拉平、沉肩 |
| **用眼健康** | 用屏时长、人脸距屏距离、干眼(眨眼变少) | 20 分钟远眺、离屏幕远一点、多眨眼 |
| **在场感知** | 是否在座、专注/分心 | 专注时间线统计，离岗自动暂停打扰 |
| **心率压力(rPPG)** | 摄像头远程光电容积脉搏波估心率/压力 | 状态紧绷时引导深呼吸 |
| **情绪紧张度** | 面部 blendshapes(皱眉/眯眼/抿嘴) | 紧张趋势归档，长期看曲线 |
| **环境光护眼** | 画面平均亮度 | 光线偏暗提示开灯/调亮 |
| **智能节律** | 说话检测→会议模式、勿扰/免打扰时段、自然停顿延迟打扰 | 开会/专注时不打断，停顿时才提醒 |
| **健康分 + 趋势** | 综合 focus/posture/calm/relax/move 五维 | 每日健康分、连续达标天数，自动写日报到 Obsidian |

## 隐私设计（核心原则）

- **不落盘任何视频/图像**：摄像头帧只在内存实时分析，预览仅在本机 `127.0.0.1`。
- **只存状态指标**：SQLite 里只有"专注/疲劳/坐姿"等数字，没有任何画面。
- **不联网、无大模型**：全部是计算机视觉 + 信号处理 + 规则，断网照常用
  （仅首次需联网下载 MediaPipe 模型，之后纯离线）。
- **不上传**：除非你主动 `git push`，数据不离开本机。

## 安装与运行

```bash
pip install -r requirements.txt
```

首次运行需联网下载 MediaPipe 模型到 `models/`（约 9 MB，仅一次）：
`face_landmarker.task` 与 `pose_landmarker_lite.task`（MediaPipe 官方模型）。

**桌面客户端（推荐）**——原生窗口 + 系统托盘，不占浏览器标签：
```bash
pythonw client.py
```
或双击桌面图标 `app.ico` / 用 `控制中心.ps1` 菜单启动/停止。

**纯看板模式**：
```bash
python app.py        # 浏览器打开 http://127.0.0.1:5005
```

## 与桌面宠物联动（可选）

配合 [claude-pet](https://github.com/vito111111/claude-pet)（同机的桌面像素火花宠物）：
不健康因素会让宠物**变色/变形**，健康建议以**10 秒自动消失弹窗**呈现；
点击"起来动一动"，宠物会**居中放大做跟练引导**（Ring Fit 风格的深蹲/颈肩放松/深呼吸）。
通过本地文件 `~/.claude/pet_health.json` 通信，宠物未运行时无副作用。

## 文件结构

```
worker-monitor/
├── client.py        # 原生桌面客户端（WebView2 + 托盘），推荐入口
├── app.py           # Flask 看板 + 启动监控线程
├── monitor.py       # 核心编排：取帧→各模块分析→状态机→提醒→桥接宠物
├── modules/
│   ├── vision.py    # MediaPipe FaceLandmarker/PoseLandmarker(Tasks API)
│   ├── fatigue.py   # 疲劳：EAR/PERCLOS/MAR/眨眼
│   ├── posture.py   # 坐姿：肩倾/颈探/头偏/体倾，多指标+平滑+滞回+校准
│   ├── eyecare.py   # 用眼：时长/距离/干眼
│   ├── presence.py  # 在场/专注分心
│   ├── rppg.py      # 心率压力(远程 PPG)
│   ├── affect.py    # 情绪紧张度(blendshapes)
│   ├── env.py       # 环境光检测
│   ├── rhythm.py    # 智能节律：会议/勿扰/自然停顿延迟
│   └── geom.py      # 头部姿态等几何
├── reminders.py     # 提醒文案 + 冷却节流
├── pet_bridge.py    # 桥接桌面宠物（写 pet_health.json）
├── storage.py       # SQLite：状态事件、采样、健康分、连续达标
├── report.py        # 每日健康日报(Markdown)写入 Obsidian
├── config.json      # 全部阈值与开关
├── 控制中心.ps1     # 启动/停止菜单
└── requirements.txt
```

## 配置要点 `config.json`

阈值因人/摄像头/光线而异，可在看板观察实时值后微调。常用项：

| 字段 | 含义 | 默认 |
|---|---|---|
| `camera_index` | 摄像头序号 | 0 |
| `eye_break_minutes` | 多久提醒远眺一次 | 20 |
| `sedentary_minutes` | 久坐多久提醒起身 | 45 |
| `posture.*` | 高低肩/驼背等阈值、平滑、滞回、校准帧数 | 见文件 |
| `rhythm.quiet_hours` / `rhythm.dnd` | 免打扰时段 / 一键勿扰 | [] / false |
| `daily_report` / `obsidian_health_dir` | 是否写每日健康日报 / 写到哪 | true / Obsidian |
| `pet_integration` | 是否联动桌面宠物 | true |
| `privacy_no_video_save` | 不保存视频（始终生效） | true |

## 技术栈

MediaPipe Tasks API（FaceLandmarker 478 点 + iris + 52 blendshapes、PoseLandmarker 33 点）、
OpenCV、SciPy（rPPG 滤波/FFT）、Flask、pywebview(WebView2)、pystray、SQLite、Python 3.13。

## 许可

MIT。仅供个人健康管理；若用于多人场景请提前告知并征得同意，遵守当地法律。
