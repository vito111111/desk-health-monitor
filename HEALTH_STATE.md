# 健康状态契约 (health_state) — 系统脊柱

把"摄像头 / 手表 / 手柄 / 体脂秤…"等零散健康数据源,收敛成**一个统一状态**:
传感器是写入插件,桌宠/语音/周报是只读渲染器,中间靠 `health_state` 解耦。
加任何新硬件 = 多写一个源文件,**不动渲染端一行代码**。

## 数据流

```
传感器层(各写各的, 互不覆盖)        统一状态目录                   渲染层(只读聚合)
worker-monitor 摄像头 ─┐    ~/.claude/health/camera.json     ┌─ claude-pet 桌宠
sensors/watch_stub.py ─┼──▶ ~/.claude/health/watch.json   ──┼─ (语音/周报 未来)
未来 手柄/体脂秤/水杯  ─┘    ~/.claude/health/*.json           └─ read_state() 聚合
                        ~/.claude/pet_health.json (旧单文件, 摄像头兼容续写, 老版宠物可用)
```

## 契约文件 `health_state.py`

worker-monitor 与 claude-pet **各持一份完全相同的副本**(线协议),改动需同步,`SCHEMA` 变更双方同升级。

- 写端 `SourceWriter(source, also_legacy=False)` → `.write(present=, factors=, metrics=, event=)`
  原子写 `~/.claude/health/<source>.json`;`also_legacy=True`(仅摄像头)同时续写旧单文件。
- 读端 `read_state()` → 聚合所有**在线**源:因素去重合并、严重度取最高(alert>warn>ok)、
  推导 `vitality`(0-100 元气值)、挑最新 `event`;全离线回退旧文件,仍无 → `None`。

### 单源文件结构 `~/.claude/health/<source>.json`
```json
{"schema":"health_state/2","source":"camera","ts":1700000000.0,
 "present":true,"factors":["slouch","need_move"],
 "metrics":{"seated_minutes":95},
 "event":{"id":"camera:1","type":"need_move","title":"…","body":"…","routine":"full"}}
```

### 聚合输出 `read_state()`
```json
{"schema":"health_state/2","ts":...,"present":true,
 "factors":["slouch","need_move","sleep_debt"],"severity":"warn","vitality":76,
 "event":{...},"online_sources":["camera","watch"],
 "sources":{"camera":{"ts":...,"factors":[...],"metrics":{...}}, "watch":{...}}}
```

## 源新鲜度
`camera` 等高频源 8s 未更新即离线;`watch` 6h、`scale` 7 天(低频源同步几次即可)。见 `SOURCE_STALE_SEC`。

## 因素 / 严重度 / 元气值
`SEVERITY` 表定义每个因素的档位,新因素加在这里即被聚合识别;渲染端(pet.py `HEALTH_INFO`)
对未知因素有兜底(显示 ⚠ "注意一下"),所以**新增源可渐进上线,不会让桌宠崩**。

## 新增一个数据源(以真实手表为例)
1. 复制 `sensors/watch_stub.py`,把 `_read_input()` 换成调小米/华为/佳明/Apple 健康的 API。
2. `python -m sensors.your_source` 跑起来(或挂进托盘/计划任务)。
3. 完成。桌宠的造型/颜色/元气会自动反映新源的因素,无需改 claude-pet。

## 验证
`python test_health_state.py` — 多源写入→聚合→去重/严重度/元气/过期离线 全链路冒烟。
