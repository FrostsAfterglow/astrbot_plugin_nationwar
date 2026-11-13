"""持久化层：按 QQ 号隔离的玩家存档 + 全局游戏状态 + 静态数据加载。

设计要点（满足用户需求）：
- 玩家数据「按 QQ 号隔断」：每个玩家一个独立文件 data/players/<qq>.json
- 游玩数据保存在玩家注册账号（QQ 号）对应的存储位置
- 全局世界状态（地区归属、战争、外交、事件、tick）独立存储
- 静态游戏数据（地图/建筑/科技/兵种/政策/指令）从 data/*.json 读取
"""
import json
import os
import time
import threading


class Store:
    def __init__(self, base_dir: str):
        self.base = base_dir
        self.players_dir = os.path.join(base_dir, "players")
        self.state_path = os.path.join(base_dir, "state.json")
        self.static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
        os.makedirs(self.players_dir, exist_ok=True)
        self._lock = threading.RLock()
        self._static_cache = {}

    # ---------------- 静态数据 ----------------
    def static(self, name: str):
        if name not in self._static_cache:
            path = os.path.join(self.static_dir, name + ".json")
            with open(path, "r", encoding="utf-8") as f:
                self._static_cache[name] = json.load(f)
        return self._static_cache[name]

    def buildings(self):
        return self.static("buildings")

    def techs(self):
        return self.static("techs")

    def units(self):
        return self.static("units")

    def policies(self):
        return self.static("policies")

    def commands(self):
        return self.static("commands")

    def world_template(self):
        return self.static("world")

    # ---------------- 全局状态 ----------------
    def load_state(self) -> dict:
        if not os.path.exists(self.state_path):
            return self._default_state()
        with open(self.state_path, "r", encoding="utf-8") as f:
            try:
                st = json.load(f)
            except Exception:
                st = self._default_state()
        # 兼容补全
        for k, v in self._default_state().items():
            st.setdefault(k, v)
        return st

    def save_state(self, st: dict):
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _default_state() -> dict:
        return {
            "regions": [],          # 运行期地区状态（含 owner/capital_of/dev）
            "relations": {},        # "qqA|qqB": value(-100..100)，对称
            "wars": [],             # ["qqA|qqB", ...] 处于交战
            "allies": [],           # ["qqA|qqB", ...] 同盟
            "events": [],           # 事件日志
            "org_index": {},        # org_name(小写) -> qq
            "tick": int(time.time()),
            "version": 1,
        }

    # ---------------- 玩家 ----------------
    def player_path(self, qq: str) -> str:
        return os.path.join(self.players_dir, f"{qq}.json")

    def player_exists(self, qq: str) -> bool:
        return os.path.exists(self.player_path(qq))

    def load_player(self, qq: str) -> dict | None:
        p = self.player_path(qq)
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return None

    def save_player(self, p: dict):
        with self._lock:
            with open(self.player_path(p["qq"]), "w", encoding="utf-8") as f:
                json.dump(p, f, ensure_ascii=False, indent=2)

    def all_players(self) -> list:
        out = []
        for fn in os.listdir(self.players_dir):
            if fn.endswith(".json"):
                try:
                    with open(os.path.join(self.players_dir, fn), "r", encoding="utf-8") as f:
                        out.append(json.load(f))
                except Exception:
                    continue
        return out

    # ---------------- 原子操作 ----------------
    def new_player(self, qq: str, org: str, start_res: dict, home_region: int) -> dict:
        now = int(time.time())
        p = {
            "qq": str(qq),
            "org": org,                      # 初始为空，待 /初始组织名 设置
            "registered_at": now,
            "home_region": home_region,
            "capital_region": None,
            "res": dict(start_res),
            "pop": 1000,
            "happy": 60,
            "stable": 60,
            "rep": 0,
            "tax_rate": 20,
            "debt": 0,
            "buildings": {},                  # building_id -> level
            "techs": {},                      # tech_id -> level
            "research": {"tech": None, "progress": 0},
            "units": {},                      # unit_id -> count
            "generals": [],
            "policies": [],
            "relations": {},                  # 冗余缓存（以全局为准）
            "wars": [],
            "allies": [],
            "stats": {"wars_won": 0, "wars_lost": 0, "kills": 0,
                      "deaths": 0, "regions_taken": 0, "regions_lost": 0},
            "build_queue": [],                # {"building":, "to_level":, "ends_at":}
            "production": [],                 # 预留
            "log": [],
            "last_tick": now,
        }
        return p
