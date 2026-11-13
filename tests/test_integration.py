#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""集成测试：用假事件验证 main._run_cmd 的完整链路（含参数解析与 @提及）。"""
import sys
import os
import tempfile

sys.path.insert(0, "/workspace")

from astrbot_plugin_nationwar.main import _rest, NationWarPlugin
from astrbot_plugin_nationwar.core.store import Store
from astrbot_plugin_nationwar.core.engine import Engine


class FakeEvent:
    """模拟 AstrMessageEvent 的最小子集。"""
    def __init__(self, raw, qq="12345"):
        self._raw = raw
        self._qq = qq

    def get_sender_id(self):
        return self._qq

    def get_message_str(self):
        return self._raw

    def plain_result(self, text):
        return ("plain", text)

    def chain_result(self, comps):
        return ("chain", comps)


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


def test_run_cmd_register_mention():
    import asyncio
    d = tempfile.mkdtemp()
    store = Store(d)
    eng = Engine(store, {"starting_resources": "1000,1000,200,50,50"}, None)
    plugin = object.__new__(NationWarPlugin)
    plugin.engine = eng
    plugin.store = store

    async def collect(ev, key, names):
        res = []
        async for r in plugin._run_cmd(ev, key, names):
            res.append(r)
        return res

    # 注册：应返回 chain 且含 At 提及
    ev = FakeEvent("注册", qq="777")
    out = asyncio.run(collect(ev, "register", ["注册", "signup", "regist"]))
    out = out[0]
    assert out[0] == "chain", out
    assert any(str(getattr(c, "qq", None)) == "777" for c in out[1]), "注册回复应 @ 用户"
    assert "已注册成功" in out[1][-1].text, out
    print("✅ 注册回复含 @ 提及且文案正确")

    # 设组织名
    ev2 = FakeEvent("初始组织名 曙光帝国", qq="777")
    out2 = asyncio.run(collect(ev2, "set_org", ["初始组织名", "建组织", "创国"]))[0]
    assert out2[0] == "chain"
    assert "创建成功" in out2[1][-1].text, out2
    print("✅ 设组织名回复含 @ 提及")

    # 普通指令：plain 无提及
    ev3 = FakeEvent("我的信息", qq="777")
    out3 = asyncio.run(collect(ev3, "myinfo", ["我的信息", "信息", "国家"]))[0]
    assert out3[0] == "plain"
    assert "曙光帝国" in out3[1], out3
    print("✅ 普通指令返回 plain 且含组织名")


if __name__ == "__main__":
    test_rest_parsing()
    test_run_cmd_register_mention()
    print("\n集成测试通过。")
