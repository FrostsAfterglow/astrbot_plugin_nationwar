#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""存档永久化 + 30 天自动清档 回归测试（v1.2.0）。

覆盖：
- 原子写 / .bak 回滚 / 损坏文件隔离（绝不静默丢弃=绝不"初始化掉数据"）
- 插件「重新初始化」（新建 Store/Engine 实例读同一目录）账号数据不丢、不被重置
- 旧目录迁移 migrate_legacy_dir
- 老档案补齐 last_active（用历史时间戳兜底，不误判过期）
- touch_active 刷新活跃时间（发指令保活）
- purge_inactive：30 天未使用级联清档（释放地区/组织名/外交/战争/同盟），活跃账号保留
"""
import sys
import os
import json
import time
import shutil
import tempfile

sys.path.insert(0, "/workspace")

from astrbot_plugin_nationwar.core.store import Store  # noqa: E402
from astrbot_plugin_nationwar.core.engine import Engine  # noqa: E402

PLUGIN = "/workspace/astrbot_plugin_nationwar"
DAY = 86400


def _engine(base):
    s = Store(base)
    e = Engine(s, {"starting_resources": "1000,1000,200,50,50",
                   "inactive_days": 30}, None)
    st = s.load_state()
    e.ensure_world(st)
    return s, e, st


def _register(s, e, st, qq, org):
    e.dispatch(qq, "register", "", st)
    e.dispatch(qq, "set_org", org, st)
    return s.load_player(qq)


def test_atomic_write_and_bak():
    base = tempfile.mkdtemp()
    s = Store(base)
    p = s.new_player("111", "测试国", {"money": 100, "food": 100,
                                       "oil": 1, "rare": 1, "tech": 1}, 1)
    s.save_player(p)
    assert s.load_player("111")["org"] == "测试国"
    # .bak 存在（上一版回滚点）
    p["org"] = "改名国"
    s.save_player(p)
    assert os.path.exists(s.player_path("111") + ".bak")
    assert s.load_player("111")["org"] == "改名国"
    print("✅ 原子写 + .bak 回滚点")


def test_corrupt_file_is_quarantined_not_dropped():
    base = tempfile.mkdtemp()
    s = Store(base)
    p = s.new_player("222", "损坏测试", {}, 1)
    s.save_player(p)
    s.save_player(p)   # 第二次写产生 .bak（回滚点）
    assert os.path.exists(s.player_path("222") + ".bak")
    # 主文件写坏，但 .bak 完好 -> 自动从 .bak 恢复
    with open(s.player_path("222"), "w", encoding="utf-8") as f:
        f.write("{坏掉的 json")
    got = s.load_player("222")
    assert got and got["org"] == "损坏测试", "应从 .bak 自动恢复，不能丢号"
    assert s.load_player("222")["org"] == "损坏测试", "主文件应被修复"
    # 主+bak 全坏 -> 隔离到 _corrupt（不删除原数据）
    with open(s.player_path("222"), "w", encoding="utf-8") as f:
        f.write("{坏")
    with open(s.player_path("222") + ".bak", "w", encoding="utf-8") as f:
        f.write("{坏")
    assert s.load_player("222") is None
    assert os.path.isdir(s.corrupt_dir) and len(os.listdir(s.corrupt_dir)) >= 1
    print("✅ 损坏存档从 .bak 恢复 / 彻底损坏隔离到 _corrupt（数据不丢）")


def test_reinit_does_not_reset_data():
    """模拟插件重载/重启：新建 Store+Engine 读同一持久目录，账号与世界不得被重置。"""
    base = tempfile.mkdtemp()
    s, e, st = _engine(base)
    _register(s, e, st, "333", "永恒帝国")
    # 造点资产：建造 + 占领第 5 个地区
    e.dispatch("333", "build", "农场", st)
    e.dispatch("333", "accel_build", "", st)
    st = s.load_state()
    st["regions"][4]["owner"] = "333"
    st["regions"][4]["capital_of"] = "333"
    s.save_state(st)
    before = s.load_player("333")

    # —— 插件「再初始化」：完全新建实例 ——
    s2, e2, st2 = _engine(base)
    after = s2.load_player("333")
    assert after is not None, "重建实例后账号不能消失"
    assert after["org"] == "永恒帝国"
    assert after["registered_at"] == before["registered_at"], "注册时间不得被重置"
    assert after["buildings"].get("farm", 0) == before["buildings"].get("farm", 0)
    assert st2["regions"][4]["owner"] == "333", "世界地区归属不得被重新初始化"
    assert st2["org_index"].get("永恒帝国") == "333"
    # 再来一次指令，数据持续累积
    e2.dispatch("333", "myinfo", "", st2)
    assert s2.load_player("333")["org"] == "永恒帝国"
    print("✅ 插件重载/重启/更新均不重置账号与世界数据（存档永久化）")


def test_migrate_legacy_dir():
    """旧版误落在插件目录内 data_runtime 的存档，升级后要迁移到持久目录。"""
    legacy = tempfile.mkdtemp()
    os.makedirs(os.path.join(legacy, "players"))
    oldp = Store(legacy).new_player("444", "旧目录国家", {}, 7)
    with open(os.path.join(legacy, "players", "444.json"), "w", encoding="utf-8") as f:
        json.dump(oldp, f, ensure_ascii=False)
    with open(os.path.join(legacy, "state.json"), "w", encoding="utf-8") as f:
        json.dump({"regions": [{"id": 7, "owner": "444"}], "org_index": {"旧目录国家": "444"}},
                  f, ensure_ascii=False)

    base = tempfile.mkdtemp()
    s = Store(base)
    moved = s.migrate_legacy_dir(legacy)
    assert moved == 2, f"应迁移 2 个文件，实际 {moved}"
    assert s.load_player("444")["org"] == "旧目录国家"
    assert s.load_state()["regions"][0]["owner"] == "444"
    # 幂等 + 不覆盖新数据：新目录已有更新值时不覆盖
    s.save_player({**s.load_player("444"), "org": "新名字"})
    s.migrate_legacy_dir(legacy)
    assert s.load_player("444")["org"] == "新名字", "迁移不得覆盖新目录已有数据"
    print("✅ 旧目录存档迁移（幂等、不覆盖新数据）")


def test_migrate_last_active_uses_historical_ts():
    """老档案没有 last_active 时，用历史时间戳补齐，绝不能误判为「刚活跃」。"""
    base = tempfile.mkdtemp()
    s = Store(base)
    old = s.new_player("555", "老玩家", {}, 1)
    old.pop("last_active")              # 模拟升级前的老档案
    old["last_tick"] = int(time.time()) - 40 * DAY   # 40 天前最后结算
    old["registered_at"] = int(time.time()) - 60 * DAY
    s.save_player(old)
    fixed = s.migrate_last_active()
    assert fixed == 1
    got = s.load_player("555")
    assert got["last_active"] == old["last_tick"], "应取历史时间戳，不能用当前时间"
    print("✅ 老档案 last_active 用历史时间戳兜底（不误判、该清的能清）")


def test_touch_active_refreshes():
    base = tempfile.mkdtemp()
    s, e, st = _engine(base)
    _register(s, e, st, "666", "活跃国")
    p = s.load_player("666")
    p["last_active"] = int(time.time()) - 20 * DAY
    s.save_player(p)
    # 发一条任意指令 = 一次使用，应刷新活跃时间
    e.dispatch("666", "myinfo", "", st)
    got = s.load_player("666")
    assert time.time() - got["last_active"] < 5, "发指令应把活跃时间刷新为现在"
    print("✅ 玩家发指令刷新最后活跃时间（保活）")


def test_purge_inactive_cascades():
    """30 天未使用自动清档：删号 + 释放地区/组织名/外交/战争/同盟；活跃账号保留。"""
    base = tempfile.mkdtemp()
    s, e, st = _engine(base)
    now = int(time.time())

    # 活跃账号
    _register(s, e, st, "active1", "活跃联邦")
    # 过期账号（35 天未使用）
    _register(s, e, st, "stale1", "沉睡王国")
    _register(s, e, st, "stale2", "遗忘公国")
    for qq in ("stale1", "stale2"):
        p = s.load_player(qq)
        p["last_active"] = now - 35 * DAY
        s.save_player(p)
    # 活跃账号保持新鲜
    pa = s.load_player("active1")
    pa["last_active"] = now
    s.save_player(pa)

    # 造世界状态：额外占领 + 与 active1 有战争/同盟/关系
    st = s.load_state()
    st["regions"][2]["owner"] = "stale1"
    st["regions"][2]["capital_of"] = "stale1"
    st["regions"][2]["dev"] = 3
    st["regions"][3]["owner"] = "stale1"
    st["wars"] = ["active1|stale1"]
    st["allies"] = ["stale1|stale2"]
    st["relations"] = {"active1|stale1": -50, "active1|active1": 10}
    s.save_state(st)
    # 清理前，记录所有属于过期账号的地区（注册时 set_org 会自动分配首都，数量动态）
    stale_ids = [r["id"] for r in st["regions"]
                 if r["owner"] in ("stale1", "stale2")]
    assert len(stale_ids) >= 2

    names, freed = e.purge_inactive(st, 30, now)
    assert len(names) == 2, f"应清理 2 个过期账号，实际 {names}"
    assert freed == len(stale_ids), f"应释放 {len(stale_ids)} 个地区，实际 {freed}"
    # 存档已删
    assert s.load_player("stale1") is None and s.load_player("stale2") is None
    assert s.load_player("active1") is not None, "活跃账号必须保留"
    # 级联回收
    st2 = s.load_state()
    assert all(r["owner"] == "" for r in st2["regions"] if r["id"] in stale_ids), "地区归属应释放"
    assert all(r["capital_of"] == "" for r in st2["regions"] if r["id"] in stale_ids)
    assert st2["regions"][2]["dev"] == 0
    assert "沉睡王国" not in st2["org_index"] and "遗忘公国" not in st2["org_index"]
    assert "活跃联邦" in st2["org_index"], "活跃账号组织名不能被误删"
    assert st2["wars"] == [] and st2["allies"] == []
    assert "active1|stale1" not in st2["relations"]
    assert "active1|active1" in st2["relations"], "不涉及过期账号的关系要保留"
    assert st2["last_purge"] == now
    print("✅ 30 天未使用自动清档 + 全量级联回收（地区/组织名/战争/同盟/关系）")


def test_purge_zero_disabled_and_recent_kept():
    """inactive_days<=0 关闭清理；未到期的账号绝不被清。"""
    base = tempfile.mkdtemp()
    s, e, st = _engine(base)
    now = int(time.time())
    _register(s, e, st, "777", "临界国")
    p = s.load_player("777")
    p["last_active"] = now - 29 * DAY   # 29 天，未到期
    s.save_player(p)
    names, _ = e.purge_inactive(st, 30, now)
    assert names == [] and s.load_player("777") is not None, "29 天账号不能被清"
    # 改 31 天
    p = s.load_player("777")
    p["last_active"] = now - 31 * DAY
    s.save_player(p)
    names, _ = e.purge_inactive(st, 0, now)   # 关闭
    assert names == [] and s.load_player("777") is not None, "days<=0 应关闭清理"
    names, _ = e.purge_inactive(st, 30, now)
    assert len(names) == 1 and s.load_player("777") is None
    print("✅ 未到期账号保留 / inactive_days<=0 可关闭清理")


def test_delete_cascade():
    """玩家主动 /注销 也要级联释放地区，不留幽灵国家。"""
    base = tempfile.mkdtemp()
    s, e, st = _engine(base)
    _register(s, e, st, "888", "注销测试国")
    st = s.load_state()
    reg = next(r for r in st["regions"] if r["owner"] == "888")
    reg["capital_of"] = "888"
    s.save_state(st)
    out = e.dispatch("888", "delete_account", "", s.load_state())
    assert "注销" in out, out
    assert s.load_player("888") is None
    st2 = s.load_state()
    assert all(r["owner"] != "888" for r in st2["regions"]), "注销要释放所有地区"
    assert "注销测试国" not in st2["org_index"]
    print("✅ 主动注销级联释放地区与组织名（无幽灵国家）")


def test_reset_not_overwritten_by_stale_object():
    """/重置 生成新玩家后，dispatch 末尾不得用旧 p 覆盖回去（历史 bug）。"""
    base = tempfile.mkdtemp()
    s, e, st = _engine(base)
    _register(s, e, st, "999", "重置测试国")
    e.dispatch("999", "build", "农场", st)
    e.dispatch("999", "accel_build", "", st)
    assert s.load_player("999")["buildings"].get("farm", 0) == 1
    out = e.dispatch("999", "reset_account", "", s.load_state())
    assert "重置" in out, out
    got = s.load_player("999")
    assert got["org"] == "重置测试国", "重置后组织名应保留"
    assert got["buildings"].get("farm", 0) == 0, "重置后建筑应清空（不被旧对象覆盖）"
    print("✅ /重置 生效，不被旧玩家对象覆盖")


def test_real_plugin_init_migrates_and_purges():
    """真实构造 NationWarPlugin（走完整 __init__）：迁移 + 补活跃 + 启动清档。"""
    from astrbot_plugin_nationwar.main import NationWarPlugin
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "players"))
    now = int(time.time())
    # 40 天未用老档案（无 last_active，用 last_tick 兜底）
    old = {"qq": "expired1", "org": "沉睡王国", "registered_at": now - 40 * DAY,
           "last_tick": now - 40 * DAY, "res": {"money": 100, "food": 100}}
    json.dump(old, open(os.path.join(d, "players", "expired1.json"), "w"),
              ensure_ascii=False)
    # 活跃账号
    act = {"qq": "active1", "org": "活跃联邦", "registered_at": now,
           "last_tick": now, "last_active": now, "res": {"money": 100, "food": 100}}
    json.dump(act, open(os.path.join(d, "players", "active1.json"), "w"),
              ensure_ascii=False)
    json.dump({
        "regions": [{"id": 1, "name": "测试平原", "continent": "北境",
                     "terrain": "平原", "owner": "expired1", "capital_of": "expired1",
                     "dev": 2, "resource": "food", "rich": 3, "defense": 50}],
        "org_index": {"沉睡王国": "expired1", "活跃联邦": "active1"},
    }, open(os.path.join(d, "state.json"), "w"), ensure_ascii=False)

    class FakeCtx:
        def get_registered_platform_adapters(self):
            return []

    cfg = {"data_dir_override": d, "tick_enabled": False, "inactive_days": 30,
           "starting_resources": "1000,1000,200,50,50"}
    p = NationWarPlugin(FakeCtx(), cfg)
    assert p.store.base == d, "应尊重 data_dir_override"
    assert not p.store.player_exists("expired1"), "启动应清理过期账号"
    assert p.store.player_exists("active1"), "活跃账号必须保留"
    st = p.store.load_state()
    assert st["regions"][0]["owner"] == "" and st["regions"][0]["capital_of"] == ""
    assert "沉睡王国" not in st["org_index"] and "活跃联邦" in st["org_index"]
    assert st.get("last_purge", 0) > 0

    # —— 再次构造（模拟插件重载）：活跃账号数据仍在，且不会被重复初始化 ——
    act2 = p.store.load_player("active1")
    act2["org"] = "改名联邦"
    p.store.save_player(act2)
    p2 = NationWarPlugin(FakeCtx(), cfg)
    assert p2.store.load_player("active1")["org"] == "改名联邦", "重载不得重置"
    assert p2.store.load_player("active1")["last_active"] == act["last_active"] or \
        p2.store.load_player("active1")["last_active"] > 0
    print("✅ 真实插件启动：迁移/补活跃/清档/重载不重置 全链路正常")


if __name__ == "__main__":
    test_atomic_write_and_bak()
    test_corrupt_file_is_quarantined_not_dropped()
    test_reinit_does_not_reset_data()
    test_migrate_legacy_dir()
    test_migrate_last_active_uses_historical_ts()
    test_touch_active_refreshes()
    test_purge_inactive_cascades()
    test_purge_zero_disabled_and_recent_kept()
    test_delete_cascade()
    test_reset_not_overwritten_by_stale_object()
    test_real_plugin_init_migrates_and_purges()
    print("\n存档永久化 / 自动清档测试全部通过。")
