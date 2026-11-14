"""持久化层：按 QQ 号隔离的玩家存档 + 全局游戏状态 + 静态数据加载。

设计要点（满足用户需求）：
- 玩家数据「按 QQ 号隔断」：每个玩家一个独立文件 players/<qq>.json
- 游玩数据保存在玩家注册账号（QQ 号）对应的存储位置
- 全局世界状态（地区归属、战争、外交、事件、tick）独立存储
- 静态游戏数据（地图/建筑/科技/兵种/政策/指令）从 data/*.json 读取

【v1.2.0 存档永久化加固】
- 所有写入采用「临时文件 + os.replace」原子写，杜绝写一半断电/崩溃导致存档损坏
- 每个玩家/全局状态保留一份 .bak 上一版；主文件损坏时自动回退 .bak
- 彻底损坏的 JSON 不静默丢弃（那等于「初始化掉数据」），而是隔离到 _corrupt/ 供人工恢复
- 玩家新增 last_active 字段（最后游玩时间），供 30 天未使用自动清档判定
- migrate_legacy_dir：把插件目录内旧 data_runtime 存档迁移到持久目录（升级不丢号）
- migrate_last_active：给升级前的老档案补齐 last_active（按 last_tick/registered_at/文件mtime 兜底）
"""
import json
import os
import time
import shutil
import tempfile
import threading


def _atomic_write_text(path: str, text: str, keep_bak: bool = True):
    """原子写入：先写同目录临时文件并 fsync，再 os.replace 覆盖。

    keep_bak=True 时，覆盖前把上一版复制为 path+'.bak'，作为崩溃/损坏时的回滚点。
    同目录临时文件保证 os.replace 处在同一文件系统内（原子）。
    """
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    if keep_bak and os.path.exists(path):
        try:
            shutil.copy2(path, path + ".bak")
        except Exception:
            pass
    fd, tmp = tempfile.mkstemp(prefix="._nw_", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise


class Store:
    def __init__(self, base_dir: str):
        self.base = base_dir
        self.players_dir = os.path.join(base_dir, "players")
        self.state_path = os.path.join(base_dir, "state.json")
        self.corrupt_dir = os.path.join(base_dir, "_corrupt")
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

    # ---------------- 通用：损坏隔离 / 读取 ----------------
    def _quarantine(self, path: str, raw_err: Exception | None = None):
        """把彻底损坏的文件移到 _corrupt/，绝不删除（保住数据以便人工恢复）。"""
        try:
            os.makedirs(self.corrupt_dir, exist_ok=True)
            base = os.path.basename(path)
            dst = os.path.join(self.corrupt_dir, f"{int(time.time())}_{base}")
            shutil.copy2(path, dst)
            return dst
        except Exception:
            return None

    def _load_json(self, path: str, with_bak: bool = True):
        """读取 JSON；主文件损坏时先回退 .bak，仍失败则隔离并返回 None。"""
        if not os.path.exists(path):
            return None
        candidates = [path]
        if with_bak and os.path.exists(path + ".bak"):
            candidates.append(path + ".bak")
        for i, c in enumerate(candidates):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if i > 0:  # 从 .bak 恢复成功：立即修复主文件
                    try:
                        _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2),
                                           keep_bak=False)
                    except Exception:
                        pass
                return data
            except Exception:
                continue
        # 主文件与 .bak 均不可读：隔离主文件（不删除），返回 None 交由上层重建
        self._quarantine(path)
        return None

    # ---------------- 全局状态 ----------------
    def load_state(self) -> dict:
        st = self._load_json(self.state_path)
        if not isinstance(st, dict):
            st = self._default_state()
        # 兼容补全（升级新增字段时自动补齐，不覆盖已有值）
        for k, v in self._default_state().items():
            st.setdefault(k, v)
        return st

    def save_state(self, st: dict):
        with self._lock:
            _atomic_write_text(self.state_path, json.dumps(st, ensure_ascii=False, indent=2))

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
            "last_purge": 0,        # 上次自动清档时间
            "version": 2,
        }

    # ---------------- 玩家 ----------------
    def player_path(self, qq: str) -> str:
        return os.path.join(self.players_dir, f"{qq}.json")

    def player_exists(self, qq: str) -> bool:
        return os.path.exists(self.player_path(qq))

    def load_player(self, qq: str) -> dict | None:
        p = self._load_json(self.player_path(qq))
        if isinstance(p, dict):
            # 老档案字段兼容（不覆盖已有值）。
            # 关键：last_active 必须用「已有时间戳」兜底，绝不能用动态 now，
            # 否则每次读取都等于给老玩家续期，30 天自动清档将永不触发。
            p.setdefault("qq", str(qq))
            base_ts = p.get("last_tick") or p.get("registered_at") or 0
            p.setdefault("last_tick", int(base_ts))
            p.setdefault("registered_at", int(base_ts))
            p.setdefault("last_active", int(base_ts))
            defaults = {
                "org": "", "home_region": 0, "capital_region": None,
                "pop": 1000, "happy": 60, "stable": 60, "rep": 0,
                "tax_rate": 20, "debt": 0, "buildings": {}, "techs": {},
                "research": {"tech": None, "progress": 0}, "units": {},
                "generals": [], "policies": [], "relations": {}, "wars": [],
                "allies": [], "build_queue": [], "production": [], "log": [],
                "stats": {"wars_won": 0, "wars_lost": 0, "kills": 0,
                          "deaths": 0, "regions_taken": 0, "regions_lost": 0},
                "res": {"money": 1000, "food": 1000, "oil": 200, "rare": 50, "tech": 50},
            }
            for k, v in defaults.items():
                p.setdefault(k, v)
            return p
        return None

    def save_player(self, p: dict):
        with self._lock:
            path = self.player_path(p["qq"])
            _atomic_write_text(path, json.dumps(p, ensure_ascii=False, indent=2))
            # 同步清理同名 .bak 之外的临时残留
        return True

    def delete_player(self, qq: str) -> bool:
        """删除玩家存档（自动清档/主动注销用），连同 .bak 一起清。"""
        with self._lock:
            path = self.player_path(qq)
            ok = False
            for f in (path, path + ".bak"):
                try:
                    if os.path.exists(f):
                        os.remove(f)
                        ok = True
                except Exception:
                    pass
            return ok

    def all_players(self) -> list:
        out = []
        for fn in os.listdir(self.players_dir):
            if not fn.endswith(".json"):
                continue
            qq = fn[:-5]
            p = self.load_player(qq)
            if isinstance(p, dict):
                out.append(p)
        return out

    def touch_active(self, qq: str, now: int | None = None):
        """玩家主动发指令时刷新最后活跃时间（30 天保活判定依据）。"""
        now = now or int(time.time())
        p = self.load_player(qq)
        if isinstance(p, dict):
            p["last_active"] = now
            self.save_player(p)

    # ---------------- 升级迁移 ----------------
    def migrate_last_active(self, now: int | None = None) -> int:
        """给升级前的老档案补齐 last_active 并持久化到磁盘。

        注意：load_player() 会在内存里兜底 last_active，因此这里必须读「磁盘原始
        JSON」判断是否真的缺字段，否则补写永远不触发。
        兜底优先级：last_tick > registered_at > 文件 mtime > 当前时间。
        绝不把老玩家误判为「刚活跃」，也不误伤到期的老号。
        返回实际补写的档案数。
        """
        now = now or int(time.time())
        fixed = 0
        with self._lock:
            for fn in os.listdir(self.players_dir):
                if not fn.endswith(".json"):
                    continue
                path = os.path.join(self.players_dir, fn)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        p = json.load(f)
                except Exception:
                    continue
                if not isinstance(p, dict) or p.get("last_active"):
                    continue
                fallback = p.get("last_tick") or p.get("registered_at")
                if not fallback:
                    try:
                        fallback = int(os.path.getmtime(path))
                    except Exception:
                        fallback = now
                try:
                    p["last_active"] = int(fallback)
                except Exception:
                    p["last_active"] = now
                _atomic_write_text(path, json.dumps(p, ensure_ascii=False, indent=2),
                                   keep_bak=False)
                fixed += 1
        return fixed

    def migrate_legacy_dir(self, legacy_dir: str) -> int:
        """把旧版「插件目录内 data_runtime」的存档迁移到当前持久目录。

        只在目标文件不存在时复制，绝不覆盖新目录已有的数据。
        返回迁移的文件数。
        """
        if not legacy_dir or not os.path.isdir(legacy_dir):
            return 0
        if os.path.abspath(legacy_dir) == os.path.abspath(self.base):
            return 0
        moved = 0
        legacy_players = os.path.join(legacy_dir, "players")
        if os.path.isdir(legacy_players):
            for fn in os.listdir(legacy_players):
                if not fn.endswith(".json"):
                    continue
                src = os.path.join(legacy_players, fn)
                dst = os.path.join(self.players_dir, fn)
                if not os.path.exists(dst):
                    try:
                        shutil.copy2(src, dst)
                        moved += 1
                    except Exception:
                        pass
        src_state = os.path.join(legacy_dir, "state.json")
        if os.path.exists(src_state) and not os.path.exists(self.state_path):
            try:
                shutil.copy2(src_state, self.state_path)
                moved += 1
            except Exception:
                pass
        return moved

    # ---------------- 原子操作 ----------------
    def new_player(self, qq: str, org: str, start_res: dict, home_region: int) -> dict:
        now = int(time.time())
        p = {
            "qq": str(qq),
            "org": org,                      # 初始为空，待 /初始组织名 设置
            "registered_at": now,
            "last_active": now,              # 最后游玩时间（30 天未使用自动清档）
            "home_region": home_region,
            "capital_region": None,
            "res": dict(start_res) if start_res else {"money": 1000, "food": 1000,
                                                       "oil": 200, "rare": 50, "tech": 50},
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
