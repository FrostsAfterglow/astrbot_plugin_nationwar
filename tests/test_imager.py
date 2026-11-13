#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图片渲染器单测：中文渲染、emoji 清洗、超长分页、PNG 有效、指令图/地图生成。"""
import sys
import os
import json
import tempfile

sys.path.insert(0, "/workspace")

from PIL import Image  # noqa: E402
from astrbot_plugin_nationwar.core.imager import (  # noqa: E402
    ImageRenderer, sanitize, THEMES,
)

PLUGIN = "/workspace/astrbot_plugin_nationwar"


def _r():
    return ImageRenderer(tempfile.mkdtemp())


def test_renderer_available_with_bundled_font():
    r = _r()
    assert r.available, "随插件打包的中文字体应可用（用户机器无需装字体）"
    assert r.font_path and os.path.exists(r.font_path)
    print("✅ 渲染器可用，字体随插件打包")


def test_sanitize_emoji():
    s = sanitize("🗺️ 世界地图 ⚔️ 进攻 ✅ 完成 💰 资金")
    assert "🗺" not in s and "⚔" not in s and "✅" not in s and "💰" not in s
    assert "[图]" in s and "[战]" in s and "[√]" in s and "[金]" in s
    assert "世界地图" in s and "资金" in s
    print("✅ emoji/稀有符号清洗为字体可渲染标签（无豆腐块）")


def test_chinese_text_png_valid():
    r = _r()
    pages = r.render_text("国家战争：资金 1000｜粮食 1000｜石油 200\n【资源】稀有金属 50｜科技点 50",
                          title="服务器状态")
    assert pages
    for p in pages:
        im = Image.open(p)
        assert im.format == "PNG" and im.size[0] >= 800
        # 非纯色（说明确实画了内容）
        assert len(im.convert("RGB").getcolors(maxcolors=1000000) or []) > 3
    print("✅ 中文文本渲染为有效 PNG（非空白图）")


def test_long_text_paginates():
    r = _r()
    text = "\n".join(f"第{i}行：这是一条用于测试的中文文本，包含资源与数值 12345。" for i in range(120))
    pages = r.render_text(text, title="超长帮助", max_lines_per_page=26)
    assert len(pages) >= 5, f"应自动分页，实际 {len(pages)} 页"
    for p in pages:
        assert Image.open(p).format == "PNG"
    print(f"✅ 超长文本自动分页为 {len(pages)} 张图片")


def test_both_themes():
    r = _r()
    for theme in ("blue", "red"):
        p = r.render_text("测试主题配色", title="主题", theme=theme)[0]
        assert Image.open(p).format == "PNG"
    assert "blue" in THEMES and "red" in THEMES
    print("✅ 蓝/红两主题均可用")


def test_chart_images_generation():
    with open(os.path.join(PLUGIN, "data", "commands.json"), encoding="utf-8") as f:
        cmds = json.load(f)
    r = _r()
    p1 = r.render_chart_image(1, cmds, "■ 指令图一 · 内政经济", "内政经济", "blue")
    p2 = r.render_chart_image(2, cmds, "■ 指令图二 · 军事外交", "军事外交", "red")
    for p in (p1, p2):
        assert p and os.path.exists(p)
        im = Image.open(p)
        assert im.format == "PNG" and im.size[0] == 1600
    print("✅ 两张指令图可由数据目录现场渲染（静态资源缺失时兜底）")


def test_world_and_region_map():
    with open(os.path.join(PLUGIN, "data", "world.json"), encoding="utf-8") as f:
        tpl = json.load(f)
    state = {"regions": tpl["regions"]}
    # 造两个归属，验证着色分支
    state["regions"][0]["owner"] = "10001"
    state["regions"][1]["owner"] = "10002"
    r = _r()
    pw = r.render_world_map(state, tpl)
    assert pw and Image.open(pw).format == "PNG"
    pr = r.render_region_map(state["regions"][0])
    assert pr and Image.open(pr).format == "PNG"
    print("✅ 世界地图 / 区域地图均可渲染为 PNG（含归属着色）")


def test_static_chart_assets_exist():
    for p in (os.path.join(PLUGIN, "assets", "commands_chart1.png"),
              os.path.join(PLUGIN, "assets", "commands_chart2.png")):
        assert os.path.exists(p), f"缺少静态指令图资源 {p}"
        assert Image.open(p).format == "PNG"
    print("✅ 两张静态指令图资源已随插件提供")


if __name__ == "__main__":
    test_renderer_available_with_bundled_font()
    test_sanitize_emoji()
    test_chinese_text_png_valid()
    test_long_text_paginates()
    test_both_themes()
    test_chart_images_generation()
    test_world_and_region_map()
    test_static_chart_assets_exist()
    print("\n图片渲染器测试通过。")
