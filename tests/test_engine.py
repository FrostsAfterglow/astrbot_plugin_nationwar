#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""国家战争引擎离线测试：覆盖注册、建造、科技、征兵、进攻、外交、地图、排行等。"""
import os
import sys
import tempfile
import time
import json

# 让 core 包可导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.store import Store
from core.engine import Engine

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {extra}")


def new_engine():
    d = tempfile.mkdtemp(prefix="nw_test_")
    store = Store(d)
    eng = Engine(store, {"starting_resources": "1000,1000,200,50,50"}, logger=None)
    state = store.load_state()
    eng.ensure_world(state)
    return eng, store, state


def test_register_flow():
    print("== 注册流程 ==")
    eng, store, state = new_engine()
    # 未注册时其它指令被拦
    out = eng.dispatch("10001", "myinfo", "", state)
    check("未注册拦截", "尚未注册" in out, out)
    # 注册（快速注册，账号=QQ）
    out = eng.dispatch("10001", "register", "", state)
    check("注册成功提示", "已注册成功" in out and "初始组织名" in out, out)
    p = store.load_player("10001")
    check("玩家文件已建", p is not None)
    check("初始组织名为空", p["org"] == "")
    check("已分配家园地区", p["home_region"] != 0)
    # 无组织名不能玩
    out = eng.dispatch("10001", "build", "农场", state)
    check("无组织名拦截", "组织名" in out, out)
    # 设置组织名
    out = eng.dispatch("10001", "set_org", "曙光帝国", state)
    check("设组织名成功", "创建成功" in out and "首都" in out, out)
    p = store.load_player("10001")
    check("组织名已写入", p["org"] == "曙光帝国")
    check("首都地区归属", any(r["owner"] == "10001" for r in state["regions"]))
    check("org_index 已登记", state["org_index"].get("曙光帝国") == "10001")
    # 重复设组织名
    out = eng.dispatch("10001", "set_org", "另一个", state)
    check("重复设名拦截", "已设置" in out, out)


def test_build_and_economy():
    print("== 建造与经济 ==")
    eng, store, state = new_engine()
    eng.dispatch("20001", "register", "", state)
    eng.dispatch("20001", "set_org", "钢铁联邦", state)
    # 建造农场
    out = eng.dispatch("20001", "build", "农场", state)
    check("建造入队", "已开始建造" in out, out)
    p = store.load_player("20001")
    check("建造队列非空", len(p["build_queue"]) == 1)
    # 加速建造
    out = eng.dispatch("20001", "accel_build", "", state)
    check("加速完成", "加速完成" in out, out)
    p = store.load_player("20001")
    check("农场已建成", p["buildings"].get("farm") == 1)
    # 资源随时间产出：手动推进 last_tick 后 recalc
    p["last_tick"] = int(time.time()) - 3600  # 1 游戏小时
    eng.recalc(p, state, int(time.time()))
    check("农场产出粮食", p["res"]["food"] > 1000, str(p["res"]["food"]))
    # 建筑列表/我的建筑
    out = eng.dispatch("20001", "building_list", "", state)
    check("建筑列表", "农场" in out, out)
    out = eng.dispatch("20001", "my_buildings", "", state)
    check("我的建筑", "农场" in out, out)


def test_tech_and_units():
    print("== 科技与兵种 ==")
    eng, store, state = new_engine()
    eng.dispatch("30001", "register", "", state)
    eng.dispatch("30001", "set_org", "科技共和国", state)
    # 研究农业
    out = eng.dispatch("30001", "research", "农业", state)
    check("开始研究", "开始研发" in out, out)
    out = eng.dispatch("30001", "accel_tech", "", state)
    check("加速研究完成", "研发加速完成" in out, out)
    p = store.load_player("30001")
    check("农业已掌握", "agri" in p["techs"])
    # 征兵步兵（步兵无科技要求）
    out = eng.dispatch("30001", "recruit", "步兵 10", state)
    check("征兵成功", "已征召" in out, out)
    p = store.load_player("30001")
    check("步兵入账", p["units"].get("infantry") == 10)
    # 征坦克需装甲科技（未满足应失败）
    out = eng.dispatch("30001", "recruit", "坦克 1", state)
    check("缺科技征兵拦截", "需要先研究" in out, out)
    out = eng.dispatch("30001", "unit_list", "", state)
    check("兵种列表", "步兵" in out, out)
    out = eng.dispatch("30001", "my_army", "", state)
    check("我的部队", "步兵" in out, out)


def test_military_and_diplo():
    print("== 军事与外交 ==")
    eng, store, state = new_engine()
    # 玩家A
    eng.dispatch("40001", "register", "", state)
    eng.dispatch("40001", "set_org", "Alpha", state)
    eng.dispatch("40001", "accel_build", "", state) if False else None
    pA = store.load_player("40001")
    # 给A大量军队
    pA["units"]["infantry"] = 1000
    pA["res"]["money"] = 99999
    store.save_player(pA)
    # 玩家B
    eng.dispatch("40002", "register", "", state)
    eng.dispatch("40002", "set_org", "Beta", state)
    # A 进攻 B 的首都（B 无军队，应成功）
    bcap = store.load_player("40002")["capital_region"]
    r = eng.region_by_id(state, bcap)
    out = eng.dispatch("40001", "attack", r["name"], state)
    check("进攻占领成功", "进攻成功" in out and "占领" in out, out)
    check("地区归属变更", eng.region_by_id(state, bcap)["owner"] == "40001")
    check("夺取计数", store.load_player("40001")["stats"]["regions_taken"] == 1)
    # 外交：宣战
    out = eng.dispatch("40001", "declare_war", "Beta", state)
    check("宣战", "宣战" in out, out)
    check("战争状态", eng._pair("40001", "40002") in state["wars"])
    # 建交（与无主的第三方无意义，测试与 B 关系）
    out = eng.dispatch("40001", "establish", "Beta", state)
    check("建交提示", "外交关系" in out, out)


def test_map_and_system():
    print("== 地图与系统 ==")
    eng, store, state = new_engine()
    eng.dispatch("50001", "register", "", state)
    eng.dispatch("50001", "set_org", "地图国", state)
    out = eng.dispatch("50001", "world_map", "", state)
    check("世界地图", "艾瑟拉" in out, out)
    out = eng.dispatch("50001", "my_territory", "", state)
    check("我的领地", "领地" in out, out)
    out = eng.dispatch("50001", "satellite", "", state)
    check("卫星扫描", "卫星扫描" in out, out)
    out = eng.dispatch("50001", "rank_power", "", state)
    check("国力排行", "国力排行" in out, out)
    out = eng.dispatch("50001", "help", "", state)
    check("帮助", "入门" in out, out)
    out = eng.dispatch("50001", "rules", "", state)
    check("规则", "游戏规则" in out, out)
    out = eng.dispatch("50001", "server_status", "", state)
    check("服务器状态", "服务器状态" in out, out)


def test_res_view_gate():
    print("== 资源查询与门槛 ==")
    eng, store, state = new_engine()
    eng.dispatch("60001", "register", "", state)
    # 无组织名时资源查询被拦
    out = eng.dispatch("60001", "res_money", "", state)
    check("无组织名资源查询拦截", "组织名" in out, out)
    eng.dispatch("60001", "set_org", "钱庄", state)
    out = eng.dispatch("60001", "res_money", "", state)
    check("资源查询放行", "资金" in out, out)


def test_full_command_count():
    print("== 指令目录完整性 ==")
    eng, store, state = new_engine()
    cmds = store.commands()
    names = [c["name"] for c in cmds]
    check("指令总数>=200", len(cmds) >= 200, str(len(cmds)))
    check("指令名唯一", len(names) == len(set(names)))
    c1 = sum(1 for c in cmds if c["chart"] == 1)
    c2 = sum(1 for c in cmds if c["chart"] == 2)
    check("图1内政经济", c1 > 0, str(c1))
    check("图2军事外交", c2 > 0, str(c2))
    print(f"  指令总数 {len(cmds)}（图1 {c1} / 图2 {c2}）")


if __name__ == "__main__":
    test_register_flow()
    test_build_and_economy()
    test_tech_and_units()
    test_military_and_diplo()
    test_map_and_system()
    test_res_view_gate()
    test_full_command_count()
    print(f"\n结果：通过 {PASS} / 失败 {FAIL}")
    sys.exit(1 if FAIL else 0)
