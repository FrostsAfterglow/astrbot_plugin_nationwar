#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成国家战争插件的全部静态数据与 250+ 指令目录。

产出（写入插件 data/ 目录）：
  world.json      虚拟世界地图（6 大陆 / 64 地区）
  buildings.json  建筑目录
  techs.json      科技目录
  units.json      兵种目录
  policies.json   政策目录
  commands.json   指令目录（两张指令图的数据源）

运行：python scripts/gen_data.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, "..", "data"))
os.makedirs(DATA, exist_ok=True)


# ---------------------------------------------------------------------------
# 1. 建筑目录（30 种）
# 字段：id, name, cat(分类), maxlv(最高等级), cost(每级造价 dict),
#       upkeep(每级维护 dict), prod(每级产出 dict), desc
# ---------------------------------------------------------------------------
BUILDINGS = [
    ("farm", "农场", "生产", 10, {"money": 80, "food": 0}, {"food": 0}, {"food": 12}, "基础粮食生产，稳定供给人口。"),
    ("granary", "粮仓", "生产", 8, {"money": 120, "food": 60}, {"food": 0}, {"food": 8}, "提升粮食储存上限并少量增产。"),
    ("mine", "矿场", "生产", 10, {"money": 150, "food": 0}, {"rare": 0}, {"rare": 4}, "开采稀有金属，科技与造兵刚需。"),
    ("oilwell", "油井", "生产", 10, {"money": 200, "food": 0}, {"oil": 0}, {"oil": 10}, "开采石油，机械化部队的燃料。"),
    ("rareore", "稀有矿", "生产", 8, {"money": 260, "food": 0}, {"rare": 0}, {"rare": 7}, "高品位稀有矿，高级科技核心材料。"),
    ("factory", "工厂", "生产", 10, {"money": 220, "rare": 4}, {"money": 0}, {"money": 18}, "制造商品换取资金。"),
    ("steel", "炼钢厂", "生产", 8, {"money": 300, "rare": 6}, {"rare": 0}, {"rare": 3, "money": 6}, "冶金工业，支撑重工业。"),
    ("chem", "化工厂", "生产", 8, {"money": 320, "oil": 8, "rare": 4}, {"oil": 0}, {"oil": 4, "money": 8}, "化工产出，燃料与材料。"),
    ("power", "发电厂", "生产", 8, {"money": 180, "rare": 2}, {"money": 0}, {"money": 10}, "提供电力，降低其他建筑维护。"),
    ("nuclear", "核电厂", "生产", 6, {"money": 800, "rare": 20}, {"money": 0}, {"money": 40}, "海量电力，高耗能科技基石。"),
    ("research", "研究中心", "科研", 10, {"money": 260, "rare": 6}, {"tech": 0}, {"tech": 6}, "产出科技点，解锁未来。"),
    ("warehouse", "仓库", "后勤", 8, {"money": 100}, {"money": 0}, {}, "提升资源储存上限。"),
    ("radar", "雷达站", "军事", 8, {"money": 240, "rare": 4}, {"money": 0}, {}, "提升侦察与防御预警。"),
    ("aa", "防空炮", "军事", 8, {"money": 200, "rare": 3}, {"money": 0}, {}, "拦截空袭与导弹。"),
    ("barracks", "兵营", "军事", 10, {"money": 160, "food": 40}, {"food": 0}, {}, "训练陆军的基础设施。"),
    ("tankplant", "坦克厂", "军事", 8, {"money": 360, "rare": 8}, {"money": 0}, {}, "生产装甲车辆。"),
    ("dock", "船坞", "军事", 8, {"money": 420, "rare": 10}, {"money": 0}, {}, "建造舰船，需沿海。"),
    ("airbase", "空军基地", "军事", 8, {"money": 480, "rare": 12}, {"money": 0}, {}, "起降作战飞机。"),
    ("missile", "导弹基地", "军事", 6, {"money": 600, "rare": 18}, {"money": 0}, {}, "部署弹道与巡航导弹。"),
    ("space", "航天中心", "军事", 4, {"money": 1200, "rare": 40}, {"money": 0}, {}, "发射卫星与太空威慑。"),
    ("training", "训练营", "军事", 8, {"money": 180, "food": 30}, {"food": 0}, {}, "提升新兵训练效率。"),
    ("supply", "补给站", "后勤", 8, {"money": 140, "food": 20}, {"food": 0}, {"food": 4}, "保障前线补给，减少战损。"),
    ("hospital", "医院", "社会", 8, {"money": 160, "food": 20}, {"food": 0}, {}, "提升幸福度与人口上限。"),
    ("school", "学校", "社会", 8, {"money": 150}, {"money": 0}, {"tech": 2}, "提升教育与科技点。"),
    ("tv", "电视台", "社会", 6, {"money": 220}, {"money": 0}, {}, "提升声望与影响力。"),
    ("intel", "情报局", "谍报", 6, {"money": 300, "rare": 6}, {"money": 0}, {}, "提升谍报与反间谍能力。"),
    ("embassy", "大使馆", "外交", 6, {"money": 200}, {"money": 0}, {}, "提升外交影响力。"),
    ("market", "市场", "经济", 8, {"money": 130}, {"money": 0}, {"money": 6}, "促进贸易，增加资金。"),
    ("wall", "城墙", "防御", 8, {"money": 170, "rare": 2}, {"money": 0}, {}, "提升地区防御值。"),
    ("capital", "首都", "行政", 5, {"money": 500, "rare": 10}, {"money": 0}, {"money": 12, "tech": 2}, "国家中枢，提供全局加成。"),
    ("cityhall", "市政厅", "行政", 8, {"money": 190, "food": 20}, {"food": 0}, {"money": 4}, "提升地区治理与稳定。"),
]


# ---------------------------------------------------------------------------
# 2. 科技目录（42 种，分 5 个层级，含前置）
# 字段：id, name, tier, cost(科技点), pre(前置列表), unlocks(解锁说明), desc
# ---------------------------------------------------------------------------
TECHS = [
    ("agri", "农业", 1, 30, [], "解锁高效农场", "基础农业技术。"),
    ("mining", "采矿", 1, 30, [], "解锁矿场增产", "基础采矿技术。"),
    ("oilrefine", "炼油", 1, 40, ["mining"], "解锁油井", "石油提炼。"),
    ("metallurgy", "冶金", 2, 60, ["mining"], "解锁炼钢厂", "金属冶炼。"),
    ("powergrid", "电力", 2, 60, [], "解锁发电厂", "电网技术。"),
    ("chemtech", "化工", 2, 70, ["oilrefine"], "解锁化工厂", "化学工业。"),
    ("nucleart", "核能", 3, 160, ["powergrid", "metallurgy"], "解锁核电厂", "核裂变发电。"),
    ("computer", "计算机", 3, 120, [], "解锁网络战", "信息处理。"),
    ("radart", "雷达技术", 2, 70, ["powergrid"], "解锁雷达站", "远程探测。"),
    ("infantry", "步兵科技", 1, 30, [], "解锁步兵", "单兵装备。"),
    ("artillery", "炮兵科技", 2, 70, ["metallurgy"], "解锁炮兵", "火力压制。"),
    ("armor", "装甲科技", 3, 130, ["metallurgy"], "解锁坦克", "机械化突击。"),
    ("heli", "直升机", 3, 140, ["powergrid"], "解锁直升机", "空中机动。"),
    ("airforce", "空军科技", 4, 220, ["powergrid", "computer"], "解锁战斗机/轰炸机", "制空权。"),
    ("navy", "海军科技", 3, 150, ["metallurgy"], "解锁驱逐舰", "海上力量。"),
    ("submarine", "潜艇技术", 4, 200, ["navy"], "解锁潜艇", "水下威慑。"),
    ("carrier", "航母技术", 5, 320, ["submarine", "airforce"], "解锁航母", "海上机场。"),
    ("missilet", "导弹技术", 4, 240, ["computer", "metallurgy"], "解锁导弹基地", "远程打击。"),
    ("nuclearw", "核武器", 5, 400, ["nucleart", "missilet"], "解锁核打击", "战略威慑。"),
    ("stealth", "隐形技术", 4, 260, ["airforce", "computer"], "提升突防", "隐身设计。"),
    ("ewar", "电子战", 4, 230, ["computer"], "解锁电子战", "电磁对抗。"),
    ("cyber", "网络战", 4, 250, ["computer"], "解锁网络战单位", "信息攻防。"),
    ("bio", "生物技术", 3, 140, [], "解锁医疗加成", "生命科技。"),
    ("gene", "基因工程", 4, 280, ["bio"], "解锁高级兵种", "基因强化。"),
    ("nano", "纳米技术", 5, 360, ["chemtech", "computer"], "全军强化", "微观制造。"),
    ("quantum", "量子技术", 5, 380, ["computer"], "解锁卫星/破译", "量子计算。"),
    ("laser", "激光技术", 4, 240, ["powergrid"], "解锁防空升级", "定向能。"),
    ("satellite", "卫星技术", 4, 260, ["space" if False else "rocket"], "解锁卫星", "天基侦察。"),
    ("rocket", "火箭技术", 3, 150, ["metallurgy"], "解锁航天中心", "运载能力。"),
    ("spaceflight", "航天飞机", 5, 340, ["satellite", "rocket"], "太空部署", "可复用航天器。"),
    ("logistics", "物流", 2, 60, [], "提升补给", "运输效率。"),
    ("mobilize", "动员", 2, 60, [], "提升征兵", "全民动员。"),
    ("psywar", "心理战", 3, 130, ["tv" if False else "media"], "提升威慑", "舆论攻势。"),
    ("media", "传媒", 2, 70, [], "解锁电视台", "信息传播。"),
    ("diplomacy", "外交学", 2, 60, [], "解锁大使馆", "国际关系。"),
    ("economics", "经济学", 2, 70, [], "提升资金产出", "宏观管理。"),
    ("governance", "治国术", 3, 130, ["economics"], "提升稳定", "国家管理。"),
    ("fortify", "要塞工程", 3, 120, ["metallurgy"], "解锁城墙升级", "筑城学。"),
    ("recon", "侦察术", 2, 60, ["radart"], "提升侦察", "情报搜集。"),
    ("ai", "人工智能", 5, 420, ["quantum", "computer"], "全军智能", "自主系统。"),
    ("drone", "无人机", 4, 220, ["computer", "powergrid"], "解锁无人机", "无人平台。"),
]


# ---------------------------------------------------------------------------
# 3. 兵种目录（25 种）
# 字段：id, name, cat(陆军/海军/空军/战略/特种), cost(dict), power(战力),
#       tech(所需科技 id 或 ""), desc
# ---------------------------------------------------------------------------
UNITS = [
    ("infantry", "步兵", "陆军", {"money": 20, "food": 5}, 10, "", "最基础的地面部队，无需科技即可征召。"),
    ("mg", "机枪兵", "陆军", {"money": 30, "food": 6}, 16, "infantry", "压制火力。"),
    ("artillery", "炮兵", "陆军", {"money": 80, "food": 10}, 35, "artillery", "远程火力支援。"),
    ("tank", "坦克", "陆军", {"money": 200, "rare": 6}, 90, "armor", "主力突击装甲。"),
    ("apc", "装甲车", "陆军", {"money": 120, "rare": 3}, 50, "armor", "机动运兵。"),
    ("engineer", "工兵", "陆军", {"money": 40, "food": 8}, 18, "infantry", "修桥筑路架墙。"),
    ("specops", "特种兵", "特种", {"money": 120, "rare": 4}, 60, "infantry", "渗透与斩首。"),
    ("guard", "国民警卫", "陆军", {"money": 25, "food": 5}, 12, "mobilize", "本土防御民兵。"),
    ("heli", "直升机", "空军", {"money": 260, "rare": 8}, 110, "heli", "空中突击。"),
    ("fighter", "战斗机", "空军", {"money": 380, "rare": 12}, 160, "airforce", "制空作战。"),
    ("bomber", "轰炸机", "空军", {"money": 520, "rare": 16}, 220, "airforce", "战略轰炸。"),
    ("drone", "无人机", "空军", {"money": 200, "rare": 6}, 95, "drone", "廉价侦察打击。"),
    ("destroyer", "驱逐舰", "海军", {"money": 360, "rare": 10}, 140, "navy", "海上护航。"),
    ("cruiser", "巡洋舰", "海军", {"money": 560, "rare": 16}, 210, "navy", "舰队核心。"),
    ("submarine", "潜艇", "海军", {"money": 480, "rare": 14}, 180, "submarine", "隐蔽猎杀。"),
    ("carrier", "航母", "海军", {"money": 1400, "rare": 40}, 400, "carrier", "海上空军基地。"),
    ("missile", "导弹车", "战略", {"money": 420, "rare": 18}, 200, "missilet", "机动弹道。"),
    ("samm", "防空导弹", "陆军", {"money": 240, "rare": 8}, 120, "laser", "区域防空。"),
    ("nukesilo", "核导弹", "战略", {"money": 1600, "rare": 60}, 600, "nuclearw", "战略核打击。"),
    ("cavalry", "侦察兵", "陆军", {"money": 35, "food": 6}, 22, "recon", "快速侦察。"),
    ("marine", "陆战队", "特种", {"money": 160, "rare": 5}, 80, "navy", "两栖登陆。"),
    ("cyberunit", "网络战单位", "特种", {"money": 300, "rare": 10}, 70, "cyber", "瘫痪敌方系统。"),
    ("satunit", "卫星", "战略", {"money": 900, "rare": 30}, 150, "satellite", "天基侦察预警。"),
    ("fortress", "要塞守备", "陆军", {"money": 180, "rare": 4}, 100, "fortify", "固定防御核心。"),
    ("spacetroop", "天军", "战略", {"money": 1800, "rare": 50}, 300, "spaceflight", "轨道打击力量。"),
]


# ---------------------------------------------------------------------------
# 4. 政策目录（20 种）
# 字段：id, name, effect(效果说明), desc
# ---------------------------------------------------------------------------
POLICIES = [
    ("market_econ", "市场经济", "资金产出+20%，幸福+5", "自由市场调节。"),
    ("planned_econ", "计划经济", "资源产出+10%，幸福-3", "国家统筹分配。"),
    ("conscription", "征兵制", "征兵成本-30%，幸福-5", "义务兵役。"),
    ("volunteer", "志愿兵制", "征兵成本+20%，幸福+5", "职业军人。"),
    ("welfare", "高福利", "幸福+10%，资金产出-10%", "民生优先。"),
    ("free_trade", "自由贸易", "贸易收益+30%", "敞开市场。"),
    ("protection", "贸易保护", "资金产出+10%，贸易收益-20%", "保护本土产业。"),
    ("martial", "军事管制", "造兵+20%，幸福-8", "战时体制。"),
    ("censorship", "言论管制", "稳定+8%，幸福-4", "信息管控。"),
    ("democracy", "民主", "稳定+10%，幸福+6", "民主体制。"),
    ("centralism", "集权", "稳定+12%，幸福-3", "强力中枢。"),
    ("green", "环保", "幸福+6%，石油产出-5%", "可持续发展。"),
    ("industrial", "工业化", "工厂/炼钢产出+20%", "重工业化。"),
    ("sci_tech", "科教兴国", "科技点+25%", "科技立国。"),
    ("strong_army", "强军", "全军战力+10%，资金-8%", "军事优先。"),
    ("good_neighbor", "睦邻", "外交收益+20%", "与邻为善。"),
    ("isolation", "孤立主义", "稳定+6%，外交收益-30%", "闭关自守。"),
    ("expansion", "扩张主义", "征服收益+20%，稳定-5", "领土渴望。"),
    ("religious_free", "宗教自由", "幸福+5%，稳定+3", "信仰多元。"),
    ("secular", "世俗化", "稳定+5%，幸福-2", "政教分离。"),
]


# ---------------------------------------------------------------------------
# 5. 世界地图：6 大陆 / 64 地区
# continent: (中文名, [地区名列表])
# 每个地区：name, terrain, resource(资源类型), rich(富集 1-5)
# resource in: food / oil / rare / metal / none
# ---------------------------------------------------------------------------
CONTINENTS = {
    "北境": [
        ("霜寒平原", "平原", "food", 3), ("银松岭", "森林", "rare", 2), ("冰原港", "沿海", "none", 1),
        ("铁壁要塞", "山地", "metal", 4), ("白河谷", "平原", "food", 4), ("极光城", "高原", "rare", 3),
        ("雪狼荒原", "沙漠", "none", 1), ("北关", "山地", "metal", 3), ("寒湖", "森林", "food", 2),
        ("冰晶矿脉", "山地", "rare", 5),
    ],
    "中土": [
        ("王都平原", "平原", "food", 5), ("金穗田", "平原", "food", 4), ("黑铁矿区", "山地", "metal", 5),
        ("碧水湾", "沿海", "food", 3), ("翠林", "森林", "rare", 3), ("中央高地", "高原", "rare", 2),
        ("龙脊山", "山地", "metal", 4), ("风车原", "平原", "none", 2), ("商道城", "平原", "none", 2),
        ("圣湖", "森林", "food", 3), ("晨曦港", "沿海", "none", 2),
    ],
    "瀚海": [
        ("赤沙大漠", "沙漠", "oil", 5), ("绿洲城邦", "沙漠", "food", 2), ("黑油海", "沙漠", "oil", 4),
        ("风蚀谷", "沙漠", "none", 1), ("海市", "沿海", "oil", 3), ("沙王城", "沙漠", "rare", 3),
        ("盐湖", "沙漠", "none", 1), ("瀚海咽喉", "沿海", "none", 2), ("流沙原", "沙漠", "oil", 3),
        ("日轮岛", "岛屿", "rare", 4),
    ],
    "烈日": [
        ("炎阳平原", "平原", "food", 3), ("火山带", "山地", "metal", 4), ("珍珠港", "沿海", "none", 2),
        ("翡翠群岛", "岛屿", "rare", 5), ("红土高原", "高原", "food", 2), ("烈日王城", "平原", "none", 2),
        ("珊瑚海", "沿海", "food", 3), ("黑曜石矿", "山地", "rare", 4), ("热风草原", "平原", "food", 4),
        ("落日角", "沿海", "oil", 3),
    ],
    "霜原": [
        ("永冻荒原", "沙漠", "none", 1), ("极星港", "沿海", "none", 2), ("冰晶森林", "森林", "rare", 3),
        ("雪豹岭", "山地", "metal", 3), ("寒霜矿", "山地", "rare", 4), ("冻土平原", "平原", "food", 2),
        ("白鲸湾", "沿海", "food", 3), ("极光高地", "高原", "rare", 2), ("冰封要塞", "山地", "metal", 4),
        ("霜语城", "平原", "none", 2),
    ],
    "远星": [
        ("新大陆平原", "平原", "food", 4), ("星陨谷", "高原", "rare", 5), ("远星港", "沿海", "none", 2),
        ("幽蓝森林", "森林", "rare", 4), ("巨岩山", "山地", "metal", 5), ("晨星原", "平原", "food", 3),
        ("深红沙漠", "沙漠", "oil", 4), ("潮汐岛", "岛屿", "food", 3), ("远星要塞", "山地", "metal", 4),
        ("曙光城", "平原", "none", 2), ("星海角", "沿海", "oil", 3),
    ],
}


def build_world():
    regions = []
    rid = 0
    for cont, areas in CONTINENTS.items():
        for (name, terrain, resource, rich) in areas:
            rid += 1
            # 资源富集度影响该地区的资源加成系数
            regions.append({
                "id": rid,
                "name": name,
                "continent": cont,
                "terrain": terrain,
                "resource": resource,
                "rich": rich,
                "defense": 30 + rich * 8 + (10 if terrain in ("山地", "高原", "岛屿") else 0),
                "owner": "",          # 占领者 QQ，空为无主
                "dev": 0,             # 开发度
                "capital_of": "",     # 若为某玩家首都地区则记 QQ
            })
    return {
        "name": "艾瑟拉大陆",
        "continents": list(CONTINENTS.keys()),
        "region_count": len(regions),
        "regions": regions,
    }


# ---------------------------------------------------------------------------
# 6. 指令目录（250+）
# 每条指令：key, name, alias, chart(1/2), group, desc, args, tag, target
#   tag 用于引擎路由；target 携带实体 id 或操作名
# ---------------------------------------------------------------------------
def gen_commands():
    cmds = []
    used_names = set()

    def add(key, name, chart, group, desc, args="", alias=None, tag="", target=None):
        alias = alias or []
        assert name not in used_names, f"指令重名: {name}"
        used_names.add(name)
        for a in alias:
            assert a not in used_names, f"别名重名: {name} 的别名 {a} 与已有指令冲突"
            used_names.add(a)
        cmds.append({
            "key": key, "name": name, "alias": alias, "chart": chart,
            "group": group, "desc": desc, "args": args, "tag": tag, "target": target,
        })

    # ---- 基础（chart1）----
    add("register", "注册", 1, "基础", "快速注册（账号=QQ号）。", "", alias=["signup", "regist"])
    add("set_org", "初始组织名", 1, "基础", "首次设置你的组织/国家名（仅无组织名时可用）。", "组织名", alias=["建组织", "创国"])
    add("rename_org", "重命名组织", 1, "基础", "修改你的组织名。", "新组织名", alias=["改名"])
    add("myinfo", "我的信息", 1, "基础", "查看你的国家总览。", "", alias=["信息", "国家"], tag="player_info")
    add("power", "国力", 1, "基础", "查看综合国力评分。", "", alias=["实力"], tag="power_view")
    add("res_total", "资源总览", 1, "基础", "查看全部资源与状态。", "", alias=["资源"], tag="res_total")

    # ---- 资源查询（chart1）----
    for nm, tg, ds in [
        ("资金", "money", "查看资金。"), ("粮食", "food", "查看粮食。"),
        ("石油", "oil", "查看石油。"), ("稀有金属", "rare", "查看稀有金属。"),
        ("科技点", "tech", "查看科技点。"), ("人口", "pop", "查看人口。"),
        ("幸福度", "happy", "查看幸福度。"), ("稳定度", "stable", "查看稳定度。"),
        ("声望", "rep", "查看国际声望。"),
    ]:
        add("res_" + tg, nm, 1, "资源", ds, "", alias=[], tag="res_view", target=tg)

    # ---- 建筑（chart1）----
    add("building_list", "建筑列表", 1, "建筑", "查看全部可建造建筑。", "", tag="building_list")
    add("my_buildings", "我的建筑", 1, "建筑", "查看你已建造的建筑。", "", tag="my_buildings")
    add("build", "建造", 1, "建筑", "建造/升级建筑：/建造 建筑名", "建筑名", alias=["建"], tag="build")
    add("upgrade", "升级建筑", 1, "建筑", "升级建筑：/升级建筑 建筑名", "建筑名", tag="build_upgrade")
    add("demolish", "拆除建筑", 1, "建筑", "拆除建筑返还部分资源：/拆除建筑 建筑名", "建筑名", tag="demolish")
    add("accel_build", "加速建造", 1, "建筑", "加速当前建造队列。", "", tag="accel_build")
    for bid, bn, *_ in BUILDINGS:
        add("b_" + bid, bn, 1, "建筑", f"快捷建造/升级「{bn}」。", "", tag="build", target=bid)

    # ---- 科技（chart1）----
    add("tech_list", "科技列表", 1, "科技", "查看全部科技与前置。", "", tag="tech_list")
    add("my_tech", "我的科技", 1, "科技", "查看已研究科技。", "", tag="my_tech")
    add("research", "研究", 1, "科技", "研究科技：/研究 科技名", "科技名", alias=["研发"], tag="research")
    add("cancel_tech", "取消研究", 1, "科技", "取消当前研究。", "", tag="cancel_tech")
    add("accel_tech", "加速研究", 1, "科技", "加速当前研究。", "", tag="accel_tech")
    for tid, tn, *_ in TECHS:
        add("t_" + tid, "研" + tn, 1, "科技", f"快捷研究「{tn}」。", "", tag="research", target=tid)

    # ---- 兵种/部队（chart1）----
    add("unit_list", "部队列表", 1, "军事", "查看全部可征召兵种。", "", tag="unit_list")
    add("my_army", "我的部队", 1, "军事", "查看你的军队编制。", "", alias=["部队"], tag="my_army")
    add("recruit", "征兵", 1, "军事", "征召兵种：/征兵 兵种名 数量", "兵种名 数量", alias=["征召"], tag="recruit")
    add("disband", "解散部队", 1, "军事", "解散部队：/解散部队 兵种名 数量", "兵种名 数量", tag="disband")
    add("train", "训练", 1, "军事", "提升部队训练度：/训练 兵种名", "兵种名", tag="train")
    add("general", "将领", 1, "军事", "查看你的将领。", "", tag="general")
    add("recruit_general", "招募将领", 1, "军事", "招募一名将领。", "", tag="recruit_general")
    add("promote_general", "提升将领", 1, "军事", "提升将领等级：/提升将领 将领名", "将领名", tag="promote_general")
    for uid, un, *_ in UNITS:
        add("u_" + uid, "征" + un, 1, "军事", f"快捷征召「{un}」：/征{un} 数量", "数量", tag="recruit", target=uid)

    # ---- 政策（chart1）----
    add("policy_list", "政策列表", 1, "政策", "查看全部国策。", "", tag="policy_list")
    add("my_policy", "我的政策", 1, "政策", "查看已颁布政策。", "", tag="my_policy")
    add("enact_policy", "颁布政策", 1, "政策", "颁布国策：/颁布政策 政策名", "政策名", tag="enact_policy")
    add("revoke_policy", "撤销政策", 1, "政策", "撤销国策：/撤销政策 政策名", "政策名", tag="revoke_policy")
    for pid, pn, *_ in POLICIES:
        add("p_" + pid, "颁" + pn, 1, "政策", f"快捷颁布「{pn}」。", "", tag="enact_policy", target=pid)

    # ---- 经济运营（chart1）----
    for nm, tg, ds, arg in [
        ("征税", "tax", "向国民征税获得资金。", ""),
        ("发工资", "pay", "为军队与官员发工资（影响稳定）。", ""),
        ("调税率", "settax", "调整税率：/调税率 0-100", "税率"),
        ("贸易", "trade", "与其他玩家/市场贸易换资金。", ""),
        ("卖资源", "sell", "出售资源：/卖资源 资源名 数量", "资源名 数量"),
        ("买资源", "buy", "购买资源：/买资源 资源名 数量", "资源名 数量"),
        ("投资", "invest", "投资基建换长期收益。", ""),
        ("援助", "aid", "援助他国：/援助 组织名 资金", "组织名 资金"),
        ("借贷", "loan", "向市场借贷。", ""),
        ("还债", "repay", "偿还债务。", ""),
        ("印钞", "print", "紧急印钞（引发通胀）。", ""),
        ("补贴", "subsidy", "补贴产业换产出。", ""),
        ("关税", "tariff", "设置关税影响贸易。", ""),
        ("私有化", "privatize", "私有化国企换资金。", ""),
        ("征收", "confiscate", "征收私产（降稳定）。", ""),
        ("募捐", "donate", "向国民募捐。", ""),
        ("国债", "bond", "发行国债筹资。", ""),
        ("黑市", "blackmarket", "高风险黑市交易。", ""),
        ("汇率", "exchange", "查看/调整汇率。", ""),
    ]:
        add("eco_" + tg, nm, 1, "经济", ds, arg, tag="economy", target=tg)

    # ---- 社会（chart1）----
    for nm, tg, ds in [
        ("移民", "immigrate", "吸引移民增加人口。"),
        ("人口普查", "census", "普查人口更新上限。"),
        ("安居", "settle", "建设民居提升幸福。"),
        ("城建", "urban", "推进城市建设。"),
        ("绿化", "green", "环境绿化提升幸福。"),
        ("治安", "security", "加强治安提升稳定。"),
        ("维稳", "stabilize", "维稳行动提升稳定。"),
        ("教育", "education", "投资教育换科技。"),
        ("医疗", "health", "投资医疗换幸福人口。"),
    ]:
        add("soc_" + tg, nm, 1, "社会", ds, "", tag="social", target=tg)

    # ================= CHART 2：军事外交 =================
    # ---- 军事行动（chart2）----
    add("mil_power", "军力", 2, "军事", "查看军队总战力。", "", tag="mil_power")
    add("attack", "进攻", 2, "军事", "进攻地区/国家：/进攻 地区名或组织名", "目标", tag="attack")
    add("defend", "防守", 2, "军事", "将部队派驻防守地区。", "地区名", tag="defend")
    add("patrol", "巡逻", 2, "军事", "部队巡逻提升警戒。", "地区名", tag="patrol")
    add("airstrike", "空袭", 2, "军事", "空袭敌方地区。", "地区名", tag="airstrike")
    add("bomb", "轰炸", 2, "军事", "战略轰炸敌方设施。", "地区名", tag="bomb")
    add("missile_strike", "导弹打击", 2, "军事", "导弹打击：/导弹打击 地区名", "地区名", tag="missile_strike")
    add("nuke", "核打击", 2, "军事", "核打击（需核导弹）：/核打击 地区名", "地区名", tag="nuke")
    add("land", "登陆", 2, "军事", "两栖登陆作战。", "地区名", tag="land")
    add("guerrilla", "游击", 2, "军事", "游击袭扰敌方。", "地区名", tag="guerrilla")
    add("blockade", "封锁", 2, "军事", "海上封锁敌方港口。", "地区名", tag="blockade")
    add("siege", "包围", 2, "军事", "包围敌方地区。", "地区名", tag="siege")
    add("reinforce", "增援", 2, "军事", "向战区增援部队。", "地区名", tag="reinforce")
    add("retreat", "撤退", 2, "军事", "部队撤离战区。", "地区名", tag="retreat")
    add("airdrop", "空降", 2, "军事", "空降部队夺占地区。", "地区名", tag="airdrop")
    add("shell", "炮击", 2, "军事", "远程炮击敌方。", "地区名", tag="shell")
    add("ewar_cmd", "电子战", 2, "军事", "电子干扰敌方系统。", "地区名", tag="ewar")
    add("decap", "斩首", 2, "军事", "斩首行动打击指挥。", "组织名", tag="decap")
    add("war_report", "我的战报", 2, "军事", "查看你的战斗记录。", "", tag="war_report")

    # ---- 外交（chart2）----
    add("establish", "建交", 2, "外交", "与他国建交：/建交 组织名", "组织名", tag="diplo", target="establish")
    add("ally", "结盟", 2, "外交", "提议结盟：/结盟 组织名", "组织名", tag="diplo", target="ally")
    add("break_rel", "断交", 2, "外交", "断绝外交关系。", "组织名", tag="diplo", target="break")
    add("declare_war", "宣战", 2, "外交", "向他国宣战：/宣战 组织名", "组织名", tag="diplo", target="war")
    add("ceasefire", "停战", 2, "外交", "请求停战。", "组织名", tag="diplo", target="cease")
    add("peace", "和谈", 2, "外交", "开启和谈。", "组织名", tag="diplo", target="peace")
    add("nonaggression", "互不侵犯", 2, "外交", "签订互不侵犯条约。", "组织名", tag="diplo", target="napt")
    add("vassal", "附庸", 2, "外交", "使小国成为附庸。", "组织名", tag="diplo", target="vassal")
    add("sanction", "制裁", 2, "外交", "经济制裁他国。", "组织名", tag="diplo", target="sanction")
    add("condemn", "谴责", 2, "外交", "外交谴责。", "组织名", tag="diplo", target="condemn")
    add("trade_pact", "贸易协定", 2, "外交", "签订贸易协定。", "组织名", tag="diplo", target="tradepact")
    add("embassy_cmd", "建使馆", 2, "外交", "在它国设立使馆。", "组织名", tag="diplo", target="embassy")
    add("summit", "峰会", 2, "外交", "召开国际峰会。", "", tag="diplo", target="summit")
    add("un_vote", "联合国", 2, "外交", "参与联合国投票。", "", tag="diplo", target="un")
    add("mediate", "调停", 2, "外交", "调停他国冲突。", "组织名", tag="diplo", target="mediate")
    add("recall_embassy", "撤大使", 2, "外交", "撤回驻外大使。", "组织名", tag="diplo", target="recall")
    add("befriend", "示好", 2, "外交", "对他国示好改善关系。", "组织名", tag="diplo", target="befriend")
    add("hostile", "敌视", 2, "外交", "公开敌视他国。", "组织名", tag="diplo", target="hostile")
    add("neutral", "中立声明", 2, "外交", "发布中立声明。", "", tag="diplo", target="neutral")
    add("condominium", "共管", 2, "外交", "提议共管地区。", "组织名", tag="diplo", target="condo")

    # ---- 地图（chart2）----
    add("world_map", "世界地图", 2, "地图", "查看完整虚拟世界地图。", "", alias=["地图"], tag="map", target="world")
    add("region_map", "区域地图", 2, "地图", "查看某地区详情：/区域地图 地区名", "地区名", tag="map", target="region")
    add("my_territory", "我的领地", 2, "地图", "查看你拥有的地区。", "", tag="map", target="territory")
    add("neighbors", "邻国", 2, "地图", "查看邻近国家/地区。", "", tag="map", target="neighbor")
    add("recon", "侦察", 2, "地图", "侦察敌方地区情报。", "地区名", tag="map", target="recon")
    add("satellite", "卫星", 2, "地图", "卫星扫描全局态势。", "", tag="map", target="sat")
    add("radar_scan", "雷达扫描", 2, "地图", "雷达扫描周边。", "", tag="map", target="radar")
    add("terrain", "地形", 2, "地图", "查看地形与通行性。", "地区名", tag="map", target="terrain")
    add("res_dist", "资源分布", 2, "地图", "查看全球资源分布。", "", tag="map", target="resdist")
    add("sphere", "势力图", 2, "地图", "查看各势力范围。", "", tag="map", target="sphere")

    # ---- 谍报（chart2）----
    add("spy", "间谍", 2, "谍报", "派遣间谍：/间谍 组织名", "组织名", tag="spy", target="send")
    add("counterspy", "反间谍", 2, "谍报", "强化反间谍。", "", tag="spy", target="counter")
    add("steal_intel", "窃取情报", 2, "谍报", "窃取敌方情报。", "组织名", tag="spy", target="steal")
    add("sabotage", "破坏", 2, "谍报", "破坏敌方设施。", "组织名", tag="spy", target="sabotage")
    add("assassinate", "暗杀", 2, "谍报", "暗杀敌方将领/领袖。", "组织名", tag="spy", target="assassin")
    add("subvert", "策反", 2, "谍报", "策反敌方部队。", "组织名", tag="spy", target="subvert")
    add("tap", "监听", 2, "谍报", "监听敌方通讯。", "组织名", tag="spy", target="tap")
    add("double_agent", "双重间谍", 2, "谍报", "安插双重间谍。", "组织名", tag="spy", target="double")

    # ---- 排行/系统（chart2）----
    add("rank_power", "国力排行", 2, "系统", "查看国力排行榜。", "", tag="system", target="power")
    add("rank_win", "战绩排行", 2, "系统", "查看战绩排行榜。", "", tag="system", target="win")
    add("rank_kill", "杀敌排行", 2, "系统", "查看杀敌排行榜。", "", tag="system", target="kill")
    add("online", "在线玩家", 2, "系统", "查看在线/已注册玩家。", "", tag="system", target="online")
    add("server_status", "服务器状态", 2, "系统", "查看服务器与游戏状态。", "", tag="system", target="status")
    add("help", "帮助", 2, "系统", "查看插件帮助与入门。", "", alias=["helpme"], tag="system", target="help")
    add("cmd_charts", "指令图", 2, "系统", "查看两张大型指令图。", "", tag="system", target="charts")
    add("rules", "游戏规则", 2, "系统", "查看完整游戏规则。", "", tag="system", target="rules")
    add("delete_account", "注销账号", 2, "系统", "注销并删除你的国家数据。", "", tag="system", target="delete")
    add("reset_account", "重开账号", 2, "系统", "重置你的国家重新开始。", "", tag="system", target="reset")

    return cmds


def main():
    world = build_world()
    cmds = gen_commands()
    buildings = [{"id": b[0], "name": b[1], "cat": b[2], "maxlv": b[3], "cost": b[4],
                 "upkeep": b[5], "prod": b[6], "desc": b[7]} for b in BUILDINGS]
    techs = [{"id": t[0], "name": t[1], "tier": t[2], "cost": t[3], "pre": t[4],
             "unlocks": t[5], "desc": t[6]} for t in TECHS]
    units = [{"id": u[0], "name": u[1], "cat": u[2], "cost": u[3], "power": u[4],
             "tech": u[5], "desc": u[6]} for u in UNITS]
    policies = [{"id": p[0], "name": p[1], "effect": p[2], "desc": p[3]} for p in POLICIES]

    out = {
        "world.json": world,
        "buildings.json": buildings,
        "techs.json": techs,
        "units.json": units,
        "policies.json": policies,
        "commands.json": cmds,
    }
    for fname, data in out.items():
        path = os.path.join(DATA, fname)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"写入 {fname}: {len(data) if isinstance(data, list) else 'obj'} 条")

    c1 = sum(1 for c in cmds if c["chart"] == 1)
    c2 = sum(1 for c in cmds if c["chart"] == 2)
    print(f"指令总数: {len(cmds)}  (图1 内政经济 {c1} / 图2 军事外交 {c2})")
    print(f"地区总数: {world['region_count']}")


if __name__ == "__main__":
    main()
