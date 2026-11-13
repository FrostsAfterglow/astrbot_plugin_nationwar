#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据 commands.json 生成两张大型指令图（HTML）。

  commands_chart1.html  内政经济（图1）
  commands_chart2.html  军事外交（图2）
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, "..", "data"))
OUT = os.path.normpath(os.path.join(HERE, ".."))

with open(os.path.join(DATA, "commands.json"), "r", encoding="utf-8") as f:
    CMDS = json.load(f)


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build(chart_no, title, theme):
    items = [c for c in CMDS if c["chart"] == chart_no]
    groups = {}
    for c in items:
        groups.setdefault(c["group"], []).append(c)
    order = list(groups.keys())
    cards = []
    for g in order:
        rows = []
        for c in groups[g]:
            alias = (" / " + " / ".join(c["alias"])) if c.get("alias") else ""
            arg = f" <span class='arg'>[{esc(c['args'])}]</span>" if c.get("args") else ""
            rows.append(
                f"<div class='cmd'><b>/{esc(c['name'])}</b>{esc(alias)}{arg}"
                f"<div class='d'>{esc(c['desc'])}</div></div>"
            )
        cards.append(
            f"<div class='group'><div class='gt'>{esc(g)}"
            f"<span class='cnt'>{len(groups[g])}</span></div>"
            f"<div class='grid'>{''.join(rows)}</div></div>"
        )
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin:0; background:{theme['bg']}; color:{theme['fg']};
  font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; padding:24px; }}
h1 {{ text-align:center; margin:8px 0 2px; font-size:30px; letter-spacing:2px; }}
.sub {{ text-align:center; opacity:.7; margin-bottom:18px; }}
.wrap {{ max-width:1200px; margin:0 auto; columns:2; column-gap:18px; }}
.group {{ break-inside:avoid; background:{theme['card']}; border-radius:12px;
  padding:14px 16px; margin-bottom:18px; box-shadow:0 2px 10px rgba(0,0,0,.25); }}
.gt {{ font-weight:700; font-size:17px; color:{theme['accent']};
  border-bottom:2px solid {theme['accent']}; padding-bottom:6px; margin-bottom:10px;
  display:flex; justify-content:space-between; }}
.cnt {{ background:{theme['accent']}; color:#000; border-radius:10px;
  padding:0 8px; font-size:13px; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
.cmd {{ background:rgba(255,255,255,.04); border-radius:8px; padding:7px 9px;
  font-size:13px; }}
.cmd b {{ color:{theme['accent2']}; }}
.arg {{ color:{theme['muted']}; font-size:12px; }}
.d {{ opacity:.66; font-size:11.5px; margin-top:2px; line-height:1.4; }}
.foot {{ text-align:center; opacity:.5; margin-top:10px; font-size:12px; }}
@media(max-width:760px){{ .wrap{{columns:1;}} .grid{{grid-template-columns:1fr;}} }}
</style></head>
<body>
<h1>{esc(title)}</h1>
<div class="sub">虚拟国家战争插件 · 共 {len(items)} 条指令 · 账号=QQ号，按 /注册 开始</div>
<div class="wrap">{''.join(cards)}</div>
<div class="foot">由 astrbot_plugin_nationwar 自动生成 · /指令图 可在群内查看说明</div>
</body></html>"""
    return html


def main():
    t1 = {"bg": "#0f1424", "fg": "#e8ecf5", "card": "#1a2138", "accent": "#4fd1c5",
          "accent2": "#f6c45a", "muted": "#8aa0c0"}
    t2 = {"bg": "#1a0f14", "fg": "#f5e8ec", "card": "#2a1820", "accent": "#ff6b6b",
          "accent2": "#ffd166", "muted": "#c08aa0"}
    p1 = os.path.join(OUT, "commands_chart1.html")
    p2 = os.path.join(OUT, "commands_chart2.html")
    with open(p1, "w", encoding="utf-8") as f:
        f.write(build(1, "🟦 指令图一 · 内政经济", t1))
    with open(p2, "w", encoding="utf-8") as f:
        f.write(build(2, "🟥 指令图二 · 军事外交", t2))
    c1 = sum(1 for c in CMDS if c["chart"] == 1)
    c2 = sum(1 for c in CMDS if c["chart"] == 2)
    print(f"已生成 {p1}（{c1} 条）")
    print(f"已生成 {p2}（{c2} 条）")


if __name__ == "__main__":
    main()
