# -*- coding: utf-8 -*-
"""生成桌面图标 app.ico：深色圆底 + 绿色'关怀'心形 + 摄像头光点。"""
from PIL import Image, ImageDraw
from pathlib import Path

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 圆角深色底盘
d.rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=52,
                    fill=(24, 28, 38, 255), outline=(60, 70, 90, 255), width=4)

# 绿色心形(关怀)——两个圆 + 一个三角
cx, cy = SIZE // 2, 112
r = 40
green = (95, 205, 120, 255)
d.ellipse([cx - 2 * r, cy - r, cx, cy + r], fill=green)
d.ellipse([cx, cy - r, cx + 2 * r, cy + r], fill=green)
d.polygon([(cx - 2 * r + 6, cy + 20), (cx + 2 * r - 6, cy + 20), (cx, cy + 2 * r + 28)],
          fill=green)

# 镜头光点(摄像头感知)
d.ellipse([cx - 16, cy - 8, cx + 16, cy + 24], fill=(24, 28, 38, 255))
d.ellipse([cx - 8, cy, cx + 8, cy + 16], fill=(120, 230, 150, 255))

# 底部"在场"三个律动条
bar_y = 196
for i, h in enumerate([26, 40, 30]):
    x = cx - 34 + i * 28
    d.rounded_rectangle([x, bar_y + (40 - h), x + 16, bar_y + 40], radius=6,
                        fill=(90, 170, 240, 255))

out = Path(__file__).parent / "app.ico"
img.save(out, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon ->", out)
