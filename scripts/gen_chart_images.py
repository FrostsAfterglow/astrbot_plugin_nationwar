#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把两张指令目录渲染成 PNG 大图（作为插件静态资源提交，运行时直接发送）。

  assets/commands_chart1.png  内政经济（图1，蓝）
  assets/commands_chart2.png  军事外交（图2，红）

用法： python3 scripts/gen_chart_images.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, PLUGIN)

from core.imager import ImageRenderer  # noqa: E402

with open(os.path.join(PLUGIN, "data", "commands.json"), encoding="utf-8") as f:
    CMDS = json.load(f)


def main():
    # 输出目录用一个固定临时目录即可；render_chart_image 会把成品写到 assets/
    r = ImageRenderer(os.path.join(PLUGIN, "data_runtime", "rendered"))
    if not r.available:
        print("ERROR: Pillow 或字体不可用，无法生成指令图", file=sys.stderr)
        return 1
    p1 = r.render_chart_image(
        1, CMDS, "■ 指令图一 · 内政经济", "内政 · 经济 · 建筑 · 科技 · 政策", theme="blue")
    p2 = r.render_chart_image(
        2, CMDS, "■ 指令图二 · 军事外交", "军事 · 外交 · 地图 · 谍报 · 系统", theme="red")
    for p in (p1, p2):
        if not p or not os.path.exists(p):
            print("ERROR: 图片未生成", p, file=sys.stderr)
            return 1
        from PIL import Image
        im = Image.open(p)
        print(f"已生成 {p}  {im.size[0]}x{im.size[1]}  {os.path.getsize(p)//1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
