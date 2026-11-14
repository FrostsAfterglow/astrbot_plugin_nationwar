# -*- coding: utf-8 -*-
"""真正的地形地图渲染（纯 Pillow，无 numpy / scipy 硬依赖）。

v1.2.0：把原来的「格子表 / 方框」升级为具备真实地理观感的地图：
- 世界地图：不规则大陆海岸线 + Voronoi 半平面裁剪拼接出的地区边界 +
  地形着色与纹理符号（山峰/树林/沙丘/浪线/田块/等高线）+ 归属势力染色 +
  首都星标 + 资源点 + 地区名/编号 + 海洋渐变 + 经纬网 + 罗盘 + 比例尺 + 图例
- 地区地图：单地区放大地形场景（层叠山脊 / 森林 / 沙丘海岸 / 农田 / 高原）+
  资源图标 + 城池/首都 + 防御塔楼 + 信息面板 + 罗盘比例尺

算法要点：地区边界用「Voronoi 半平面裁剪」精确生成（对大陆多边形依次用
与其他种子点的垂直平分线做 Sutherland–Hodgman 裁剪），得到锐利、无缝拼接的
多边形地块，比像素距离场更清晰，且完全不依赖第三方科学计算库。
"""
from __future__ import annotations

import math
import os
import random
from typing import Callable

try:
    from PIL import Image, ImageDraw
    _HAS_PIL = True
except Exception:  # pragma: no cover
    _HAS_PIL = False


def _passthrough(t: str) -> str:
    return t or ""


# ---------------------------------------------------------------------------
# 配色
# ---------------------------------------------------------------------------
OCEAN_TOP = (22, 54, 88)
OCEAN_BOT = (8, 22, 44)
GRID = (40, 78, 116)
COAST = (92, 156, 184)      # 近岸浅海
SAND = (216, 206, 158)      # 沙滩带
BORDER = (48, 54, 50)       # 地区边界

TERRAIN_COLORS = {
    "平原": (128, 172, 102),
    "森林": (58, 114, 74),
    "山地": (146, 134, 120),
    "沙漠": (216, 190, 126),
    "沿海": (186, 200, 150),
    "高原": (172, 142, 106),
    "岛屿": (112, 172, 152),
}
TERRAIN_ORDER = ["平原", "森林", "山地", "沙漠", "沿海", "高原", "岛屿"]

OWNER_PALETTE = [
    (233, 88, 88), (86, 196, 214), (240, 190, 86), (168, 128, 232),
    (96, 206, 132), (240, 140, 96), (120, 160, 240), (226, 120, 180),
    (200, 220, 96), (96, 214, 200),
]
RESOURCE_COLORS = {
    "food": (150, 210, 90), "oil": (70, 76, 92), "rare": (178, 120, 232),
    "metal": (232, 150, 80), "none": None,
}
RESOURCE_CN = {"food": "粮食", "oil": "石油", "rare": "稀有金属",
               "metal": "金属", "none": "无"}

# 6 块大陆在世界画布（地图区）中的相对中心
CONT_LAYOUT = {
    "北境": (0.18, 0.26), "霜原": (0.50, 0.19), "远星": (0.83, 0.28),
    "中土": (0.24, 0.70), "烈日": (0.55, 0.73), "瀚海": (0.84, 0.68),
}


# ---------------------------------------------------------------------------
# 几何工具
# ---------------------------------------------------------------------------
def _blob_polygon(cx, cy, rx, ry, seed, n=64, irregular=0.22):
    """生成带自然凹凸的不规则大陆海岸线多边形。"""
    rnd = random.Random(seed)
    p0, p1, p2 = (rnd.uniform(0, 2 * math.pi) for _ in range(3))
    pts = []
    for k in range(n):
        t = 2 * math.pi * k / n
        wobble = (1 + irregular * (0.50 * math.sin(3 * t + p0)
                                  + 0.30 * math.sin(5 * t + p1)
                                  + 0.20 * math.sin(7 * t + p2))
                  + rnd.uniform(-0.035, 0.035))
        pts.append((cx + rx * wobble * math.cos(t),
                    cy + ry * wobble * math.sin(t)))
    return pts


def _in_poly(pt, poly) -> bool:
    x, y = pt
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _clip_halfplane(poly, d, c):
    """Sutherland–Hodgman：保留 dot(p,d) >= c 的半平面部分。"""
    if not poly:
        return []
    out = []
    n = len(poly)
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        fa = a[0] * d[0] + a[1] * d[1] - c
        fb = b[0] * d[0] + b[1] * d[1] - c
        ia, ib = fa >= 0, fb >= 0
        if ia:
            out.append(a)
        if ia != ib:
            t = fa / (fa - fb) if (fa - fb) != 0 else 0.0
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _voronoi_cells(cont_poly, seeds):
    """把大陆多边形按种子点切成 Voronoi 地区多边形（精确、无缝）。"""
    cells = []
    for i, si in enumerate(seeds):
        cell = list(cont_poly)
        for j, sj in enumerate(seeds):
            if i == j:
                continue
            d = (si[0] - sj[0], si[1] - sj[1])
            c = ((si[0] ** 2 + si[1] ** 2) - (sj[0] ** 2 + sj[1] ** 2)) / 2.0
            cell = _clip_halfplane(cell, d, c)
            if len(cell) < 3:
                break
        cells.append(cell if len(cell) >= 3 else [])
    return cells


def _seeds(cont_poly, regions, cx, cy, rx, ry, seed):
    """在大陆内用黄金角螺旋布置地区种子点（确定性、分布均匀）。"""
    rnd = random.Random(seed)
    n = max(1, len(regions))
    golden = math.pi * (3 - math.sqrt(5))
    pts = []
    for i in range(n):
        rr = 0.66 * math.sqrt((i + 0.5) / n)
        a = i * golden + rnd.uniform(-0.14, 0.14)
        x = cx + rx * rr * math.cos(a)
        y = cy + ry * rr * math.sin(a)
        for _ in range(8):
            if _in_poly((x, y), cont_poly):
                break
            x = cx + (x - cx) * 0.82
            y = cy + (y - cy) * 0.82
        pts.append((x, y))
    return pts


def _star(cx, cy, r, r2=None, n=5, rot=-math.pi / 2):
    r2 = r2 or r * 0.45
    pts = []
    for i in range(n * 2):
        ang = rot + i * math.pi / n
        rr = r if i % 2 == 0 else r2
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    return pts


def _shade(color, factor):
    return tuple(max(0, min(255, int(v * factor))) for v in color)


def _clip_text(draw, text, font, maxw):
    if draw.textlength(text, font=font) <= maxw:
        return text
    s = text
    while s and draw.textlength(s + "…", font=font) > maxw:
        s = s[:-1]
    return (s + "…") if s else ""


def _owner_color(qq, index=None):
    if index is not None:
        return OWNER_PALETTE[index % len(OWNER_PALETTE)]
    h = 0
    for ch in str(qq):
        h = (h * 31 + ord(ch)) & 0x7FFFFFFF
    return OWNER_PALETTE[h % len(OWNER_PALETTE)]


# ---------------------------------------------------------------------------
# 绘制组件
# ---------------------------------------------------------------------------
def _draw_ocean(img, d, W, H, top, bottom):
    """海洋渐变 + 经纬网 + 淡波纹。"""
    for y in range(top, bottom):
        t = (y - top) / max(1, bottom - top)
        c = tuple(int(OCEAN_TOP[k] + (OCEAN_BOT[k] - OCEAN_TOP[k]) * t) for k in range(3))
        d.line([(0, y), (W, y)], fill=c)
    # 经纬网
    step = 120
    for x in range(0, W, step):
        d.line([(x, top), (x, bottom)], fill=GRID, width=1)
    for y in range(top, bottom, step):
        d.line([(0, y), (W, y)], fill=GRID, width=1)
    # 波纹（短弧）
    rnd = random.Random(20261114)
    for _ in range(90):
        x = rnd.randint(20, W - 60)
        y = rnd.randint(top + 20, bottom - 20)
        ln = rnd.randint(18, 46)
        d.arc([x, y, x + ln, y + 8], 200, 340, fill=(46, 92, 128), width=2)


def _draw_compass(d, cx, cy, r, font):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(226, 236, 245), width=2)
    d.ellipse([cx - r * 0.72, cy - r * 0.72, cx + r * 0.72, cy + r * 0.72],
              outline=(150, 168, 200), width=1)
    d.polygon(_star(cx, cy - r * 0.12, r * 0.62, r * 0.16, 4, rot=0),
              fill=(233, 88, 88))
    d.text((cx - 6, cy - r - 22), "N", font=font, fill=(246, 196, 90))


def _draw_scalebar(d, x, y, font, total=260):
    seg = total // 2
    d.rectangle([x, y, x + seg, y + 9], fill=(232, 236, 245))
    d.rectangle([x + seg, y, x + total, y + 9], outline=(232, 236, 245), width=2)
    d.text((x, y + 14), "0", font=font, fill=(200, 214, 232))
    d.text((x + seg - 12, y + 14), "500", font=font, fill=(200, 214, 232))
    d.text((x + total - 28, y + 14), "1000 km", font=font, fill=(200, 214, 232))


def _draw_terrain_symbols(d, cell, terrain, seed, density=1.0):
    """在一个地区多边形内撒地形符号，贴合形状。"""
    if not cell:
        return
    xs = [p[0] for p in cell]
    ys = [p[1] for p in cell]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    area = (x1 - x0) * (y1 - y0)
    rnd = random.Random(seed)
    count = max(3, int(area / 1500 * density))
    placed = 0
    tries = 0
    while placed < count and tries < count * 8:
        tries += 1
        x = rnd.uniform(x0, x1)
        y = rnd.uniform(y0, y1)
        if not _in_poly((x, y), cell):
            continue
        placed += 1
        if terrain == "山地":
            d.polygon([(x, y - 9), (x - 8, y + 6), (x + 8, y + 6)],
                      fill=(108, 98, 88))
            d.polygon([(x, y - 9), (x - 3, y - 2), (x + 3, y - 2)],
                      fill=(232, 232, 226))
        elif terrain == "森林":
            d.line([(x, y + 7), (x, y - 1)], fill=(52, 44, 36), width=2)
            d.polygon([(x, y - 10), (x - 6, y + 3), (x + 6, y + 3)],
                      fill=(38, 88, 56))
        elif terrain == "沙漠":
            d.arc([x - 7, y - 3, x + 7, y + 5], 200, 340, fill=(196, 166, 96), width=2)
            d.ellipse([x + 8, y, x + 10, y + 2], fill=(196, 166, 96))
        elif terrain == "沿海":
            d.arc([x - 6, y - 2, x + 6, y + 4], 190, 350, fill=(120, 168, 176), width=2)
            d.arc([x - 6, y + 3, x + 6, y + 9], 190, 350, fill=(120, 168, 176), width=2)
        elif terrain == "平原":
            d.rectangle([x - 5, y - 4, x + 5, y + 4], outline=(150, 186, 118), width=1)
            d.line([(x, y - 4), (x, y + 4)], fill=(150, 186, 118), width=1)
        elif terrain == "高原":
            d.line([(x - 6, y + 3), (x + 2, y - 4)], fill=(140, 112, 82), width=2)
            d.line([(x - 2, y + 5), (x + 7, y - 2)], fill=(140, 112, 82), width=2)
        elif terrain == "岛屿":
            d.arc([x - 7, y - 3, x + 7, y + 5], 190, 350, fill=(150, 200, 190), width=2)


# ---------------------------------------------------------------------------
# 世界地图
# ---------------------------------------------------------------------------
def world_map(state: dict, tpl: dict, owners: dict, font: Callable,
              out_path: str, sanitize: Callable = _passthrough) -> str | None:
    """绘制完整虚拟世界地形地图，保存到 out_path 并返回路径。"""
    if not _HAS_PIL:
        return None
    regions = state.get("regions") or tpl.get("regions", [])
    conts = tpl.get("continents", [])
    W, H = 1720, 1200
    MARGIN, head_h, foot_h = 46, 150, 118
    map_top, map_bot = head_h, H - foot_h
    map_h = map_bot - map_top
    map_w = W - MARGIN * 2

    img = Image.new("RGB", (W, H), OCEAN_BOT)
    d = ImageDraw.Draw(img)
    _draw_ocean(img, d, W, H, map_top, map_bot)

    # 势力配色表（按首次出现顺序稳定分配）
    owner_index = {}
    for r in regions:
        o = str(r.get("owner", "") or "")
        if o and o not in owner_index:
            owner_index[o] = len(owner_index)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)

    by_cont = {}
    for r in regions:
        by_cont.setdefault(r.get("continent", "未知"), []).append(r)

    label_tasks = []  # (x, y, region, owner_color_or_None)
    for ci, cname in enumerate(conts):
        rs = by_cont.get(cname, [])
        if not rs:
            continue
        fx, fy = CONT_LAYOUT.get(cname, (0.5, 0.5))
        cx = MARGIN + map_w * fx
        cy = map_top + map_h * fy
        rx = 212 + (ci % 3) * 12
        ry = 152 + (ci % 2) * 16
        seed = sum(ord(ch) for ch in cname) * 7 + 11
        cont_poly = _blob_polygon(cx, cy, rx, ry, seed)
        seeds = _seeds(cont_poly, rs, cx, cy, rx, ry, seed + 1)
        cells = _voronoi_cells(cont_poly, seeds)

        # 近岸浅海 + 沙滩带
        d.polygon(cont_poly, fill=COAST)
        d.line(cont_poly + [cont_poly[0]], fill=SAND, width=7, joint="curve")

        for k, r in enumerate(rs):
            cell = cells[k] if k < len(cells) else []
            if len(cell) < 3:
                continue
            terrain = r.get("terrain", "平原")
            base = TERRAIN_COLORS.get(terrain, TERRAIN_COLORS["平原"])
            # 地形明暗斑块（用种子确定性）
            rnd = random.Random(int(r.get("id", k)) * 13 + 5)
            d.polygon(cell, fill=base)
            for _ in range(4):
                px = rnd.uniform(cx - rx, cx + rx)
                py = rnd.uniform(cy - ry, cy + ry)
                if _in_poly((px, py), cell):
                    d.ellipse([px - 22, py - 14, px + 22, py + 14],
                              fill=_shade(base, rnd.choice([0.9, 1.1])))
            _draw_terrain_symbols(d, cell, terrain,
                                  int(r.get("id", k)) * 31 + 3, density=0.9)
            d.line(cell + [cell[0]], fill=BORDER, width=2, joint="curve")

            o = str(r.get("owner", "") or "")
            ocol = _owner_color(o, owner_index.get(o)) if o else None
            if ocol:
                od.polygon(cell, fill=ocol + (78,))
                od.line(cell + [cell[0]], fill=ocol + (235,), width=4, joint="curve")

            # 标注点用种子点（必在其 Voronoi 区内）
            sx, sy = seeds[k]
            label_tasks.append((sx, sy, r, ocol))

    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    d = ImageDraw.Draw(img)

    # 地区标注：名称 + 编号 + 首都星 + 资源点
    f_name = font(17)
    f_id = font(14)
    for sx, sy, r, ocol in label_tasks:
        nm = sanitize(str(r.get("name", "")))[:4]
        rid = str(r.get("id", ""))
        # 名称（白字深描边）
        d.text((sx, sy - 20), nm, font=f_name, fill=(250, 250, 246),
               stroke_width=2, stroke_fill=(20, 28, 24))
        d.text((sx, sy - 1), "#" + rid, font=f_id, fill=(255, 226, 140),
               stroke_width=2, stroke_fill=(20, 28, 24))
        # 首都星标
        if r.get("capital_of"):
            d.polygon(_star(sx + 26, sy - 14, 9), fill=(255, 210, 90),
                      outline=(120, 80, 20))
        # 资源点
        rc = RESOURCE_COLORS.get(r.get("resource"), None)
        if rc:
            d.ellipse([sx - 30, sy + 12, sx - 22, sy + 20], fill=rc,
                      outline=(20, 28, 24), width=1)

    # ---- 标题栏 ----
    d.rectangle([0, 0, W, head_h], fill=(15, 20, 36))
    d.rectangle([0, 0, W, 8], fill=(79, 209, 197))
    title = sanitize("[图] " + str(tpl.get("name", "虚拟世界")) + " · 世界地形图")
    ft = font(46)
    d.text(((W - d.textlength(title, font=ft)) / 2, 30), title,
           font=ft, fill=(246, 196, 90))
    owned = sum(1 for r in regions if r.get("owner"))
    sub = (f"{len(conts)} 大陆 · {len(regions)} 地区 · {len(owner_index)} 势力 · "
           f"已占领 {owned} 地区 · 有色=势力范围 · 数字=地区编号")
    fs = font(21)
    d.text(((W - d.textlength(sub, font=fs)) / 2, 96), sanitize(sub),
           font=fs, fill=(150, 168, 200))
    d.line([(MARGIN, head_h - 12), (W - MARGIN, head_h - 12)], fill=(48, 62, 96), width=2)

    # ---- 罗盘 / 比例尺 ----
    _draw_compass(d, W - 92, map_top + 92, 46, font(18))
    _draw_scalebar(d, MARGIN + 12, map_bot - 44, font(16))

    # ---- 图例栏 ----
    d.rectangle([0, map_bot, W, H], fill=(15, 20, 36))
    d.line([(MARGIN, map_bot + 6), (W - MARGIN, map_bot + 6)], fill=(48, 62, 96), width=2)
    f_lg = font(18)
    lx, ly = MARGIN, map_bot + 22
    d.text((lx, ly), sanitize("地形："), font=f_lg, fill=(150, 168, 200))
    lx += 78
    for tn in TERRAIN_ORDER:
        d.rectangle([lx, ly + 2, lx + 20, ly + 20], fill=TERRAIN_COLORS[tn],
                    outline=(80, 96, 120), width=1)
        d.text((lx + 25, ly), sanitize(tn), font=f_lg, fill=(232, 236, 245))
        lx += 118
    # 第二行：势力 + 首都 + 说明
    ly2 = ly + 34
    lx = MARGIN
    d.text((lx, ly2), sanitize("势力："), font=f_lg, fill=(150, 168, 200))
    lx += 78
    shown = 0
    for qq, idx in list(owner_index.items())[:6]:
        col = _owner_color(qq, idx)
        label = sanitize(str(owners.get(qq, "") or ("QQ" + str(qq)[:4])))[:6]
        d.rectangle([lx, ly2 + 2, lx + 20, ly2 + 20], fill=col,
                    outline=(20, 28, 24), width=1)
        d.text((lx + 25, ly2), label, font=f_lg, fill=(232, 236, 245))
        lx += 42 + d.textlength(label, font=f_lg)
        shown += 1
    if not shown:
        d.text((lx, ly2), sanitize("（暂无势力，/注册 建国）"), font=f_lg,
               fill=(150, 168, 200))
    # 首都星 + 资源说明放在右侧
    rx0 = W - 430
    d.polygon(_star(rx0, ly2 + 10, 9), fill=(255, 210, 90))
    d.text((rx0 + 16, ly2), sanitize("首都"), font=f_lg, fill=(232, 236, 245))
    d.ellipse([rx0 + 96, ly2 + 3, rx0 + 106, ly2 + 13], fill=(178, 120, 232))
    d.text((rx0 + 112, ly2), sanitize("资源点  /区域地图 名称 查详情"),
           font=f_lg, fill=(150, 168, 200))

    foot = "国家战争插件 · 合成地形图 · 天童爱丽丝 (AL-1S)"
    ff = font(15)
    d.text((W - MARGIN - d.textlength(sanitize(foot), font=ff), H - 22),
           sanitize(foot), font=ff, fill=(110, 130, 165))

    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        img.save(out_path, "PNG")
        return out_path
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 单地区放大地形图
# ---------------------------------------------------------------------------
def region_map(region: dict, owners: dict, tpl: dict, font: Callable,
               out_path: str, sanitize: Callable = _passthrough) -> str | None:
    """绘制单个地区的放大地形场景，保存到 out_path 并返回路径。"""
    if not _HAS_PIL:
        return None
    W, H = 1180, 800
    head_h = 128
    img = Image.new("RGB", (W, H), (15, 20, 36))
    d = ImageDraw.Draw(img)

    # 主图区
    PX0, PY0, PX1, PY1 = 40, head_h, 800, H - 70
    pw, ph = PX1 - PX0, PY1 - PY0
    # 天空/底色
    for y in range(PY0, PY1):
        t = (y - PY0) / max(1, ph)
        c = (int(150 + 30 * t), int(186 + 20 * t), int(204 - 30 * t))
        d.line([(PX0, y), (PX1, y)], fill=c)

    terrain = region.get("terrain", "平原")
    base = TERRAIN_COLORS.get(terrain, TERRAIN_COLORS["平原"])
    rid = int(region.get("id", 0) or 0)
    rnd = random.Random(rid * 97 + 3)

    # 地区轮廓（占满主图区的大 blob）
    cx, cy = (PX0 + PX1) / 2, (PY0 + PY1) / 2
    poly = _blob_polygon(cx, cy, pw * 0.46, ph * 0.45, rid * 17 + 9,
                         n=72, irregular=0.16)
    d.polygon(poly, fill=COAST)
    d.line(poly + [poly[0]], fill=SAND, width=9, joint="curve")
    d.polygon(poly, fill=base)

    # 地形明暗斑块
    for _ in range(26):
        x = rnd.uniform(PX0 + 40, PX1 - 40)
        y = rnd.uniform(PY0 + 40, PY1 - 40)
        if _in_poly((x, y), poly):
            rr = rnd.uniform(24, 68)
            d.ellipse([x - rr, y - rr * 0.6, x + rr, y + rr * 0.6],
                      fill=_shade(base, rnd.choice([0.9, 0.94, 1.06, 1.1])))

    # ---- 放大地形场景（比世界图更密集、更有层次）----
    if terrain == "山地":
        # 远景 -> 近景 三层山脊
        for layer, (col, yn, h) in enumerate([
                ((176, 168, 156), PY0 + ph * 0.30, 90),
                ((140, 128, 116), PY0 + ph * 0.46, 130),
                ((104, 96, 88), PY0 + ph * 0.66, 170)]):
            pts = [(PX0, PY1)]
            x = PX0
            while x <= PX1:
                pts.append((x, yn - rnd.uniform(0, h)))
                x += rnd.uniform(60, 100)
            pts += [(PX1, PY1)]
            d.polygon(pts, fill=col)
            # 雪顶
            if layer >= 1:
                for px, py in pts[1:-1]:
                    if py < yn - h * 0.55:
                        d.polygon([(px, py), (px - 12, py + 18), (px + 12, py + 18)],
                                  fill=(236, 238, 234))
    elif terrain == "森林":
        for _ in range(150):
            x = rnd.uniform(PX0 + 20, PX1 - 20)
            y = rnd.uniform(PY0 + ph * 0.35, PY1 - 20)
            if _in_poly((x, y), poly):
                s = rnd.uniform(10, 22)
                d.line([(x, y + s), (x, y)], fill=(48, 40, 32), width=3)
                d.polygon([(x, y - s * 1.4), (x - s * 0.7, y + s * 0.2),
                           (x + s * 0.7, y + s * 0.2)],
                          fill=_shade((38, 88, 56), rnd.uniform(0.8, 1.25)))
    elif terrain == "沙漠":
        for _ in range(30):
            x = rnd.uniform(PX0, PX1)
            y = rnd.uniform(PY0 + 60, PY1)
            d.arc([x - 60, y - 20, x + 60, y + 24], 200, 340,
                  fill=_shade(base, 0.85), width=3)
        for _ in range(120):
            x = rnd.uniform(PX0 + 20, PX1 - 20)
            y = rnd.uniform(PY0 + 60, PY1 - 20)
            d.ellipse([x, y, x + 2, y + 2], fill=(176, 152, 96))
    elif terrain in ("沿海", "岛屿"):
        # 下半：海面
        sea_y = PY0 + ph * 0.62
        for y in range(int(sea_y), PY1):
            t = (y - sea_y) / max(1, PY1 - sea_y)
            c = (int(70 - 30 * t), int(140 - 50 * t), int(180 - 60 * t))
            d.line([(PX0, y), (PX1, y)], fill=c)
        for _ in range(40):
            x = rnd.uniform(PX0, PX1 - 40)
            y = rnd.uniform(sea_y + 6, PY1 - 10)
            d.arc([x, y, x + 34, y + 10], 190, 350, fill=(210, 232, 240), width=2)
        d.line([(PX0, sea_y), (PX1, sea_y)], fill=SAND, width=8)
        if terrain == "岛屿":
            d.ellipse([cx - 90, PY0 + ph * 0.18, cx + 90, PY0 + ph * 0.55],
                      fill=base, outline=SAND, width=6)
    elif terrain == "平原":
        # 田块透视网格 + 小路
        for i in range(9):
            y = PY0 + ph * 0.35 + i * (ph * 0.6 / 9)
            d.line([(PX0, y), (PX1, y)], fill=_shade(base, 0.86), width=2)
        for i in range(11):
            x = PX0 + i * (pw / 11)
            d.line([(x, PY0 + ph * 0.35), (x + (i - 5) * 8, PY1)],
                   fill=_shade(base, 0.86), width=2)
        d.line([(PX0, PY0 + ph * 0.34), (cx, PY1)], fill=(214, 198, 150), width=10)
    elif terrain == "高原":
        for k in range(6):
            inset = 20 + k * 26
            d.line([(PX0 + inset, PY0 + inset * 0.6), (PX1 - inset, PY0 + inset * 0.6),
                    (PX1 - inset, PY1 - inset * 0.5), (PX0 + inset, PY1 - inset * 0.5),
                    (PX0 + inset, PY0 + inset * 0.6)],
                   fill=_shade(base, 0.8), width=2)

    # 裁掉主图区外溢出的绘制（重画边框）
    d.rectangle([PX0, PY0, PX1, PY1], outline=(48, 62, 96), width=3)

    # ---- 资源图标（中央偏上）----
    res = region.get("resource", "none")
    rc = RESOURCE_COLORS.get(res)
    if rc:
        ix, iy = PX0 + pw * 0.5, PY0 + ph * 0.30
        d.ellipse([ix - 30, iy - 30, ix + 30, iy + 30], fill=(255, 255, 255),
                  outline=(30, 40, 36), width=3)
        d.ellipse([ix - 20, iy - 20, ix + 20, iy + 20], fill=rc)
        rlabel = sanitize("资源 · " + RESOURCE_CN.get(res, "无"))
        fr = font(20)
        d.text((ix - d.textlength(rlabel, font=fr) / 2, iy + 36), rlabel,
               font=fr, fill=(30, 40, 36), stroke_width=2,
               stroke_fill=(240, 240, 232))

    # ---- 城池 / 首都 ----
    o = str(region.get("owner", "") or "")
    if o:
        col = _owner_color(o)
        bx, by = PX0 + pw * 0.5 - 46, PY0 + ph * 0.62
        d.rectangle([bx, by, bx + 92, by + 54], fill=(196, 190, 172),
                    outline=(60, 56, 48), width=3)
        for k in range(5):
            d.rectangle([bx + k * 18, by - 10, bx + k * 18 + 12, by],
                        fill=(196, 190, 172), outline=(60, 56, 48), width=2)
        d.rectangle([bx + 32, by + 20, bx + 60, by + 54], fill=(90, 76, 60))
        # 旗
        d.line([(bx + 92, by - 6), (bx + 92, by - 56)], fill=(60, 56, 48), width=3)
        d.polygon([(bx + 92, by - 56), (bx + 138, by - 46), (bx + 92, by - 34)], fill=col)
        oname = sanitize(str(owners.get(o, "") or ("QQ" + o[:4])))[:8]
        fo = font(18)
        d.text((bx + 4, by + 58), oname, font=fo, fill=(30, 40, 36),
               stroke_width=2, stroke_fill=(240, 240, 232))
        if region.get("capital_of"):
            d.polygon(_star(bx + 106, by - 70, 13), fill=(255, 210, 90),
                      outline=(120, 80, 20))
            fc = font(18)
            d.text((bx + 124, by - 80), sanitize("首都"), font=fc,
                   fill=(255, 210, 90), stroke_width=2, stroke_fill=(30, 40, 36))

    # ---- 防御塔楼（按 defense）----
    try:
        defense = float(region.get("defense", 0) or 0)
    except Exception:
        defense = 0
    towers = min(6, max(1, int(defense / 20)))
    # 顶部留出右侧 120px 给罗盘，避免塔楼与罗盘/标题重叠
    span = pw - 170
    for k in range(towers):
        tx = PX0 + 30 + (k * span / max(1, towers - 1) if towers > 1 else 0)
        ty = PY0 + 34
        d.rectangle([tx - 9, ty, tx + 9, ty + 26], fill=(150, 146, 136),
                    outline=(60, 56, 48), width=2)
        for m in range(3):
            d.rectangle([tx - 9 + m * 6, ty - 6, tx - 5 + m * 6, ty],
                        fill=(150, 146, 136), outline=(60, 56, 48), width=1)

    # ---- 罗盘 / 比例尺 ----
    _draw_compass(d, PX1 - 54, PY0 + 58, 34, font(15))
    _draw_scalebar(d, PX0 + 16, PY1 - 40, font(14), total=180)

    # ---- 右侧信息面板 ----
    IX0, IX1 = 820, W - 30
    d.rounded_rectangle([IX0, PY0, IX1, PY1], radius=16,
                        fill=(24, 32, 56), outline=(48, 62, 96), width=2)
    f_h = font(30)
    rname = sanitize(str(region.get("name", "")))
    d.text((IX0 + 20, PY0 + 18), rname, font=f_h, fill=(246, 196, 90))
    sub = sanitize(f"#{region.get('id','')} · {region.get('continent','')}")
    f_s = font(19)
    d.text((IX0 + 20, PY0 + 60), sub, font=f_s, fill=(150, 168, 200))
    d.line([(IX0 + 20, PY0 + 96), (IX1 - 20, PY0 + 96)], fill=(48, 62, 96), width=2)

    oname = str(owners.get(o, "") or (o or "无主"))
    rows = [
        ("地形", terrain),
        ("资源", RESOURCE_CN.get(res, "无") + f"（富集 {region.get('rich', 0)}）"),
        ("防御", f"{defense:.0f}"),
        ("开发度", f"{region.get('dev', 0)}"),
        ("归属", oname if o else "无主"),
    ]
    f_k, f_v = font(20), font(20)
    yy = PY0 + 116
    for k, v in rows:
        d.text((IX0 + 20, yy), sanitize(k), font=f_k, fill=(79, 209, 197))
        vv = _clip_text(d, sanitize(str(v)), f_v, IX1 - IX0 - 130)
        d.text((IX0 + 108, yy), vv, font=f_v, fill=(232, 236, 245))
        yy += 44

    # 周边地区（同大陆）
    d.line([(IX0 + 20, yy + 6), (IX1 - 20, yy + 6)], fill=(48, 62, 96), width=2)
    yy += 22
    d.text((IX0 + 20, yy), sanitize("周边地区"), font=f_k, fill=(79, 209, 197))
    yy += 34
    neighbours = [x["name"] for x in tpl.get("regions", [])
                  if x.get("continent") == region.get("continent")
                  and x.get("id") != region.get("id")][:4]
    f_n = font(18)
    for nb in neighbours:
        d.text((IX0 + 24, yy), sanitize("· " + nb), font=f_n, fill=(200, 214, 232))
        yy += 30
    if not neighbours:
        d.text((IX0 + 24, yy), sanitize("· 暂无记录"), font=f_n, fill=(150, 168, 200))

    # ---- 标题栏 ----
    d.rectangle([0, 0, W, head_h], fill=(15, 20, 36))
    d.rectangle([0, 0, W, 8], fill=(79, 209, 197))
    title = sanitize("[地] 地区地形图 · " + str(region.get("name", "")))
    ft2 = font(42)
    d.text((40, 30), title, font=ft2, fill=(246, 196, 90))
    st = sanitize(f"{region.get('continent','')} · 地形 {terrain} · "
                  f"资源 {RESOURCE_CN.get(res,'无')} · "
                  f"归属 {oname if o else '无主'}")
    fs2 = font(20)
    d.text((40, 90), st, font=fs2, fill=(150, 168, 200))

    foot = "国家战争插件 · 合成地形图 · 天童爱丽丝 (AL-1S) · /世界地图 返回全图"
    ff = font(15)
    d.text((W - 30 - d.textlength(sanitize(foot), font=ff), H - 40),
           sanitize(foot), font=ff, fill=(110, 130, 165))

    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        img.save(out_path, "PNG")
        return out_path
    except Exception:
        return None
