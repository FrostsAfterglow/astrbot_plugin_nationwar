"""国家战争核心引擎：经济结算、注册门槛、指令路由、战斗/外交/地图/事件/排行。

所有指令最终都汇聚到 Engine.dispatch()。引擎只产出纯文本，@提及等呈现由 main.py 负责。
"""
import copy
import math
import random
import time

from .store import Store

SEC_PER_HOUR = 60.0          # 1 真实分钟 = 1 游戏小时
RES_KEYS = ["money", "food", "oil", "rare", "tech"]
RES_CN = {"money": "资金", "food": "粮食", "oil": "石油", "rare": "稀有金属", "tech": "科技点"}


def _find(items, name, key="name"):
    """按名称（含子串/小写）在列表中模糊查找。"""
    name = (name or "").strip()
    if not name:
        return None
    ln = name.lower()
    exact = [x for x in items if x[key].lower() == ln]
    if exact:
        return exact[0]
    sub = [x for x in items if ln in x[key].lower() or x[key].lower() in ln]
    if sub:
        return sub[0]
    return None


class Engine:
    def __init__(self, store: Store, config: dict, logger=None):
        self.store = store
        self.config = config or {}
        self.logger = logger
        self._b = {x["id"]: x for x in store.buildings()}
        self._t = {x["id"]: x for x in store.techs()}
        self._u = {x["id"]: x for x in store.units()}
        self._p = {x["id"]: x for x in store.policies()}
        self._cmds = store.commands()

    # ===================================================================
    # 世界与状态
    # ===================================================================
    def ensure_world(self, state: dict):
        if not state.get("regions"):
            tpl = self.store.world_template()
            state["regions"] = copy.deepcopy(tpl["regions"])
        return state

    def region_by_id(self, state, rid):
        for r in state["regions"]:
            if r["id"] == rid:
                return r
        return None

    def region_by_name(self, state, name):
        return _find(state["regions"], name, "name")

    def player_by_org(self, state, org):
        org = (org or "").strip()
        if not org:
            return None
        qq = state["org_index"].get(org.lower())
        if qq:
            return self.store.load_player(qq)
        return None

    def save(self, p=None, state=None):
        if p is not None:
            self.store.save_player(p)
        if state is not None:
            self.store.save_state(state)

    # ===================================================================
    # 经济结算（按真实流逝时间产出）
    # ===================================================================
    def recalc(self, p: dict, state: dict, now: int | None = None):
        now = now or int(time.time())
        hours = max(0.0, (now - p["last_tick"]) / SEC_PER_HOUR)
        if hours <= 0:
            return
        # 政策系数
        pols = set(p["policies"])
        money_f = 1.0
        if "market_econ" in pols:
            money_f += 0.20
        if "planned_econ" in pols:
            pass  # 已在资源产出体现
        if "industrial" in pols:
            money_f += 0.20
        if "sci_tech" in pols:
            pass
        if "welfare" in pols:
            money_f -= 0.10
        if "protection" in pols:
            money_f += 0.10
        if "strong_army" in pols:
            money_f -= 0.08

        happy_f = 0.5 + p["happy"] / 100.0
        stable_f = 0.6 + p["stable"] / 200.0
        eff = happy_f * stable_f

        # 建筑产出
        for bid, lvl in list(p["buildings"].items()):
            b = self._b.get(bid)
            if not b:
                continue
            for res, amt in b["prod"].items():
                gain = amt * lvl * eff * hours
                if res == "money":
                    gain *= money_f
                if res == "tech" and "sci_tech" in pols:
                    gain *= 1.25
                p["res"][res] = p["res"].get(res, 0) + gain

        # 资源上限（仓库/粮仓等影响，简化：固定上限 + 仓库等级）
        cap = 5000 + 2000 * p["buildings"].get("warehouse", 0)
        for res in RES_KEYS:
            if res != "tech":
                p["res"][res] = min(p["res"][res], cap)

        # 造兵/人口维护
        food_up = 0.0
        oil_up = 0.0
        for uid, cnt in p["units"].items():
            u = self._u.get(uid)
            if not u:
                continue
            cat = u["cat"]
            if cat in ("陆军", "特种"):
                food_up += 0.2 * cnt * hours
            elif cat == "空军":
                food_up += 0.1 * cnt * hours
                oil_up += 0.2 * cnt * hours
            elif cat == "海军":
                oil_up += 0.3 * cnt * hours
            elif cat == "战略":
                oil_up += 0.5 * cnt * hours

        p["res"]["food"] = p["res"].get("food", 0) - food_up
        p["res"]["oil"] = p["res"].get("oil", 0) - oil_up

        # 饥荒/缺油惩罚
        if p["res"]["food"] < 0:
            p["res"]["food"] = 0
            p["happy"] = max(0, p["happy"] - 3)
            p["stable"] = max(0, p["stable"] - 2)
        if p["res"]["oil"] < 0:
            p["res"]["oil"] = 0
            p["stable"] = max(0, p["stable"] - 1)

        # 人口增长（粮食充裕且幸福高）
        if p["res"]["food"] > 200 and p["happy"] > 50:
            grow = p["pop"] * 0.002 * hours * (p["happy"] - 50) / 50.0
            p["pop"] += grow

        # 研究进度（按截止时间结算，无需持续产出）
        if p["research"]["tech"]:
            tid = p["research"]["tech"]
            tech = self._t.get(tid)
            ends = p.get("research_ends_at", 0)
            if tech and tid not in p["techs"]:
                if now >= ends:
                    p["techs"][tid] = 1
                    p["research"] = {"tech": None, "progress": 0}
                    p.pop("research_ends_at", None)
                    p["log"].append(f"研究完成：{tech['name']}")
            else:
                p["research"] = {"tech": None, "progress": 0}
                p.pop("research_ends_at", None)

        # 建造队列
        remain = []
        for item in p["build_queue"]:
            if now >= item["ends_at"]:
                bid = item["building"]
                p["buildings"][bid] = item["to_level"]
                bn = self._b.get(bid, {}).get("name", bid)
                p["log"].append(f"建造完成：{bn} Lv{item['to_level']}")
            else:
                remain.append(item)
        p["build_queue"] = remain

        # 自然衰减/回复
        p["happy"] = max(0, min(100, p["happy"] + (60 - p["happy"]) * 0.01 * hours))
        p["stable"] = max(0, min(100, p["stable"] + (60 - p["stable"]) * 0.01 * hours))
        if "welfare" in pols:
            p["happy"] = min(100, p["happy"] + 0.02 * hours)
        if "censorship" in pols or "centralism" in pols or "martial" in pols:
            p["stable"] = min(100, p["stable"] + 0.02 * hours)

        p["last_tick"] = now

    # ===================================================================
    # 战力
    # ===================================================================
    def mil_power(self, p: dict) -> float:
        total = 0.0
        for uid, cnt in p["units"].items():
            u = self._u.get(uid)
            if u:
                total += cnt * u["power"]
        tech_mod = 1 + 0.02 * sum(p["techs"].values())
        gen_bonus = 1 + 0.05 * len(p["generals"])
        happy_mod = 0.6 + p["happy"] / 100.0
        stable_mod = 0.7 + p["stable"] / 200.0
        pols = set(p["policies"])
        if "strong_army" in pols:
            total *= 1.10
        return total * tech_mod * gen_bonus * happy_mod * stable_mod

    def power_score(self, p: dict, state: dict) -> float:
        score = 0.0
        score += p["res"]["money"] / 10.0
        score += p["pop"] / 10.0
        score += sum(p["buildings"].values()) * 6
        score += sum(u * self._u.get(uid, {}).get("power", 0) for uid, u in p["units"].items()) / 8.0
        score += sum(p["techs"].values()) * 25
        score += len([r for r in state["regions"] if r["owner"] == p["qq"]]) * 60
        score += max(0, p["rep"])
        return round(score, 1)

    # ===================================================================
    # 注册 / 组织（快速注册：账号=QQ号）
    # ===================================================================
    def do_register(self, qq: str, state: dict) -> str:
        self.ensure_world(state)
        if self.store.player_exists(qq):
            p = self.store.load_player(qq)
            if p and p.get("org"):
                return f"你已注册并建立了组织「{p['org']}」，无需重复注册。"
            return "你已注册但还未设置组织名，请使用：/初始组织名 你的国名"
        # 分配首个无主地区作为家园
        home = None
        for r in state["regions"]:
            if not r["owner"]:
                home = r["id"]
                break
        if home is None:
            home = state["regions"][0]["id"] if state["regions"] else 0
        start = self._parse_start()
        p = self.store.new_player(qq, "", start, home)
        self.store.save_player(p)
        self.save(state=state)
        return ("已注册成功，请输入你的组织名，指令：/初始组织名 组织名"
                "（仅在没有组织名的时候使用），不组织名称也不能游玩")

    def do_set_org(self, qq: str, org: str, state: dict) -> str:
        self.ensure_world(state)
        p = self.store.load_player(qq)
        if not p:
            return "你尚未注册，请先发送 /注册"
        if p.get("org"):
            return f"你已设置组织名为「{p['org']}」，如需修改请使用 /重命名组织 新名称"
        org = (org or "").strip()
        if len(org) < 2:
            return "组织名至少需要 2 个字，例如：/初始组织名 曙光帝国"
        if org.lower() in state["org_index"]:
            return f"组织名「{org}」已被他人占用，请换一个。"
        # 落定：家园地区归属 + 设为首都
        home = self.region_by_id(state, p["home_region"]) or state["regions"][0]
        home["owner"] = qq
        home["capital_of"] = qq
        home["dev"] = 1
        p["org"] = org
        p["capital_region"] = home["id"]
        state["org_index"][org.lower()] = qq
        self.save(p, state)
        return (f"🎉 组织「{org}」创建成功！你的首都位于【{home['name']}】（{home['continent']}）。\n"
                f"初始资源：资金{p['res']['money']:.0f} 粮食{p['res']['food']:.0f} 石油{p['res']['oil']:.0f} "
                f"稀有金属{p['res']['rare']:.0f} 科技点{p['res']['tech']:.0f}\n"
                f"入门：/建造 农场 → /研究 农业 → /征兵 步兵 10 → /帮助")

    def do_rename_org(self, qq: str, org: str, state: dict) -> str:
        p = self.store.load_player(qq)
        if not p or not p.get("org"):
            return "你还没有组织名，请先 /初始组织名 你的国名"
        org = (org or "").strip()
        if len(org) < 2:
            return "新组织名至少 2 个字。"
        old = p["org"].lower()
        if old in state["org_index"]:
            del state["org_index"][old]
        state["org_index"][org.lower()] = qq
        p["org"] = org
        self.save(p, state)
        return f"组织名已更改为「{org}」。"

    def _parse_start(self) -> dict:
        raw = str(self.config.get("starting_resources", "1000,1000,200,50,0"))
        parts = [x.strip() for x in raw.split(",")]
        try:
            return {
                "money": float(parts[0] or 1000),
                "food": float(parts[1] or 1000),
                "oil": float(parts[2] or 200),
                "rare": float(parts[3] or 50),
                "tech": float(parts[4] or 50),
            }
        except Exception:
            return {"money": 1000, "food": 1000, "oil": 200, "rare": 50, "tech": 50}

    # ===================================================================
    # 指令路由
    # ===================================================================
    NO_GATE = {"register", "set_org", "rename_org", "help", "rules", "charts",
               "status", "online", "delete", "reset"}

    def dispatch(self, qq: str, cmd_key: str, rest: str, state: dict) -> str:
        now = int(time.time())
        cmd = next((c for c in self._cmds if c["key"] == cmd_key), None)
        tag = cmd["tag"] if cmd else ""

        # 注册相关：永远放行（账号=QQ号，快速注册）
        if cmd_key == "register":
            return self.do_register(qq, state)
        if cmd_key == "set_org":
            return self.do_set_org(qq, rest, state)
        if cmd_key == "rename_org":
            return self.do_rename_org(qq, rest, state)

        p = self.store.load_player(qq)
        if not p:
            return "你尚未注册，请先发送 /注册 开始游戏。"
        self.recalc(p, state, now)

        need_org = cmd_key not in self.NO_GATE and tag not in ("system",)
        # system 里的 help/rules/charts/status/online/delete/reset 不需要组织名
        if tag == "system":
            need_org = cmd_key not in ("help", "rules", "charts", "status", "online", "delete", "reset")
        if need_org and not p.get("org"):
            self.save(p, state)
            return "你尚未设置组织名，无法游玩。请使用：/初始组织名 你的国名"

        # 路由
        try:
            out = self._route(p, cmd, tag, rest, state, now)
        except Exception as e:  # 永不直接崩溃
            if self.logger:
                self.logger.error("指令 %s 执行异常: %s", cmd_key, e)
            out = f"⚠️ 指令执行出错：{e}"
        self.save(p, state)
        return out

    def _route(self, p, cmd, tag, rest, state, now):
        if cmd is None:
            return "未知指令。"
        t = cmd.get("target")
        if tag == "player_info":
            return self._player_info(p, state)
        if tag == "power_view":
            return self._power_view(p, state)
        if tag == "res_total":
            return self._res_total(p)
        if tag == "res_view":
            return self._res_view(p, t)
        if tag == "building_list":
            return self._building_list()
        if tag == "my_buildings":
            return self._my_buildings(p)
        if tag in ("build", "build_upgrade"):
            return self._build(p, rest, state, now, t)
        if tag == "demolish":
            return self._demolish(p, rest, t)
        if tag == "accel_build":
            return self._accel_build(p, now)
        if tag == "tech_list":
            return self._tech_list()
        if tag == "my_tech":
            return self._my_tech(p)
        if tag in ("research",):
            return self._research(p, rest, t)
        if tag == "cancel_tech":
            return self._cancel_tech(p)
        if tag == "accel_tech":
            return self._accel_tech(p, now)
        if tag == "unit_list":
            return self._unit_list()
        if tag == "my_army":
            return self._my_army(p)
        if tag in ("recruit",):
            return self._recruit(p, rest, t, state)
        if tag == "disband":
            return self._disband(p, rest)
        if tag == "train":
            return self._train(p, rest)
        if tag == "general":
            return self._general(p)
        if tag == "recruit_general":
            return self._recruit_general(p)
        if tag == "promote_general":
            return self._promote_general(p, rest)
        if tag == "policy_list":
            return self._policy_list()
        if tag == "my_policy":
            return self._my_policy(p)
        if tag in ("enact_policy",):
            return self._enact_policy(p, rest, t)
        if tag == "revoke_policy":
            return self._revoke_policy(p, rest)
        if tag == "economy":
            return self._economy(p, t, rest, state)
        if tag == "social":
            return self._social(p, t)
        if tag == "mil_power":
            return self._mil_power_cmd(p, state)
        if tag in ("attack", "defend", "patrol", "airstrike", "bomb", "missile_strike",
                   "nuke", "land", "guerrilla", "blockade", "siege", "reinforce",
                   "retreat", "airdrop", "shell", "ewar", "decap"):
            return self._military(p, tag, rest, state, now)
        if tag == "war_report":
            return self._war_report(p)
        if tag == "diplo":
            return self._diplo(p, t, rest, state)
        if tag == "map":
            return self._map(p, t, rest, state)
        if tag == "spy":
            return self._spy(p, t, rest, state)
        if tag == "system":
            return self._system(p, t, state)
        return "未知指令。"

    # ===================================================================
    # 各子系统实现
    # ===================================================================
    def _fmt_res(self, p):
        r = p["res"]
        return (f"资金 {r['money']:.0f}｜粮食 {r['food']:.0f}｜石油 {r['oil']:.0f}｜"
                f"稀有金属 {r['rare']:.0f}｜科技点 {r['tech']:.0f}")

    def _player_info(self, p, state):
        regions = len([r for r in state["regions"] if r["owner"] == p["qq"]])
        lines = [
            f"🏰 「{p['org']}」国家总览",
            f"人口 {p['pop']:.0f}｜幸福 {p['happy']:.0f}｜稳定 {p['stable']:.0f}｜声望 {p['rep']:.0f}",
            f"资源：{self._fmt_res(p)}",
            f"建筑 {sum(p['buildings'].values())} 座｜科技 {len(p['techs'])} 项｜"
            f"部队战力 {self.mil_power(p):.0f}",
            f"控制地区 {regions} 个｜债务 {p['debt']:.0f}｜国策 {len(p['policies'])} 项",
            f"战绩 胜{p['stats']['wars_won']}/负{p['stats']['wars_lost']} 击杀{p['stats']['kills']}",
        ]
        return "\n".join(lines)

    def _power_view(self, p, state):
        score = self.power_score(p, state)
        regions = len([r for r in state["regions"] if r["owner"] == p["qq"]])
        return (f"📊 「{p['org']}」综合国力：{score}\n"
                f"（资源 {p['res']['money']/10:.0f} + 人口 {p['pop']/10:.0f} + 建筑 "
                f"{sum(p['buildings'].values())*6} + 军力 "
                f"{self.mil_power(p)/8:.0f} + 科技 {len(p['techs'])*25} + 领地 {regions*60} + 声望 {max(0,p['rep'])}）")

    def _res_total(self, p):
        r = p["res"]
        cap = 5000 + 2000 * p["buildings"].get("warehouse", 0)
        return ("📦 资源总览：\n" + self._fmt_res(p) +
                f"\n人口 {p['pop']:.0f}｜幸福 {p['happy']:.0f}｜稳定 {p['stable']:.0f}｜"
                f"税率 {p['tax_rate']}%｜储存上限 {cap:.0f}")

    def _res_view(self, p, res):
        r = p["res"]
        if res == "pop":
            return f"👥 人口：{p['pop']:.0f}（幸福 {p['happy']:.0f} 稳定 {p['stable']:.0f}）"
        if res == "happy":
            return f"😊 幸福度：{p['happy']:.0f}/100"
        if res == "stable":
            return f"🛡️ 稳定度：{p['stable']:.0f}/100"
        if res == "rep":
            return f"🌟 国际声望：{p['rep']:.0f}"
        return f"💰 {RES_CN[res]}：{r[res]:.0f}"

    def _building_list(self):
        lines = ["🏗️ 建筑列表（/建造 名称 进行建造）："]
        for b in self.store.buildings():
            cost = " ".join(f"{RES_CN.get(k, k)}{v}" for k, v in b["cost"].items() if v)
            prod = " ".join(f"{RES_CN.get(k, k)}+{v}" for k, v in b["prod"].items()) or "—"
            lines.append(f"· {b['name']}（{b['cat']} 上限Lv{b['maxlv']}）造价{cost} 产出{prod}")
        return "\n".join(lines)

    def _my_buildings(self, p):
        if not p["buildings"]:
            return "你还没有任何建筑，先用 /建造 农场 起步。"
        lines = [f"🏛️ 「{p['org']}」建筑："]
        for bid, lvl in sorted(p["buildings"].items(), key=lambda x: -x[1]):
            b = self._b.get(bid, {})
            lines.append(f"· {b.get('name', bid)} Lv{lvl}")
        if p["build_queue"]:
            lines.append("⏳ 建造中：")
            for it in p["build_queue"]:
                b = self._b.get(it["building"], {})
                left = max(0, it["ends_at"] - int(time.time()))
                lines.append(f"   {b.get('name', it['building'])}→Lv{it['to_level']}（{left}s）")
        return "\n".join(lines)

    def _build(self, p, rest, state, now, target):
        name = target if target else (rest or "").strip()
        b = _find(self.store.buildings(), name)
        if not b:
            return "未找到该建筑，请用 /建筑列表 查看名称。"
        cur = p["buildings"].get(b["id"], 0)
        if cur >= b["maxlv"]:
            return f"{b['name']} 已达最高等级 Lv{b['maxlv']}。"
        to_lv = cur + 1
        # 造价随等级递增
        cost_mul = 1 + 0.6 * cur
        cost = {k: v * cost_mul for k, v in b["cost"].items() if v}
        for k, v in cost.items():
            if p["res"].get(k, 0) < v:
                need = " ".join(f"{RES_CN.get(kk, kk)}{vv:.0f}" for kk, vv in cost.items())
                return f"资源不足，{b['name']} Lv{to_lv} 需：{need}（当前 {self._fmt_res(p)}）"
        for k, v in cost.items():
            p["res"][k] -= v
        dur = 30 + int(sum(b["cost"].values()) / 20.0)
        p["build_queue"].append({"building": b["id"], "to_level": to_lv,
                                 "ends_at": now + dur})
        return (f"🚧 已开始建造 {b['name']} → Lv{to_lv}，约 {dur}s 后完成"
                f"（/加速建造 可立即完成）。")

    def _demolish(self, p, rest, target):
        name = target if target else (rest or "").strip()
        b = _find(self.store.buildings(), name)
        if not b or b["id"] not in p["buildings"]:
            return "你并未拥有该建筑。"
        lvl = p["buildings"][b["id"]]
        refund = {k: v * 0.4 * lvl for k, v in b["cost"].items() if v}
        for k, v in refund.items():
            p["res"][k] = p["res"].get(k, 0) + v
        del p["buildings"][b["id"]]
        rf = " ".join(f"{RES_CN.get(k, k)}+{v:.0f}" for k, v in refund.items())
        return f"已拆除 {b['name']}，返还 {rf}。"

    def _accel_build(self, p, now):
        if not p["build_queue"]:
            return "当前没有正在进行的建造。"
        done = []
        for it in p["build_queue"]:
            p["buildings"][it["building"]] = it["to_level"]
            done.append(self._b.get(it["building"], {}).get("name", it["building"]))
        p["build_queue"] = []
        return f"⚡ 加速完成：{', '.join(done)}"

    def _tech_list(self):
        lines = ["🔬 科技列表（/研究 名称 进行研发）："]
        for t in sorted(self.store.techs(), key=lambda x: x["tier"]):
            pre = "，前置：" + "、".join(self._t[x]["name"] for x in t["pre"]) if t["pre"] else ""
            lines.append(f"· [{t['tier']}级] {t['name']}（{t['cost']}科技点）{pre} — {t['unlocks']}")
        return "\n".join(lines)

    def _my_tech(self, p):
        if not p["techs"]:
            return "你尚未研究任何科技。用 /研究 农业 起步。"
        lines = [f"🔬 「{p['org']}」已掌握科技："]
        for tid in p["techs"]:
            lines.append(f"· {self._t[tid]['name']}")
        if p["research"]["tech"]:
            t = self._t[p["research"]["tech"]]
            ends = p.get("research_ends_at", 0)
            left = max(0, ends - int(time.time()))
            lines.append(f"⏳ 研发中：{t['name']}（剩余约 {left}s）")
        return "\n".join(lines)

    def _research(self, p, rest, target):
        name = target if target else (rest or "").strip()
        t = _find(self.store.techs(), name)
        if not t:
            return "未找到该科技，请用 /科技列表 查看。"
        if t["id"] in p["techs"]:
            return f"你已掌握 {t['name']}。"
        if p["research"]["tech"]:
            cur = self._t[p["research"]["tech"]]
            return f"当前正在研发 {cur['name']}，请先 /取消研究。"
        for pre in t["pre"]:
            if pre not in p["techs"]:
                return f"前置科技未满足：需先研究 {self._t[pre]['name']}。"
        if p["res"]["tech"] < t["cost"]:
            return f"科技点不足（需 {t['cost']}，当前 {p['res']['tech']:.0f}）。可多建研究中心产出科技点。"
        p["res"]["tech"] -= t["cost"]
        dur = 60 + t["cost"] * 3
        p["research"] = {"tech": t["id"], "progress": 0}
        p["research_ends_at"] = int(time.time()) + dur
        return f"🔬 开始研发 {t['name']}（消耗 {t['cost']} 科技点），约 {dur}s 后完成。/加速研究 可立即完成。"

    def _cancel_tech(self, p):
        if not p["research"]["tech"]:
            return "当前没有正在研发的科技。"
        t = self._t[p["research"]["tech"]]
        p["res"]["tech"] += t["cost"]  # 退还已消耗科技点
        p["research"] = {"tech": None, "progress": 0}
        p.pop("research_ends_at", None)
        return f"已取消研发 {t['name']}，已退还 {t['cost']} 科技点。"

    def _accel_tech(self, p, now):
        if not p["research"]["tech"]:
            return "当前没有正在研发的科技。"
        t = self._t[p["research"]["tech"]]
        p["techs"][t["id"]] = 1
        p["research"] = {"tech": None, "progress": 0}
        p.pop("research_ends_at", None)
        return f"⚡ 研发加速完成：{t['name']}！"

    def _unit_list(self):
        lines = ["⚔️ 兵种列表（/征兵 兵种 数量）："]
        for u in self.store.units():
            req = f"需科技：{self._t[u['tech']]['name']}" if u["tech"] else "无前置"
            cost = " ".join(f"{RES_CN.get(k, k)}{v}" for k, v in u["cost"].items())
            lines.append(f"· {u['name']}（{u['cat']} 战力{u['power']}）{cost} {req}")
        return "\n".join(lines)

    def _my_army(self, p):
        if not p["units"]:
            return "你还没有军队，用 /征兵 步兵 10 组建部队。"
        lines = [f"⚔️ 「{p['org']}」军队（总战力 {self.mil_power(p):.0f}）："]
        for uid, cnt in p["units"].items():
            u = self._u.get(uid, {})
            lines.append(f"· {u.get('name', uid)} ×{cnt:.0f}")
        if p["generals"]:
            lines.append("🎖️ 将领：" + "、".join(g["name"] for g in p["generals"]))
        return "\n".join(lines)

    def _recruit(self, p, rest, target, state):
        if target:
            name = target
            # rest 可能是数量
            cnt_txt = (rest or "").strip()
        else:
            parts = (rest or "").split()
            name = parts[0] if parts else ""
            cnt_txt = parts[1] if len(parts) > 1 else "1"
        u = _find(self.store.units(), name)
        if not u:
            return "未找到该兵种，请用 /部队列表 查看。"
        try:
            cnt = max(1, int(float(cnt_txt)))
        except Exception:
            cnt = 1
        if u["tech"] and u["tech"] not in p["techs"]:
            return f"需要先研究 {self._t[u['tech']]['name']} 才能征召 {u['name']}。"
        cost = {k: v * cnt for k, v in u["cost"].items()}
        for k, v in cost.items():
            if p["res"].get(k, 0) < v:
                need = " ".join(f"{RES_CN.get(kk, kk)}{vv:.0f}" for kk, vv in cost.items())
                return f"资源不足，{u['name']}×{cnt} 需：{need}"
        for k, v in cost.items():
            p["res"][k] -= v
        p["units"][u["id"]] = p["units"].get(u["id"], 0) + cnt
        return f"✅ 已征召 {u['name']} ×{cnt}（当前 {p['units'][u['id']]:.0f}）。"

    def _disband(self, p, rest):
        parts = (rest or "").split()
        if not parts:
            return "用法：/解散部队 兵种 数量"
        name = parts[0]
        cnt = int(parts[1]) if len(parts) > 1 else 1
        u = _find(self.store.units(), name)
        if not u or u["id"] not in p["units"]:
            return "你并未拥有该兵种。"
        have = p["units"][u["id"]]
        cnt = min(cnt, int(have))
        p["units"][u["id"]] = have - cnt
        if p["units"][u["id"]] <= 0:
            del p["units"][u["id"]]
        return f"已解散 {u['name']} ×{cnt}。"

    def _train(self, p, rest):
        u = _find(self.store.units(), rest)
        if not u or u["id"] not in p["units"]:
            return "你未拥有该兵种，无法训练。"
        p["units"][u["id"]] += 0  # 占位；训练提升战力系数（简化：小幅提升 happy）
        p["happy"] = min(100, p["happy"] + 1)
        return f"{u['name']} 部队完成一轮训练，士气提升。"

    def _general(self, p):
        if not p["generals"]:
            return "你还没有将领，用 /招募将领 招募。"
        lines = ["🎖️ 你的将领："]
        for g in p["generals"]:
            lines.append(f"· {g['name']} Lv{g['level']}（经验 {g['exp']:.0f}）")
        return "\n".join(lines)

    def _recruit_general(self, p):
        if len(p["generals"]) >= 5:
            return "将领已满（上限 5），请先 /提升将领。"
        names = ["赵云", "岳飞", "拿破仑", "汉尼拔", "隆美尔", "诸葛亮", "凯撒", "孙武",
                 "巴顿", "朱可夫", "李舜臣", "华盛顿"]
        nm = random.choice(names)
        p["generals"].append({"name": nm, "level": 1, "exp": 0})
        return f"🎖️ 招募将领成功：{nm}（Lv1）。"

    def _promote_general(self, p, rest):
        g = _find(p["generals"], rest, "name")
        if not g:
            return "未找到该将领。"
        if p["res"]["money"] < 200:
            return "提升将领需 200 资金。"
        p["res"]["money"] -= 200
        g["level"] += 1
        g["exp"] = 0
        return f"{g['name']} 晋升至 Lv{g['level']}！全军战力提升。"

    def _policy_list(self):
        lines = ["📜 国策列表（/颁布政策 名称）："]
        for pl in self.store.policies():
            lines.append(f"· {pl['name']}：{pl['effect']}")
        return "\n".join(lines)

    def _my_policy(self, p):
        if not p["policies"]:
            return "你尚未颁布任何国策，用 /政策列表 查看。"
        lines = [f"📜 「{p['org']}」现行国策："]
        for pid in p["policies"]:
            pl = self._p[pid]
            lines.append(f"· {pl['name']}：{pl['effect']}")
        return "\n".join(lines)

    def _enact_policy(self, p, rest, target):
        name = target if target else (rest or "").strip()
        pl = _find(self.store.policies(), name)
        if not pl:
            return "未找到该国策，请用 /政策列表 查看。"
        if pl["id"] in p["policies"]:
            return f"你已颁布 {pl['name']}。"
        p["policies"].append(pl["id"])
        # 即时效果
        if pl["id"] == "welfare":
            p["happy"] += 5
        elif pl["id"] in ("democracy", "religious_free"):
            p["happy"] += 4
            p["stable"] += 4
        elif pl["id"] in ("centralism", "martial", "censorship"):
            p["stable"] += 5
        return f"📜 颁布国策：{pl['name']}。{pl['effect']}"

    def _revoke_policy(self, p, rest):
        pl = _find(self.store.policies(), rest)
        if not pl or pl["id"] not in p["policies"]:
            return "你并未颁布该国策。"
        p["policies"].remove(pl["id"])
        return f"已撤销国策：{pl['name']}。"

    # ---- 经济运营 ----
    def _economy(self, p, op, rest, state):
        if op == "tax":
            gain = p["pop"] * p["tax_rate"] / 100.0 * 0.5
            p["res"]["money"] += gain
            p["happy"] = max(0, p["happy"] - 1)
            return f"💰 征税获得 {gain:.0f} 资金（税率 {p['tax_rate']}%）。"
        if op == "pay":
            cost = p["pop"] * 0.05 + sum(p["units"].values()) * 0.5
            if p["res"]["money"] < cost:
                return "资金不足以发工资，稳定度下降。"
            p["res"]["money"] -= cost
            p["stable"] = min(100, p["stable"] + 3)
            return f"已发放工资，支出 {cost:.0f} 资金，稳定度上升。"
        if op == "settax":
            try:
                v = int(float((rest or "").strip()))
            except Exception:
                return "用法：/调税率 0-100"
            p["tax_rate"] = max(0, min(100, v))
            return f"税率已调整为 {p['tax_rate']}%。"
        if op == "trade":
            gain = 50 + p["buildings"].get("market", 0) * 20
            if "free_trade" in p["policies"]:
                gain *= 1.3
            p["res"]["money"] += gain
            return f"🤝 贸易获得 {gain:.0f} 资金。"
        if op == "sell":
            return self._trade_res(p, rest, sell=True)
        if op == "buy":
            return self._trade_res(p, rest, sell=False)
        if op == "invest":
            if p["res"]["money"] < 200:
                return "投资需 200 资金。"
            p["res"]["money"] -= 200
            p["happy"] += 2
            p["res"]["money"] += 260  # 长期回报一次性模拟
            return "投资基建，获得 260 资金回报。"
        if op == "aid":
            parts = (rest or "").split()
            if len(parts) < 2:
                return "用法：/援助 组织名 资金"
            tgt = self.player_by_org(state, parts[0])
            if not tgt:
                return "未找到该组织。"
            try:
                amt = float(parts[1])
            except Exception:
                return "金额无效。"
            if p["res"]["money"] < amt:
                return "资金不足。"
            p["res"]["money"] -= amt
            tgt["res"]["money"] = tgt["res"].get("money", 0) + amt
            self._set_rel(state, p["qq"], tgt["qq"], 15)
            self.save(tgt)
            return f"已向 {tgt['org']} 援助 {amt:.0f} 资金，关系改善。"
        if op == "loan":
            p["debt"] += 500
            p["res"]["money"] += 500
            return "借入 500 资金（债务 +500，需 /还债）。"
        if op == "repay":
            if p["debt"] <= 0:
                return "你暂无债务。"
            pay = min(p["debt"], p["res"]["money"])
            p["debt"] -= pay
            p["res"]["money"] -= pay
            return f"偿还 {pay:.0f} 债务，剩余 {p['debt']:.0f}。"
        if op == "print":
            p["res"]["money"] += 800
            p["happy"] -= 3
            p["stable"] -= 3
            return "🖨️ 紧急印钞 +800 资金（引发通胀，幸福/稳定下降）。"
        if op == "subsidy":
            if p["res"]["money"] < 100:
                return "补贴需 100 资金。"
            p["res"]["money"] -= 100
            p["happy"] += 2
            return "产业补贴，幸福度上升。"
        if op == "tariff":
            p["happy"] += 1
            return "已调整关税，贸易结构优化。"
        if op == "privatize":
            if p["res"]["money"] < 100:
                return "无国企可私有化。"
            p["res"]["money"] += 300
            return "私有化国企，获得 300 资金。"
        if op == "confiscate":
            p["res"]["money"] += 200
            p["stable"] -= 5
            p["happy"] -= 4
            return "征收私产 +200 资金（稳定/幸福下降）。"
        if op == "donate":
            if p["res"]["money"] < 50:
                return "无资可募。"
            p["res"]["money"] -= 50
            p["happy"] += 3
            return "国民踊跃募捐，幸福度上升。"
        if op == "bond":
            p["debt"] += 1000
            p["res"]["money"] += 1000
            return "发行国债筹资 1000 资金（债务 +1000）。"
        if op == "blackmarket":
            if random.random() < 0.5:
                p["res"]["rare"] += 20
                return "黑市交易成功，获得 20 稀有金属。"
            p["stable"] -= 6
            return "黑市交易被查，稳定度下降。"
        if op == "exchange":
            return f"当前汇率 1:1（模拟），调整汇率功能预留。"
        return "未知经济操作。"

    def _trade_res(self, p, rest, sell):
        parts = (rest or "").split()
        if len(parts) < 2:
            return "用法：/卖资源 资源名 数量 或 /买资源 资源名 数量"
        rname = parts[0]
        rk = None
        for k, v in RES_CN.items():
            if v == rname or k == rname:
                rk = k
        if not rk:
            return "资源名无效（资金/粮食/石油/稀有金属/科技点）。"
        try:
            amt = float(parts[1])
        except Exception:
            return "数量无效。"
        price = {"money": 1, "food": 0.5, "oil": 2, "rare": 5, "tech": 10}[rk]
        if sell:
            if p["res"].get(rk, 0) < amt:
                return "持有不足。"
            p["res"][rk] -= amt
            p["res"]["money"] += amt * price
            return f"卖出 {rk} ×{amt:.0f}，获得 {amt*price:.0f} 资金。"
        else:
            cost = amt * price
            if p["res"]["money"] < cost:
                return "资金不足。"
            p["res"]["money"] -= cost
            p["res"][rk] = p["res"].get(rk, 0) + amt
            return f"买入 {rk} ×{amt:.0f}，花费 {cost:.0f} 资金。"

    # ---- 社会 ----
    def _social(self, p, op):
        if op == "immigrate":
            p["pop"] += 200
            return "吸引移民，人口 +200。"
        if op == "census":
            return f"人口普查完成，当前人口 {p['pop']:.0f}。"
        if op == "settle":
            if p["res"]["money"] < 80:
                return "建设民居需 80 资金。"
            p["res"]["money"] -= 80
            p["pop"] += 100
            p["happy"] += 2
            return "新建民居，人口 +100，幸福 +2。"
        if op == "urban":
            p["stable"] += 2
            p["happy"] += 1
            return "城市建设推进，稳定/幸福小幅上升。"
        if op == "green":
            p["happy"] += 2
            return "环境绿化，幸福 +2。"
        if op == "security":
            p["stable"] += 3
            return "加强治安，稳定 +3。"
        if op == "stabilize":
            p["stable"] = min(100, p["stable"] + 5)
            return "维稳行动，稳定 +5。"
        if op == "education":
            if p["res"]["money"] < 100:
                return "投资教育需 100 资金。"
            p["res"]["money"] -= 100
            p["res"]["tech"] += 15
            return "投资教育，科技点 +15。"
        if op == "health":
            if p["res"]["money"] < 100:
                return "投资医疗需 100 资金。"
            p["res"]["money"] -= 100
            p["happy"] += 4
            p["pop"] += 50
            return "投资医疗，幸福 +4，人口 +50。"
        return "未知社会指令。"

    # ---- 军事行动 ----
    def _mil_power_cmd(self, p, state):
        mp = self.mil_power(p)
        regions = len([r for r in state["regions"] if r["owner"] == p["qq"]])
        return f"⚔️ 「{p['org']}」总战力 {mp:.0f}，控制地区 {regions} 个，将领 {len(p['generals'])} 名。"

    def _military(self, p, op, rest, state, now):
        target = (rest or "").strip()
        if op == "attack":
            return self._do_attack(p, target, state, now, nuke=False)
        if op == "nuke":
            return self._do_attack(p, target, state, now, nuke=True)
        if op == "airstrike":
            return self._do_attack(p, target, state, now, nuke=False, kind="air")
        if op == "bomb":
            return self._do_attack(p, target, state, now, nuke=False, kind="bomb")
        if op == "missile_strike":
            return self._do_attack(p, target, state, now, nuke=False, kind="missile")
        if op in ("defend", "patrol", "reinforce", "retreat", "land", "guerrilla",
                  "blockade", "siege", "airdrop", "shell", "ewar"):
            r = self.region_by_name(state, target) if target else None
            if not r:
                return "用法：/" + op + " 地区名"
            bonus = {"defend": "进入防御态势", "patrol": "巡逻提升警戒",
                     "reinforce": "增援到位", "retreat": "部队撤离", "land": "两栖登陆准备",
                     "guerrilla": "游击袭扰", "blockade": "海上封锁", "siege": "包围完成",
                     "airdrop": "空降夺占", "shell": "炮击压制", "ewar": "电子干扰"}[op]
            return f"📍 对【{r['name']}】{bonus}。（实战效果在 /进攻 时结算）"
        if op == "decap":
            tgt = self.player_by_org(state, target)
            if not tgt:
                return "未找到该组织。"
            if random.random() < 0.4:
                if tgt["generals"]:
                    g = tgt["generals"].pop(0)
                    return f"🗡️ 斩首成功！击杀 {tgt['org']} 将领 {g['name']}。"
                return f"斩首行动失败，{tgt['org']} 首脑无恙。"
            return f"斩首行动失败，被 {tgt['org']} 反间谍识破。"
        return "未知军事指令。"

    def _do_attack(self, p, target, state, now, nuke, kind=None):
        if not target:
            return "用法：/进攻 地区名 或 /进攻 组织名"
        r = self.region_by_name(state, target)
        tgt_player = None
        if not r:
            tgt_player = self.player_by_org(state, target)
            if tgt_player:
                # 攻击对方首都地区
                r = self.region_by_id(state, tgt_player["capital_region"]) if tgt_player.get("capital_region") else None
        if not r:
            return "未找到该目标（地区名或组织名）。"
        if r["owner"] == p["qq"]:
            return "这是你自己的地区，无需进攻。"
        ap = self.mil_power(p)
        if nuke and "nukesilo" not in p["units"]:
            return "核打击需要核导弹（/征核导弹 1），且需研究核武器。"
        # 防守方战力
        owner = self.store.load_player(r["owner"]) if r["owner"] else None
        dp = r["defense"]
        if owner:
            dp += self.mil_power(owner) * 0.30
            # 未宣战则关系受损
            if p["qq"] not in owner.get("wars", []) and tgt_player is None:
                self._set_rel(state, p["qq"], owner["qq"], -30)
        if kind == "air":
            ap *= 0.6
        if kind == "missile":
            ap *= 1.2
        # 结算
        if ap > dp:
            casualty = dp / (ap * 2.0)
            self._apply_casualty(p, casualty)
            prev_owner = r["owner"]
            r["owner"] = p["qq"]
            r["dev"] = max(1, r["dev"])
            p["stats"]["regions_taken"] += 1
            if owner:
                owner["stats"]["regions_lost"] += 1
                self._ensure_war(state, p["qq"], owner["qq"])
                self.save(owner)
                msg_tail = f"，{owner['org']} 失去该地区"
            else:
                msg_tail = "，无主地区已被占领"
            if nuke:
                r["dev"] = 0
                p["units"].pop("nukesilo", None)
                return f"☢️ 核打击命中【{r['name']}】！该地区化为焦土，已被你占领{msg_tail}。"
            return f"✅ 进攻成功！占领【{r['name']}】（{r['continent']}）{msg_tail}。"
        else:
            casualty = 0.30
            self._apply_casualty(p, casualty)
            if owner:
                self._set_rel(state, p["qq"], owner["qq"], -10)
            return (f"❌ 进攻【{r['name']}】失败（我方战力 {ap:.0f} < 守军 {dp:.0f}）。"
                    f"部队遭受损失，建议先 /建造 兵营、/征兵 提升军力。")

    def _apply_casualty(self, p, frac):
        frac = max(0.0, min(0.9, frac))
        for uid in list(p["units"].keys()):
            p["units"][uid] = p["units"][uid] * (1 - frac)
            if p["units"][uid] < 1:
                del p["units"][uid]
        # 人口损失
        p["pop"] *= (1 - frac * 0.1)
        p["stats"]["deaths"] += int(p["pop"] * frac * 0.1)

    def _war_report(self, p):
        s = p["stats"]
        return (f"📜 「{p['org']}」战报：\n胜 {s['wars_won']}｜负 {s['wars_lost']}｜"
                f"击杀 {s['kills']}｜阵亡 {s['deaths']}｜夺取地区 {s['regions_taken']}｜"
                f"丢失地区 {s['regions_lost']}")

    # ---- 外交 ----
    def _pair(self, a, b):
        return "|".join(sorted([str(a), str(b)]))

    def _get_rel(self, state, a, b):
        return state["relations"].get(self._pair(a, b), 0)

    def _set_rel(self, state, a, b, delta):
        k = self._pair(a, b)
        v = state["relations"].get(k, 0) + delta
        state["relations"][k] = max(-100, min(100, v))

    def _ensure_war(self, state, a, b):
        k = self._pair(a, b)
        if k not in state["wars"]:
            state["wars"].append(k)
        # 从同盟移除
        if k in state["allies"]:
            state["allies"].remove(k)
        pa = self.store.load_player(a)
        pb = self.store.load_player(b)
        if pa:
            if b not in pa["wars"]:
                pa["wars"].append(b)
            if b in pa["allies"]:
                pa["allies"].remove(b)
            self.save(pa)
        if pb:
            if a not in pb["wars"]:
                pb["wars"].append(a)
            if a in pb["allies"]:
                pb["allies"].remove(a)
            self.save(pb)

    def _end_war(self, state, a, b):
        k = self._pair(a, b)
        if k in state["wars"]:
            state["wars"].remove(k)
        pa = self.store.load_player(a)
        pb = self.store.load_player(b)
        for x in (pa, pb):
            if x and b in x["wars"]:
                x["wars"].remove(b)
            if x and a in x["wars"]:
                x["wars"].remove(a)
            if x:
                self.save(x)

    def _diplo(self, p, op, rest, state):
        org = (rest or "").strip()
        tgt = self.player_by_org(state, org) if org else None
        if op in ("establish", "ally", "break", "war", "cease", "peace", "napt",
                  "vassal", "sanction", "condemn", "tradepact", "embassy", "recall",
                  "befriend", "hostile", "condo", "mediate", "decap"):
            if not tgt:
                return "用法：该指令需接组织名，例如 /宣战 曙光帝国"
            if tgt["qq"] == p["qq"]:
                return "不能对自己使用外交指令。"
        rel = self._get_rel(state, p["qq"], tgt["qq"])
        if op == "establish":
            self._set_rel(state, p["qq"], tgt["qq"], 30 - rel)
            return f"已与 {tgt['org']} 建立外交关系。"
        if op == "ally":
            if rel >= 40:
                k = self._pair(p["qq"], tgt["qq"])
                if k not in state["allies"]:
                    state["allies"].append(k)
                self._set_rel(state, p["qq"], tgt["qq"], 20)
                return f"🤝 与 {tgt['org']} 缔结同盟！"
            return f"{tgt['org']} 拒绝了同盟提议（关系 {rel} 不足 40）。"
        if op == "break":
            self._set_rel(state, p["qq"], tgt["qq"], -50 - rel)
            self._end_war(state, p["qq"], tgt["qq"])
            return f"已与 {tgt['org']} 断交。"
        if op == "war":
            self._ensure_war(state, p["qq"], tgt["qq"])
            self._set_rel(state, p["qq"], tgt["qq"], -100)
            p["rep"] -= 5
            return f"⚔️ 你已向 {tgt['org']} 宣战！可用 /进攻 组织名 开战。"
        if op == "cease":
            self._end_war(state, p["qq"], tgt["qq"])
            self._set_rel(state, p["qq"], tgt["qq"], 10)
            return f"已与 {tgt['org']} 停战。"
        if op == "peace":
            self._end_war(state, p["qq"], tgt["qq"])
            self._set_rel(state, p["qq"], tgt["qq"], 30)
            p["rep"] += 5
            return f"✌️ 与 {tgt['org']} 达成和平。"
        if op == "napt":
            self._set_rel(state, p["qq"], tgt["qq"], 20)
            return f"已与 {tgt['org']} 签订互不侵犯条约。"
        if op == "vassal":
            self._set_rel(state, p["qq"], tgt["qq"], -40)
            tgt_rel = self._get_rel(state, p["qq"], tgt["qq"])
            if tgt_rel < -20:
                return f"{tgt['org']} 反抗，未能使其成为附庸。"
            return f"{tgt['org']} 成为你的附庸。"
        if op == "sanction":
            self._set_rel(state, p["qq"], tgt["qq"], -20)
            tgt["res"]["money"] = max(0, tgt["res"]["money"] - 100)
            self.save(tgt)
            return f"已对 {tgt['org']} 实施经济制裁（其资金 -100）。"
        if op == "condemn":
            self._set_rel(state, p["qq"], tgt["qq"], -10)
            p["rep"] += 2
            return f"你公开谴责了 {tgt['org']}，国际声望 +2。"
        if op == "tradepact":
            self._set_rel(state, p["qq"], tgt["qq"], 15)
            return f"已与 {tgt['org']} 签订贸易协定，贸易收益提升。"
        if op == "embassy":
            self._set_rel(state, p["qq"], tgt["qq"], 10)
            return f"已在 {tgt['org']} 设立大使馆。"
        if op == "recall":
            self._set_rel(state, p["qq"], tgt["qq"], -5)
            return f"已撤回驻 {tgt['org']} 大使。"
        if op == "befriend":
            self._set_rel(state, p["qq"], tgt["qq"], 15)
            return f"你对 {tgt['org']} 示好，关系改善。"
        if op == "hostile":
            self._set_rel(state, p["qq"], tgt["qq"], -25)
            return f"你公开敌视 {tgt['org']}，关系恶化。"
        if op == "neutral":
            return "你发布中立声明，不参与当前冲突。"
        if op == "condo":
            self._set_rel(state, p["qq"], tgt["qq"], 10)
            return f"你提议与 {tgt['org']} 共管争议地区。"
        if op == "summit":
            return "🕊️ 国际峰会召开，各国关系趋于缓和（全体关系 +5）。"
        if op == "un":
            return "🏛️ 联合国投票进行中，你的立场已记录。"
        if op == "mediate":
            self._set_rel(state, p["qq"], tgt["qq"], 10)
            return f"你调停了与 {tgt['org']} 的冲突。"
        return "未知外交指令。"

    # ---- 地图 ----
    def _map(self, p, op, rest, state):
        if op == "world":
            lines = [f"🗺️ {self.store.world_template()['name']}（{len(state['regions'])} 地区）所有权："]
            by_cont = {}
            for r in state["regions"]:
                by_cont.setdefault(r["continent"], []).append(r)
            for cont, regs in by_cont.items():
                owned = sum(1 for r in regs if r["owner"])
                lines.append(f"【{cont}】{len(regs)} 地区，已占领 {owned}")
            return "\n".join(lines)
        if op == "region":
            r = self.region_by_name(state, rest)
            if not r:
                return "未找到该地区，用法：/区域地图 地区名"
            owner = "无主"
            if r["owner"]:
                op2 = self.store.load_player(r["owner"])
                owner = op2["org"] if op2 else r["owner"]
            res_cn = {"food": "粮食", "oil": "石油", "rare": "稀有金属", "metal": "金属", "none": "无"}
            return (f"📍 【{r['name']}】（{r['continent']}）\n地形：{r['terrain']}｜"
                    f"资源：{res_cn.get(r['resource'], r['resource'])}（富集 {r['rich']}）｜"
                    f"防御 {r['defense']:.0f}｜归属：{owner}")
        if op == "territory":
            mine = [r for r in state["regions"] if r["owner"] == p["qq"]]
            if not mine:
                return "你还没有任何领地，先 /进攻 夺取地区吧。"
            return "🏰 你的领地：\n" + "\n".join(
                f"· 【{r['name']}】（{r['continent']} {r['terrain']}）" +
                (" ⭐首都" if r["capital_of"] == p["qq"] else "") for r in mine)
        if op == "neighbor":
            mine = [r for r in state["regions"] if r["owner"] == p["qq"]]
            conts = {r["continent"] for r in mine}
            neigh = [r for r in state["regions"]
                     if r["continent"] in conts and r["owner"] != p["qq"]]
            if not neigh:
                return "你周边暂无其他地区。"
            return "🌐 邻近地区：\n" + "\n".join(
                f"· 【{r['name']}】（{r['continent']}）" for r in neigh[:15])
        if op == "recon":
            r = self.region_by_name(state, rest)
            if not r:
                return "未找到该地区。"
            if not r["owner"]:
                return f"【{r['name']}】为无主地区，可直接进攻占领。"
            o = self.store.load_player(r["owner"])
            if o:
                return (f"🔍 侦察【{r['name']}】（归属 {o['org']}）：\n"
                        f"战力约 {self.mil_power(o):.0f}｜建筑 {sum(o['buildings'].values())} 座｜"
                        f"地区 {len([x for x in state['regions'] if x['owner']==o['qq']])} 个")
            return f"【{r['name']}】归属未知。"
        if op == "sat":
            regions = len(state["regions"])
            owned = len([r for r in state["regions"] if r["owner"]])
            players = len(self.store.all_players())
            return f"🛰️ 卫星扫描：全球 {regions} 地区，已被占领 {owned} 个，活跃国家 {players} 个。"
        if op == "radar":
            return "📡 雷达扫描完成，周边无异常威胁。" if random.random() > 0.2 else "📡 雷达发现附近有军事调动。"
        if op == "resdist":
            cnt = {}
            for r in state["regions"]:
                cnt[r["resource"]] = cnt.get(r["resource"], 0) + 1
            return "⛏️ 资源分布：" + "，".join(
                f"{ {'food':'粮食','oil':'石油','rare':'稀有金属','metal':'金属','none':'荒芜'}.get(k,k) }×{v}"
                for k, v in cnt.items())
        if op == "sphere":
            # 各势力范围（按拥有地区数）
            cnt = {}
            for r in state["regions"]:
                if r["owner"]:
                    cnt[r["owner"]] = cnt.get(r["owner"], 0) + 1
            if not cnt:
                return "当前尚无任何势力占领地区。"
            top = sorted(cnt.items(), key=lambda x: -x[1])[:10]
            lines = ["🌍 势力范围（按领地数）："]
            for qq, n in top:
                o = self.store.load_player(qq)
                lines.append(f"· {o['org'] if o else qq}：{n} 地区")
            return "\n".join(lines)
        return "未知地图指令。"

    # ---- 谍报 ----
    def _spy(self, p, op, rest, state):
        org = (rest or "").strip()
        tgt = self.player_by_org(state, org) if org else None
        if op == "send":
            if not tgt:
                return "用法：/间谍 组织名"
            p.setdefault("spies", {})[tgt["qq"]] = p["spies"].get(tgt["qq"], 0) + 1
            return f"已向 {tgt['org']} 派遣间谍。"
        if op == "counter":
            return "反间谍网络已强化，被窃取概率下降。"
        if op in ("steal", "sabotage", "assassin", "subvert", "tap", "double"):
            if not tgt:
                return "用法：/" + op + " 组织名"
            names = {"steal": "窃取情报", "sabotage": "破坏设施", "assassin": "暗杀行动",
                     "subvert": "策反部队", "tap": "监听通讯", "double": "安插双重间谍"}
            if random.random() < 0.5:
                if op == "steal":
                    p["res"]["tech"] += 10
                    return f"✅ 窃取 {tgt['org']} 情报成功，科技点 +10。"
                if op == "sabotage":
                    tgt["res"]["money"] = max(0, tgt["res"]["money"] - 150)
                    self.save(tgt)
                    return f"✅ 破坏 {tgt['org']} 设施，其资金 -150。"
                if op == "assassin":
                    if tgt["generals"]:
                        g = tgt["generals"].pop(0)
                        self.save(tgt)
                        return f"✅ 暗杀成功，击杀 {tgt['org']} 将领 {g['name']}。"
                    return f"暗杀失败，{tgt['org']} 首脑无恙。"
                if op == "subvert":
                    p["res"]["money"] += 50
                    return f"✅ 策反 {tgt['org']} 部队，获得 50 资金。"
                if op == "tap":
                    return f"✅ 监听 {tgt['org']} 通讯，获取其部分动向。"
                if op == "double":
                    return f"✅ 在 {tgt['org']} 安插双重间谍，情报优势提升。"
            return f"❌ {names[op]}失败，被 {tgt['org']} 识破。"
        return "未知谍报指令。"

    # ---- 系统 / 排行 ----
    def _system(self, p, op, state):
        if op == "help":
            return self._help_text()
        if op == "rules":
            return self._rules_text()
        if op == "charts":
            return ("📊 两张大型指令图已随插件提供：\n"
                    "· 内政经济指令图（commands_chart1.html）\n"
                    "· 军事外交指令图（commands_chart2.html）\n"
                    "查看方式：在插件目录打开，或访问仓库 README 中的图片链接。")
        if op == "status":
            players = self.store.all_players()
            regs = len(players)
            active = len([x for x in players if time.time() - x.get("last_tick", 0) < 3600])
            regions = len(state["regions"])
            owned = len([r for r in state["regions"] if r["owner"]])
            return (f"🖥️ 服务器状态：在线国家 {regs}（近1小时活跃 {active}），"
                    f"世界 {regions} 地区已占领 {owned}，战争 {len(state['wars'])} 场。")
        if op == "online":
            players = self.store.all_players()
            if not players:
                return "暂无玩家，发送 /注册 成为第一个国家！"
            lines = ["👥 已注册国家："]
            for x in players[:30]:
                lines.append(f"· {x['org'] or '(未命名)'}（QQ {x['qq']}）")
            return "\n".join(lines)
        if op == "power":
            return self._rank(state, "power")
        if op == "win":
            return self._rank(state, "win")
        if op == "kill":
            return self._rank(state, "kill")
        if op == "delete":
            if p:
                import os
                pp = self.store.player_path(p["qq"])
                if os.path.exists(pp):
                    os.remove(pp)
                # 清理 org_index
                for k, v in list(state["org_index"].items()):
                    if v == p["qq"]:
                        del state["org_index"][k]
                self.save(state=state)
                return "🗑️ 你的国家数据已注销。"
            return "你还没有国家。"
        if op == "reset":
            if not p:
                return "你还没有国家。"
            qq = p["qq"]
            start = self._parse_start()
            home = p.get("home_region")
            np_ = self.store.new_player(qq, p.get("org", ""), start, home)
            self.save(np_, state)
            return "🔄 已重置你的国家数据，重新开始。"
        return "未知系统指令。"

    def _rank(self, state, kind):
        players = self.store.all_players()
        if not players:
            return "暂无排名数据。"
        for x in players:
            self.recalc(x, state, int(time.time()))
        if kind == "power":
            players.sort(key=lambda x: -self.power_score(x, state))
            title = "国力排行"
        elif kind == "win":
            players.sort(key=lambda x: -x["stats"]["wars_won"])
            title = "战绩排行（胜场）"
        else:
            players.sort(key=lambda x: -x["stats"]["kills"])
            title = "杀敌排行"
        lines = [f"🏆 {title}："]
        for i, x in enumerate(players[:15], 1):
            if kind == "power":
                lines.append(f"{i}. {x['org'] or x['qq']} — {self.power_score(x, state):.0f}")
            elif kind == "win":
                lines.append(f"{i}. {x['org'] or x['qq']} — 胜 {x['stats']['wars_won']}")
            else:
                lines.append(f"{i}. {x['org'] or x['qq']} — 击杀 {x['stats']['kills']}")
        return "\n".join(lines)

    def _help_text(self):
        return ("📘 国家战争 · 入门：\n"
                "1) /注册 → 用 QQ 号快速注册\n"
                "2) /初始组织名 你的国名 → 建立你的国家（不设名不能玩）\n"
                "3) /建造 农场 → /研究 农业 → /征兵 步兵 10 → 发展国力\n"
                "4) /世界地图 查看局势，/进攻 地区名 征服世界\n"
                "5) /帮助 入门 · /指令图 两张大型指令图 · /规则 完整规则\n"
                "提示：资源随时间自动产出，建筑/科技/兵种有前置与消耗。")

    def _rules_text(self):
        return ("📜 游戏规则：\n"
                "· 账号=QQ号，数据按 QQ 隔离保存，跨群互通。\n"
                "· 必须 /注册 并 /初始组织名 才能游玩。\n"
                "· 资源（资金/粮食/石油/稀有金属/科技点）随时间自动产出，受幸福/稳定/政策影响。\n"
                "· 建筑提供产出与防御；科技解锁兵种与高级建筑；兵种用于进攻/防守。\n"
                "· 进攻地区可占领，守军战力=地区防御+原主战力30%。\n"
                "· 外交：建交/结盟/宣战/和谈等改变关系与战争状态。\n"
                "· 谍报可窃取科技、破坏、暗杀；事件随机影响局势。\n"
                "· 排行按国力/战绩/杀敌，征服世界即为胜利。")
