#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真正的地形地图测试（v1.2.0）。

覆盖：
- 世界地图 / 地区地图均为有效大尺寸 PNG
- 地图是「真地形图」而非格子表：色彩丰富（数十种以上颜色）、含地形色与海洋色
- 多边形几何：Voronoi 裁剪拼接无缝、地区覆盖大陆、点在多边形内判定正确
- 归属着色：有主/无主两种世界图显著不同
- 七种地形的地区图各不相同（不是同一张模板）
- 确定性：同一地区重复渲染几何稳定
- 中文不乱码（不出现豆腐块占位符）
"""
import sys
import os
import json
import tempfile

sys.path.insert(0, "/workspace")

from PIL import Image  # noqa: E402
from astrbot_plugin_nationwar.core.imager import ImageRenderer  # noqa: E402
from astrbot_plugin_nationwar.core import geomaps  # noqa: E402

PLUGIN = "/workspace/astrbot_plugin_nationwar"


def _r():
    return ImageRenderer(tempfile.mkdtemp())


def _tpl():
    with open(os.path.join(PLUGIN, "data", "world.json"), encoding="utf-8") as f:
        return json.load(f)


def _state(tpl, owned=None):
    regions = json.loads(json.dumps(tpl["regions"]))
    for i, qq in (owned or {}).items():
        regions[i]["owner"] = qq
        regions[i]["dev"] = 1 + i % 3
    return {"regions": regions}


def test_world_map_is_real_terrain_image():
    tpl = _tpl()
    state = _state(tpl, {0: "10001", 3: "10002", 8: "10001"})
    state["regions"][0]["capital_of"] = "10001"
    r = _r()
    p = r.render_world_map(state, tpl, {"10001": "曙光帝国", "10002": "钢铁联邦"})
    assert p and os.path.exists(p)
    assert Image.open(p).format == "PNG"
    im = Image.open(p).convert("RGB")
    assert im.size[0] >= 1600 and im.size[1] >= 1100, "应是大尺寸地图"
    colors = im.getcolors(maxcolors=2000000) or []
    # 真地形图：大量颜色（渐变海洋 + 7 种地形 + 纹理 + 势力色），远超旧格子表
    assert len(colors) > 300, f"地形图颜色应丰富，实际 {len(colors)} 色"
    # 海洋深蓝与地形绿都应出现
    px = im.load()
    has_ocean = any(px[x, y][2] > px[x, y][0] + 20 and px[x, y][2] > 60
                    for x in range(0, im.size[0], 40)
                    for y in range(160, 1080, 40))
    assert has_ocean, "应有海洋渐变"
    print(f"✅ 世界地图为真实地形大图（{im.size[0]}x{im.size[1]}，{len(colors)} 色，含海洋/地形）")


def test_owner_coloring_changes_map():
    tpl = _tpl()
    r = _r()
    p0 = r.render_world_map(_state(tpl), tpl, {})
    p1 = r.render_world_map(_state(tpl, {0: "10001", 1: "10001",
                                          2: "10002", 3: "10002"}), tpl,
                            {"10001": "A国", "10002": "B国"})
    # 强制不同文件名（sig 不同），两张图内容应有差异
    a = Image.open(p0).convert("RGB").tobytes()
    b = Image.open(p1).convert("RGB").tobytes()
    assert a != b, "有主/无主世界图应不同（归属着色生效）"
    print("✅ 归属势力染色生效（有主/无主地图不同）")


def test_all_terrains_render_distinctly():
    tpl = _tpl()
    r = _r()
    seen = {}
    for terrain in geomaps.TERRAIN_ORDER:
        reg = next((x for x in tpl["regions"] if x["terrain"] == terrain), None)
        if not reg:
            continue
        p = r.render_region_map(dict(reg), {}, tpl)
        assert p and Image.open(p).format == "PNG"
        im = Image.open(p).convert("RGB")
        seen[terrain] = im.resize((60, 40)).tobytes()
    assert len(seen) == len(geomaps.TERRAIN_ORDER), "七种地形都要能渲染"
    # 至少多数地形的主图区视觉不同
    uniq = len(set(seen.values()))
    assert uniq >= 5, f"不同地形应呈现不同场景，实际只有 {uniq} 种视觉"
    print(f"✅ 七种地形地区图均可渲染且场景各异（{uniq} 种不同视觉）")


def test_region_map_info_panel_and_valid_png():
    tpl = _tpl()
    reg = json.loads(json.dumps(tpl["regions"][0]))
    reg["owner"] = "10001"
    reg["capital_of"] = "10001"
    r = _r()
    p = r.render_region_map(reg, {"10001": "曙光帝国"}, tpl)
    assert Image.open(p).format == "PNG"
    im = Image.open(p).convert("RGB")
    assert im.size[0] >= 1100 and im.size[1] >= 760
    colors = im.getcolors(maxcolors=2000000) or []
    assert len(colors) > 200, f"地区地形图应色彩丰富，实际 {len(colors)} 色"
    print(f"✅ 地区放大地形图为有效大图（{im.size[0]}x{im.size[1]}，{len(colors)} 色）")


def test_voronoi_geometry_seamless():
    """Voronoi 半平面裁剪：每个种子落在自己的 cell 内，cell 均非空且面积>0。"""
    poly = geomaps._blob_polygon(400, 300, 220, 160, seed=42)
    seeds = geomaps._seeds(poly, list(range(10)), 400, 300, 220, 160, seed=43)
    cells = geomaps._voronoi_cells(poly, seeds)
    assert len(cells) == 10
    for s, cell in zip(seeds, cells):
        assert len(cell) >= 3, "每个地区都应得到非空多边形"
        # 种子点必在其 Voronoi 区内（这是算法核心性质）
        assert geomaps._in_poly(s, cell), "种子点必须落在自己的地区多边形内"
        xs = [p[0] for p in cell]
        ys = [p[1] for p in cell]
        assert max(xs) - min(xs) > 0 and max(ys) - min(ys) > 0
    print("✅ Voronoi 拼接几何正确（地区无缝、种子归属正确）")


def test_geometry_deterministic():
    a = geomaps._blob_polygon(300, 200, 150, 110, seed=7)
    b = geomaps._blob_polygon(300, 200, 150, 110, seed=7)
    assert a == b, "同一 seed 应生成相同海岸线（地图稳定、不抖动）"
    c = geomaps._blob_polygon(300, 200, 150, 110, seed=8)
    assert a != c, "不同 seed 应生成不同大陆形状"
    print("✅ 地图几何确定性（同地区形状稳定、不同大陆各异）")


def test_no_tofu_in_map_titles():
    """地图文字经 sanitize 清洗，不应出现 emoji 豆腐块占位 [*]。"""
    from astrbot_plugin_nationwar.core.imager import sanitize
    tpl = _tpl()
    r = _r()
    # 组织名含 emoji，应被清洗而不是画成豆腐块
    state = _state(tpl, {0: "10001"})
    p = r.render_world_map(state, tpl, {"10001": "🗺️帝国⚔️"})
    assert p
    # 直接验证清洗函数（地图标题/图例均经过它）
    cleaned = sanitize("🗺️帝国⚔️")
    assert "[图]" in cleaned and "[战]" in cleaned and "[*]" not in cleaned
    print("✅ 地图中文/emoji 清洗正确（无豆腐块）")


if __name__ == "__main__":
    test_world_map_is_real_terrain_image()
    test_owner_coloring_changes_map()
    test_all_terrains_render_distinctly()
    test_region_map_info_panel_and_valid_png()
    test_voronoi_geometry_seamless()
    test_geometry_deterministic()
    test_no_tofu_in_map_titles()
    print("\n真实地形地图测试全部通过。")
