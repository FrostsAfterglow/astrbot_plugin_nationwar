# -*- coding: utf-8 -*-
"""合成图片渲染器（Pillow）。

插件的**所有**回复都经此处渲染为 PNG 图片后再发送：
- render_text()        通用文本卡片（标题栏 + 正文自动换行 + 超长自动分页 + 水印）
- render_chart_image() 指令图（分组双栏卡片）
- render_world_map()   完整虚拟世界地图（大陆板块 + 地区着色 + 图例）
- render_region_map()  单个地区放大图

字体随插件打包（assets/fonts/NotoSansCJKsc-Regular.otf = Noto Sans CJK SC），
用户机器无需安装任何中文字体。Pillow 缺失时上层会降级为纯文本。
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from typing import List, Optional

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    _HAS_PIL = True
except Exception:  # pragma: no cover
    _HAS_PIL = False

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.normpath(os.path.join(HERE, ".."))
FONT_PATH = os.path.join(PLUGIN_DIR, "assets", "fonts", "NotoSansCJKsc-Regular.otf")
ASSET_DIR = os.path.join(PLUGIN_DIR, "assets")

# ---------------------------------------------------------------------------
# emoji / 稀有符号 -> 字体可渲染的短标签（避免出现豆腐块）
# ---------------------------------------------------------------------------
EMOJI_MAP = {
    "☢": "[核]", "⚔": "[战]", "⚠": "[!]", "⚡": "[速]", "⛏": "[矿]",
    "✅": "[√]", "✌": "[胜]", "❌": "[×]", "⭐": "[星]", "🌍": "[世界]",
    "🌐": "[全球]", "🌟": "[星]", "🎉": "[庆]", "🎖": "[勋]", "🏆": "[冠]",
    "🏗": "[建]", "🏛": "[政]", "🏰": "[堡]", "👥": "[众]", "💰": "[金]",
    "📊": "[表]", "📍": "[地]", "📘": "[书]", "📜": "[卷]", "📡": "[讯]",
    "📦": "[箱]", "🔄": "[循]", "🔍": "[查]", "🔬": "[研]", "🕊": "[和]",
    "🖥": "[服]", "🖨": "[印]", "🗑": "[删]", "🗡": "[攻]", "🗺": "[图]",
    "😊": "^_^", "🚧": "[工]", "🛡": "[防]", "🛰": "[卫]", "🟥": "■",
    "🟦": "■", "🤝": "[交]", "️": "", "\ufe0f": "", "\u20e3": "",
}

# 主题配色（深底 + 霓虹强调色）
THEMES = {
    "blue": dict(bg=(15, 20, 36), card=(24, 32, 56), bar=(28, 40, 74),
                 accent=(79, 209, 197), accent2=(246, 196, 90), fg=(232, 236, 245),
                 sub=(150, 168, 200), line=(48, 62, 96), chip=(38, 52, 88)),
    "red": dict(bg=(26, 15, 20), card=(42, 24, 32), bar=(58, 28, 38),
                accent=(255, 107, 107), accent2=(255, 209, 102), fg=(245, 232, 236),
                sub=(192, 138, 160), line=(86, 44, 58), chip=(66, 34, 46)),
}


def sanitize(text: str) -> str:
    """把 emoji/变体选择符替换为字体可渲染的短标签，保证图片不出现豆腐块。"""
    out = []
    for ch in text or "":
        if ch in EMOJI_MAP:
            out.append(EMOJI_MAP[ch])
            continue
        o = ord(ch)
        # 变体选择符、零宽连接符、非 BMP（绝大多数 emoji）一律剔除
        if o == 0xFE0F or o == 0x200D or o > 0xFFFF or 0x1F000 <= o <= 0x1FAFF:
            continue
        # 其它杂项符号区（遗漏的 emoji）用占位
        if 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF:
            out.append("[*]")
            continue
        out.append(ch)
    return "".join(out)


class ImageRenderer:
    """把文本/数据合成为 PNG 图片。所有方法返回图片文件绝对路径列表。"""

    def __init__(self, out_dir: str, font_path: str = FONT_PATH):
        self.out_dir = out_dir
        os.makedirs(self.out_dir, exist_ok=True)
        self.font_path = font_path if os.path.exists(font_path) else None
        self._cache = {}
        self._theme = THEMES["blue"]

    # ---- 基础工具 ----------------------------------------------------------
    @property
    def available(self) -> bool:
        return _HAS_PIL and self.font_path is not None

    def _font(self, size: int):
        key = size
        if key not in self._cache:
            self._cache[key] = ImageFont.truetype(self.font_path, size)
        return self._cache[key]

    def _tw(self, draw: "ImageDraw.ImageDraw", text: str, size: int) -> float:
        return draw.textlength(text, font=self._font(size))

    def _wrap(self, draw, text: str, size: int, max_w: int) -> List[str]:
        """按像素宽度逐字折行（中英混排均可）。"""
        lines = []
        for raw in text.split("\n"):
            if raw == "":
                lines.append("")
                continue
            cur = ""
            for ch in raw:
                if self._tw(draw, cur + ch, size) <= max_w:
                    cur += ch
                else:
                    if cur:
                        lines.append(cur)
                    cur = ch
            lines.append(cur)
        return lines

    def _path(self, tag: str, payload: str) -> str:
        h = hashlib.md5((tag + payload).encode("utf-8")).hexdigest()[:16]
        return os.path.join(self.out_dir, f"nw_{tag}_{h}.png")

    def _gradient(self, w: int, h: int, theme: dict):
        img = Image.new("RGB", (w, h), theme["bg"])
        d = ImageDraw.Draw(img)
        for y in range(h):
            t = y / max(1, h - 1)
            r = int(theme["bg"][0] + (theme["bar"][0] - theme["bg"][0]) * t * 0.55)
            g = int(theme["bg"][1] + (theme["bar"][1] - theme["bg"][1]) * t * 0.55)
            b = int(theme["bg"][2] + (theme["bar"][2] - theme["bg"][2]) * t * 0.55)
            d.line([(0, y), (w, y)], fill=(r, g, b))
        return img

    # ---- 通用文本卡片 ------------------------------------------------------
    def render_text(self, text: str, title: str = "国家战争", subtitle: str = "",
                    theme: str = "blue", max_lines_per_page: int = 26) -> List[str]:
        """把任意文本渲染成一张/多张卡片图。返回图片路径列表（长文本自动分页）。"""
        if not self.available:
            return []
        th = THEMES.get(theme, THEMES["blue"])
        clean = sanitize(text or "")
        W = 900
        PAD = 46
        body_size = 24
        title_size = 40
        line_h = int(body_size * 1.62)
        inner_w = W - PAD * 2 - 30

        probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        lines = self._wrap(probe, clean, body_size, inner_w)

        # 分页
        pages = [lines[i:i + max_lines_per_page]
                 for i in range(0, len(lines), max_lines_per_page)] or [[""]]
        total = len(pages)
        out_paths = []
        for idx, page in enumerate(pages, 1):
            head_h = 150
            foot_h = 62
            body_h = max(len(page), 1) * line_h + 40
            H = head_h + body_h + foot_h
            img = self._gradient(W, H, th)
            d = ImageDraw.Draw(img)

            # 标题栏
            d.rectangle([0, 0, W, 8], fill=th["accent"])
            d.text((PAD, 40), sanitize(title), font=self._font(title_size), fill=th["accent2"])
            sub = subtitle or "astrbot_plugin_nationwar · 账号=QQ号 · /注册 开始游戏"
            d.text((PAD, 96), sanitize(sub), font=self._font(20), fill=th["sub"])
            if total > 1:
                pg = f"第 {idx}/{total} 页"
                d.text((W - PAD - self._tw(d, pg, 20), 44), pg,
                       font=self._font(20), fill=th["sub"])
            d.line([(PAD, head_h - 18), (W - PAD, head_h - 18)], fill=th["line"], width=2)

            # 正文卡片
            card_top = head_h - 4
            card_bot = head_h + body_h
            d.rounded_rectangle([PAD - 16, card_top, W - PAD + 16, card_bot],
                                radius=18, fill=th["card"], outline=th["line"], width=2)
            y = card_top + 20
            for ln in page:
                # 高亮：以【】或 ▎ 开头的行
                color = th["fg"]
                if ln.startswith("【") or ln.startswith("=="):
                    color = th["accent"]
                elif ln.lstrip().startswith(("·", "-", "•")):
                    color = th["sub"]
                d.text((PAD, y), ln, font=self._font(body_size), fill=color)
                y += line_h

            # 页脚水印
            foot = "由 国家战争插件 合成图片发送 · 天童爱丽丝 (AL-1S)"
            fw = self._tw(d, foot, 18)
            d.text(((W - fw) / 2, H - foot_h + 12), sanitize(foot),
                   font=self._font(18), fill=th["sub"])

            p = self._path("txt", f"{title}|{idx}|{total}|{clean}|{theme}")
            img.save(p, "PNG")
            out_paths.append(p)
        return out_paths

    # ---- 指令图（预渲染资源）----------------------------------------------
    def _clip(self, draw, text: str, size: int, max_w: int) -> str:
        """单行截断，超宽加省略号。"""
        if self._tw(draw, text, size) <= max_w:
            return text
        s = text
        while s and self._tw(draw, s + "…", size) > max_w:
            s = s[:-1]
        return s + "…"

    def render_chart_image(self, chart_no: int, commands: list, title: str,
                           subtitle: str, theme: str = "blue") -> Optional[str]:
        """把某张指令表渲染成分组双栏大图。返回图片绝对路径。"""
        if not self.available:
            return None
        th = THEMES.get(theme, THEMES["blue"])
        items = [c for c in commands if c.get("chart") == chart_no]
        groups = {}
        for c in items:
            groups.setdefault(c.get("group", "其它"), []).append(c)

        W = 1600
        PAD = 50
        GAP = 24
        col_w = (W - PAD * 2 - GAP) // 2          # 瀑布流栏宽
        cell_w = (col_w - 28) // 2                 # 卡片内指令格宽
        name_size = 20
        desc_size = 15
        gt_size = 26
        row_h = 56
        gt_h = 50

        probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        # 预处理：每条指令的名/描述裁到单行，宽度按「指令格」而非整栏
        for g, cs in groups.items():
            for c in cs:
                nm = "/" + c["name"]
                al = (" / " + " / ".join(c.get("alias", []))) if c.get("alias") else ""
                arg = f" [{c['args']}]" if c.get("args") else ""
                c["_name"] = self._clip(probe, sanitize(nm + al + arg), name_size, cell_w - 12)
                c["_desc"] = self._clip(probe, sanitize(c.get("desc", "")), desc_size, cell_w - 12)

        cards = []
        for g, cs in groups.items():
            rows = (len(cs) + 1) // 2
            card_h = gt_h + rows * row_h + 16
            cards.append((g, cs, card_h))

        # 双栏瀑布布局（高卡尽量分到较矮的一列）
        col_heights = [0, 0]
        placements = []
        for g, cs, card_h in cards:
            ci = 0 if col_heights[0] <= col_heights[1] else 1
            placements.append((g, cs, card_h, PAD + ci * (col_w + GAP), col_heights[ci]))
            col_heights[ci] += card_h + GAP

        head_h = 170
        foot_h = 64
        H = head_h + max(col_heights) + foot_h
        img = self._gradient(W, H, th)
        d = ImageDraw.Draw(img)

        d.rectangle([0, 0, W, 10], fill=th["accent"])
        title_s = sanitize(title)
        tw = self._tw(d, title_s, 46)
        d.text(((W - tw) / 2, 38), title_s, font=self._font(46), fill=th["accent2"])
        sub = f"{sanitize(subtitle)} · 共 {len(items)} 条指令 · 账号=QQ号 /注册 开始"
        sw = self._tw(d, sub, 22)
        d.text(((W - sw) / 2, 104), sub, font=self._font(22), fill=th["sub"])
        d.line([(PAD, head_h - 20), (W - PAD, head_h - 20)], fill=th["line"], width=2)

        for g, cs, card_h, x, y0 in placements:
            y = head_h + y0
            d.rounded_rectangle([x, y, x + col_w, y + card_h], radius=16,
                                fill=th["card"], outline=th["line"], width=2)
            d.rounded_rectangle([x + 14, y + 12, x + 22, y + gt_h - 8],
                                radius=4, fill=th["accent"])
            d.text((x + 34, y + 11), sanitize(g), font=self._font(gt_size), fill=th["accent"])
            cnt = str(len(cs))
            d.text((x + col_w - 20 - self._tw(d, cnt, 22), y + 15), cnt,
                   font=self._font(22), fill=th["accent2"])
            ry = y + gt_h
            for i, c in enumerate(cs):
                cx = x + 14 + (i % 2) * cell_w
                cy = ry + (i // 2) * row_h
                # 交替格底色，提升可读性
                if (i // 2) % 2 == 0:
                    d.rounded_rectangle([cx - 4, cy - 2, cx + cell_w - 10, cy + row_h - 8],
                                        radius=6, fill=th["chip"])
                d.text((cx + 2, cy + 4), c["_name"], font=self._font(name_size), fill=th["fg"])
                d.text((cx + 2, cy + 30), c["_desc"], font=self._font(desc_size), fill=th["sub"])

        foot = "astrbot_plugin_nationwar · 两张指令图（内政经济 / 军事外交）· /指令图 可再次查看"
        fw = self._tw(d, foot, 20)
        d.text(((W - fw) / 2, H - foot_h + 18), sanitize(foot), font=self._font(20), fill=th["sub"])

        p = os.path.join(ASSET_DIR, f"commands_chart{chart_no}.png")
        img.save(p, "PNG")
        return p

    # ---- 世界地图 / 地区地图（真正的地形图，委托 geomaps 模块）--------------
    def render_world_map(self, state: dict, world_tpl: dict,
                         owners: dict | None = None) -> Optional[str]:
        """完整虚拟世界【地形地图】：不规则大陆海岸线 + Voronoi 地区拼接 +
        地形纹理 + 归属势力染色 + 首都/资源/编号 + 经纬网 + 罗盘 + 比例尺 + 图例。

        owners: {qq: 组织名}，用于图例/标注显示国家名。地图随归属与时间变化重新生成。
        """
        if not self.available:
            return None
        try:
            from .geomaps import world_map
        except Exception:
            return None
        regions = state.get("regions", [])
        sig = "|".join(f"{r.get('id')}:{r.get('owner','')}" for r in regions)
        p = self._path("wmap", f"{int(time.time() // 30)}|{sig}")
        return world_map(state, world_tpl, owners or {}, self._font, p, sanitize)

    def render_region_map(self, region: dict, owners: dict | None = None,
                          world_tpl: dict | None = None) -> Optional[str]:
        """单个地区【放大地形图】：层叠山脊/森林/沙丘海岸/农田/高原场景 +
        资源图标 + 城池/首都 + 防御塔楼 + 信息面板 + 罗盘比例尺。"""
        if not self.available:
            return None
        try:
            from .geomaps import region_map
        except Exception:
            return None
        p = self._path("rmap", f"{int(time.time() // 30)}|{region.get('id')}|"
                               f"{region.get('owner')}|{region.get('dev')}|{region.get('defense')}")
        return region_map(region, owners or {}, world_tpl or {},
                          self._font, p, sanitize)
