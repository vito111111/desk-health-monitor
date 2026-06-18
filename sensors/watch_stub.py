# -*- coding: utf-8 -*-
"""手动/桥接手表源(示例 + 兜底) —— 读用户可手编的输入文件, 不接硬件。

    ~/.claude/health_inputs/watch.json   例如 {"sleep_min":300,"resting_hr":72,"steps":1200}

用途: ①没接真实表时手填数据试通链路; ②任何"用别的方式拿到数据再喂进来"的桥接出口。
真实接表见 garmin_source.py / amazfit_source.py。

运行:  python -m sensors.watch_stub
"""
import os
import json

from sensors.wearable import WearableSource

INPUT_FILE = os.path.join(os.path.expanduser("~"), ".claude",
                          "health_inputs", "watch.json")


class WatchSource(WearableSource):
    name = "watch"
    interval = 300.0

    def fetch(self, now):
        try:
            with open(INPUT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        return {k: data[k] for k in ("sleep_min", "resting_hr", "steps")
                if k in data}


if __name__ == "__main__":
    WatchSource().run_loop()
