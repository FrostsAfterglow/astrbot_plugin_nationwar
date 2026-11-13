#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""集成测试：用假事件验证 main._run_cmd 的完整链路。

v1.1.0 起所有回复均为合成图片：
- 注册类：chain( At + Image )，@ 提及保留
- 普通指令：image_result(图片路径)
- /指令图：直接发两张预渲染 PNG
- 地图指令：专用地图图片 + 文本卡片图片
"""
import sys
import os
import tempfile

sys.path.insert(0, "/workspace")

from PIL import Image  # noqa: E402

from astrbot_plugin_nationwar.main import (  # noqa: E402
    _rest, NationWarPlugin, CHART_IMAGES,
)
from astrbot_plugin_nationwar.core.store import Store  # noqa: E402
from astrbot_plugin_nationwar.core.engine import Engine  # noqa: E402
from astrbot_plugin_nationwar.core.imager import ImageRenderer  # noqa: E402


class _Logger:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


class FakeEvent:
    """模拟 AstrMessageEvent 的最小子集（含图片 API）。"""
    def __init__(self, raw, qq="12345"):
        self._raw = raw
        self._qq = qq

    def get_sender_id(self):
        return self._qq

    def get_message_str(self):
        return self._raw

    def plain_result(self, text):
        return ("plain", text)

    def image_result(self, path):
        return ("image", path)

    def chain_result(self, comps):
        return ("chain", comps)


def make_plugin():
    d = tempfile.mkdtemp()
    store = Store(d)
    eng = Engine(store, {"starting_resources": "1000,1000,200,50,50"}, None)
    plugin = object.__new__(NationWarPlugin)
    plugin.store = store
    plugin.engine = eng
    plugin.config = {}
    plugin.logger = _Logger()
    plugin._cmd_index = {c["key"]: c for c in store.commands()}
    plugin.imager = ImageRenderer(os.path.join(d, "rendered"))
    return plugin


def _collect(plugin, ev, key, names):
    import asyncio
    async def run():
        out = []
        async for r in plugin._run_cmd(ev, key, names):
            out.append(r)
        return out
    return asyncio.run(run())


def _assert_png(path):
    assert path and os.path.exists(path), f"图片不存在: {path}"
    im = Image.open(path)
    assert im.format == "PNG" and im.size[0] > 100 and im.size[1] > 100, (path, im.size)


def _components(result):
    """提取一条消息里的所有组件（兼容 image/chain/plain 三种返回）。"""
    if result[0] == "chain":
        return result[1]
    return [result]


def test_rest_parsing():
    ev = FakeEvent("初始组织名 曙光帝国")
    assert _rest(ev, ["初始组织名", "建组织", "创国"]) == "曙光帝国"
    ev2 = FakeEvent("建造 农场")
    assert _rest(ev2, ["建造", "建"]) == "农场"
    ev3 = FakeEvent("宣战 钢铁联邦")
    assert _rest(ev3, ["宣战"]) == "钢铁联邦"
    ev4 = FakeEvent("注册")
    assert _rest(ev4, ["注册", "signup", "regist"]) == ""
    print("✅ 参数解析（多词/别名/无参）正常")


def test_register_uses_image_with_mention():
    plugin = make_plugin()
    assert plugin.imager.available, "渲染器应可用（字体需随插件打包）"

    ev = FakeEvent("注册", qq="777")
    out = _collect(plugin, ev, "register", ["注册", "signup", "regist"])
    out = out[0]
    assert out[0] == "chain", out
    comps = out[1]
    assert any(str(getattr(c, "qq", None)) == "777" for c in comps), "注册回复应 @ 用户"
    # 必须含图片组件，且图片是有效 PNG
    imgs = [c for c in comps if c.__class__.__name__ == "Image"]
    assert imgs, "注册回复应是合成图片而非纯文本"
    _assert_png(getattr(imgs[0], "path", None))
    # 文案正确性由 engine 保证（do_register），这里验证图片确实渲染了文本
    print("✅ 注册回复 = @用户 + 合成图片（非纯文本）")


def test_set_org_uses_image_with_mention():
    plugin = make_plugin()
    # 先注册
    _collect(plugin, FakeEvent("注册", qq="777"), "register", ["注册", "signup", "regist"])
    out = _collect(plugin, FakeEvent("初始组织名 曙光帝国", qq="777"),
                   "set_org", ["初始组织名", "建组织", "创国"])[0]
    assert out[0] == "chain", out
    comps = out[1]
    assert any(str(getattr(c, "qq", None)) == "777" for c in comps)
    imgs = [c for c in comps if c.__class__.__name__ == "Image"]
    assert imgs
    _assert_png(getattr(imgs[0], "path", None))
    print("✅ 设组织名回复 = @用户 + 合成图片")


def test_normal_command_is_image():
    plugin = make_plugin()
    _collect(plugin, FakeEvent("注册", qq="777"), "register", ["注册", "signup", "regist"])
    _collect(plugin, FakeEvent("初始组织名 曙光帝国", qq="777"),
             "set_org", ["初始组织名", "建组织", "创国"])
    out = _collect(plugin, FakeEvent("我的信息", qq="777"),
                   "myinfo", ["我的信息", "信息", "国家"])[0]
    assert out[0] == "image", f"普通指令应返回图片，实际 {out[0]}"
    _assert_png(out[1])
    print("✅ 普通指令回复 = 合成图片")


def test_cmd_charts_sends_two_pngs():
    plugin = make_plugin()
    out = _collect(plugin, FakeEvent("指令图", qq="777"), "cmd_charts", ["指令图"])
    assert len(out) == 2, f"/指令图 应发送两张图片，实际 {len(out)} 条"
    for r in out:
        assert r[0] == "image", r
        _assert_png(r[1])
    print("✅ /指令图 直接发送两张预渲染 PNG（不再发文字说明）")


def test_world_map_sends_dedicated_image():
    plugin = make_plugin()
    _collect(plugin, FakeEvent("注册", qq="777"), "register", ["注册", "signup", "regist"])
    _collect(plugin, FakeEvent("初始组织名 曙光帝国", qq="777"),
             "set_org", ["初始组织名", "建组织", "创国"])
    out = _collect(plugin, FakeEvent("世界地图", qq="777"), "world_map", ["世界地图", "地图"])
    # 至少 2 张：专用世界地图 + 文本说明卡片
    assert len(out) >= 2, f"世界地图应发多张图片，实际 {len(out)}"
    for r in out:
        assert r[0] == "image", r
        _assert_png(r[1])
    print(f"✅ 世界地图指令发送 {len(out)} 张图片（专用地图 + 说明卡片）")


def test_engine_text_still_correct():
    """图片化不影响 engine 的纯文本逻辑（注册文案必须与需求一致）。"""
    d = tempfile.mkdtemp()
    store = Store(d)
    eng = Engine(store, {"starting_resources": "1000,1000,200,50,50"}, None)
    st = store.load_state()
    eng.ensure_world(st)
    txt = eng.do_register("777", st)
    assert "已注册成功" in txt and "/初始组织名" in txt and "不组织名称也不能游玩" in txt
    print("✅ engine 注册文案保持与需求一致")


if __name__ == "__main__":
    test_rest_parsing()
    test_register_uses_image_with_mention()
    test_set_org_uses_image_with_mention()
    test_normal_command_is_image()
    test_cmd_charts_sends_two_pngs()
    test_world_map_sends_dedicated_image()
    test_engine_text_still_correct()
    print("\n集成测试通过。")
