"""国家战争插件主类（AstrBot v4 Star 插件）。

- 按 QQ 号快速注册（账号=QQ号），数据按 QQ 隔离保存、跨群互通
- 200+ 指令，分两张大型指令图（内政经济 / 军事外交）
- 完整虚拟世界地图 + 各大区地图
- 所有指令在运行时按 commands.json 目录动态注册
"""
import asyncio
import os

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import message_components as Comp

from .core.store import Store
from .core.engine import Engine
from .core import engine as engine_mod

PLUGIN_NAME = "astrbot_plugin_nationwar"

# 需要 @ 提及用户的指令（注册相关回复按需求格式）
MENTION_KEYS = {"register", "set_org", "rename_org"}


def _rest(event: AstrMessageEvent, names: list) -> str:
    """从原始消息中剥离指令名，取剩余参数文本（支持多词参数/别名）。"""
    s = (event.get_message_str() or "").strip()
    if s.startswith("/"):
        s = s[1:].strip()
    for n in names:
        if s == n:
            return ""
        if s.startswith(n + " "):
            return s[len(n) + 1:].strip()
    # 兜底：去掉第一个词
    parts = s.split(" ", 1)
    return parts[1].strip() if len(parts) > 1 else ""


@register(
    PLUGIN_NAME,
    "FrostsAfterglow",
    "大型文字模拟国家战争：虚拟世界地图 + 200+ 指令（内政经济/军事外交两张指令图），按 QQ 号快速注册与隔离存档。",
    "1.0.0",
    "https://github.com/FrostsAfterglow/astrbot_plugin_nationwar",
)
class NationWarPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.context = context
        self.config = dict(config) if config is not None else {}

        # 数据目录：优先用 AstrBot 持久化目录，回退到本地
        base = self._resolve_data_dir()
        self.store = Store(base)

        self.engine = Engine(self.store, self.config, logger=self.logger)
        self.logger.info("国家战争插件已加载，数据目录：%s", base)

        # 后台自动结算
        self._bg = None
        if self.config.get("tick_enabled", True):
            interval = max(5, int(self.config.get("tick_interval_min", 30) or 30))
            self._bg = asyncio.ensure_future(self._auto_tick(interval))

    def _resolve_data_dir(self) -> str:
        try:
            from astrbot.api.star import StarTools
            d = str(StarTools.get_data_dir(self))
            if d:
                return d
        except Exception:
            pass
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_runtime")

    async def _auto_tick(self, interval: int):
        try:
            while True:
                await asyncio.sleep(interval * 60)
                self._tick_all()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error("自动结算异常：%s", e)

    def _tick_all(self):
        try:
            state = self.store.load_state()
            self.engine.ensure_world(state)
            now = int(__import__("time").time())
            for p in self.store.all_players():
                self.engine.recalc(p, state, now)
                self.store.save_player(p)
            self.store.save_state(state)
        except Exception as e:
            self.logger.error("tick 错误：%s", e)

    async def _run_cmd(self, event: AstrMessageEvent, key: str, names: list):
        qq = str(event.get_sender_id())
        rest = _rest(event, names)
        state = self.store.load_state()
        self.engine.ensure_world(state)
        try:
            text = self.engine.dispatch(qq, key, rest, state)
        except Exception as e:
            self.logger.error("dispatch 异常 %s: %s", key, e)
            text = f"⚠️ 指令执行出错：{e}"
        if key in MENTION_KEYS:
            try:
                sid = event.get_sender_id()
                yield event.chain_result([Comp.At(qq=sid), Comp.Plain(" " + text)])
            except Exception:
                yield event.plain_result(text)
        else:
            yield event.plain_result(text)

    async def terminate(self):
        if self._bg is not None:
            self._bg.cancel()
        self.logger.info("国家战争插件已卸载")


# ---------------------------------------------------------------------------
# 动态注册全部指令（来自 commands.json）
# ---------------------------------------------------------------------------
def _make_handler(cmd):
    """工厂函数：为每个指令生成独立闭包，避免 late-binding 共享变量的问题。

    关键：必须先把函数 __name__ 设为唯一，再套 @filter.command —— 因为框架用
    module + 函数名 作为 handler 全局唯一标识，同名函数会被合并成同一个 handler。
    """
    name = cmd["name"]
    alias = set(cmd.get("alias", [])) or None
    key = cmd["key"]
    names = [name] + list(cmd.get("alias", []))

    async def handler(self, event: AstrMessageEvent, args: str = ""):
        async for r in self._run_cmd(event, key, names):
            yield r

    # 先改名（唯一），再装饰，否则 250 个指令会塌缩成 1 个 handler
    handler.__name__ = "cmd_" + key
    handler.__qualname__ = "NationWarPlugin.cmd_" + key
    handler.__doc__ = cmd.get("desc", "")
    return filter.command(name, alias)(handler)


def _build_command_methods():
    # 仅用 Store 读取静态 commands.json（静态目录与 base 无关）
    cmds = engine_mod.Store(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_runtime")
    ).commands()
    return [_make_handler(c) for c in cmds]


# 把动态生成的指令方法挂到插件类上（在模块导入时执行，确保被框架扫描到）
for _h in _build_command_methods():
    setattr(NationWarPlugin, _h.__name__, _h)
