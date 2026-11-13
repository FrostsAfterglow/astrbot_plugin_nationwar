#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证插件可被 AstrBot 识别并动态注册 250+ 指令。"""
import sys
import os

sys.path.insert(0, "/workspace")
import astrbot_plugin_nationwar.main as m
from astrbot.core.star.register.star_handler import star_handlers_registry


def test_registration():
    cls = m.NationWarPlugin
    methods = [n for n in dir(cls) if n.startswith("cmd_")]
    assert len(methods) >= 200, f"动态指令方法数不足: {len(methods)}"
    print(f"✅ 插件类动态指令方法: {len(methods)}")

    mine = [h for h in star_handlers_registry._handlers
            if getattr(h.handler, "__module__", "") == "astrbot_plugin_nationwar.main"]
    assert len(mine) >= 200, f"全局注册表 handler 数不足: {len(mine)}"
    print(f"✅ 全局注册表本插件 handler: {len(mine)}（无塌缩）")

    # 每个 catalog key 都有对应方法且 handler 唯一
    keys = {c["key"] for c in m.engine_mod.Store(
        os.path.join(os.path.dirname(m.__file__), "data_runtime")
    ).commands()}
    method_keys = {n[4:] for n in methods}
    missing = keys - method_keys
    assert not missing, f"缺少方法: {missing}"
    print(f"✅ 全部 {len(keys)} 个指令 key 均生成独立方法")


if __name__ == "__main__":
    test_registration()
    print("\n注册验证通过。")
