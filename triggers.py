r"""
           _
 ___  __ _| |_ __ ___   ___ _ __ _ __
/ __|/ _` | | '_ ` _ \ / _ \ '__| '__|
\__ \ (_| | | | | | | |  __/ |  | |
|___/\__, |_|_| |_| |_|\___|_|  |_|
        |_|

🔒 Licensed under the GNU GPLv3
🌐 https://www.gnu.org/licenses/gpl-3.0.htmla
"""

# meta banner: https://github.com/sqlmerr/hikka_mods/blob/main/assets/banners/triggers.png?raw=true
# meta icon: https://github.com/sqlmerr/hikka_mods/blob/main/assets/icons/triggers.png?raw=true
# meta developer: @sqlmerr_m
# upstream: https://github.com/sqlmerr/hikka_mods/blob/main/triggers.py
# compatibility fixes: @LebedKA_SYS (troy9221/hikka_modules)

import ast
import logging
import asyncio
import json
import math
from copy import deepcopy
from contextlib import suppress
from typing import Dict, List, TypedDict, Any, Callable, Optional, Tuple, Union
from meval import meval

from .. import loader, utils
from hikkatl.tl.patched import Message

from collections import OrderedDict
from time import monotonic

from ..inline.types import InlineCall
from ..types import JSONSerializable
try:
    from ..types import HikkaReplyMarkup
except ImportError:
    from ..types import HerokuReplyMarkup as HikkaReplyMarkup


logger = logging.getLogger(__name__)


class _TriggerCooldown:
    """Bounded, monotonic per-trigger cooldown without third-party packages."""

    def __init__(self, maxsize=10_000, ttl=1.0, timer=monotonic):
        self.maxsize = maxsize
        self.ttl = ttl
        self.timer = timer
        self._expires = OrderedDict()

    def _expire(self, now):
        while self._expires:
            key, deadline = next(iter(self._expires.items()))
            if deadline > now:
                break
            self._expires.pop(key)

    def __contains__(self, key):
        now = self.timer()
        self._expire(now)
        return key in self._expires

    def __setitem__(self, key, value):
        now = self.timer()
        self._expire(now)
        self._expires.pop(key, None)
        if self.ttl <= 0 or self.maxsize <= 0:
            return
        self._expires[key] = now + self.ttl
        while len(self._expires) > self.maxsize:
            self._expires.popitem(last=False)


class Action(TypedDict):
    type: str
    data: Dict[str, str]


ACTION_TYPES = ["callback", "invoke", "answer", "delete"]


class Filters(TypedDict, total=False):
    from_users: List[int]
    chats: List[int]
    is_admin: bool
    contains: bool
    ignorecase: bool


class Trigger(TypedDict):
    id: int
    m: str
    action: Action
    filters: Filters
    delay: float


def validate_trigger(value):
    if not isinstance(value, dict):
        raise ValueError("Trigger must be a JSON object")
    trigger = deepcopy(value)
    if not isinstance(trigger.get("m"), str) or not trigger["m"]:
        raise ValueError("m must be a non-empty string")
    action = trigger.get("action")
    if not isinstance(action, dict) or action.get("type") not in ACTION_TYPES:
        raise ValueError("action.type must be answer, delete, invoke or callback")
    data = action.setdefault("data", {})
    if not isinstance(data, dict):
        raise ValueError("action.data must be an object")
    required = {"answer": "text", "invoke": "command", "callback": "callback_id"}.get(action["type"])
    if required and not isinstance(data.get(required), str):
        raise ValueError("action.data." + required + " must be a string")
    if action["type"] == "invoke" and not isinstance(data.get("args", ""), str):
        raise ValueError("action.data.args must be a string")
    filters = trigger.setdefault("filters", {})
    if not isinstance(filters, dict):
        raise ValueError("filters must be an object")
    for key in ("ignorecase", "contains", "is_admin"):
        if key in filters and not isinstance(filters[key], bool):
            raise ValueError("filters." + key + " must be true/false")
    for key in ("from_users", "chats"):
        if key in filters and (not isinstance(filters[key], list) or
                any(type(i) is not int for i in filters[key])):
            raise ValueError("filters." + key + " must be a list of integer IDs")
    delay = trigger.setdefault("delay", 0)
    if type(delay) not in (int, float) or not math.isfinite(delay) or delay < 0:
        raise ValueError("delay must be a finite non-negative number")
    if not isinstance(trigger.setdefault("enabled", True), bool):
        raise ValueError("enabled must be true/false")
    if type(trigger.get("id")) is not int or trigger["id"] < 0:
        raise ValueError("id must be a non-negative integer")
    return trigger


def parse_value(current, raw):
    if isinstance(current, str):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        try:
            return ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return raw


def dict_updater(obj: Dict[str, Union[dict, Any]], query: str, value: Any) -> None:
    keys = query.split(".")
    current = obj
    for key in keys[:-1]:
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"key {key} not found")
        current = current[key]

    if not isinstance(current, dict):
        raise ValueError(f"key {keys[-1]} not found")
    current[keys[-1]] = value


def dict_getter(obj: Dict[str, Union[dict, Any]], query: str) -> Any:
    keys = query.split(".")
    current = obj
    for key in keys[:-1]:
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"key {key} not found")
        current = current[key]

    if not isinstance(current, dict):
        raise ValueError("Path does not point to an object")
    return current.get(keys[-1])


class TriggerManager:
    def __init__(
        self,
        getter_func: Callable[[str, Optional[JSONSerializable]], JSONSerializable],
        setter_func: Callable[[str, JSONSerializable], bool],
    ) -> None:
        self.getter = getter_func
        self.setter = setter_func

    def get_triggers(self) -> List[Trigger]:
        return deepcopy(self.getter("triggers", []))

    def get_trigger(self, t_id: int) -> Optional[Trigger]:
        triggers = self.get_triggers()
        for t in triggers:
            if t["id"] == t_id:
                return t

    def get_trigger_with_index(self, t_id: int) -> Optional[Tuple[int, Trigger]]:
        triggers = self.get_triggers()
        for i, t in enumerate(triggers):
            if t["id"] == t_id:
                return i, t

    def set_triggers(self, value: List[Trigger]) -> bool:
        return self.setter("triggers", deepcopy(value))

    def add_trigger(self, value: Trigger) -> bool:
        value = validate_trigger(value)
        triggers = self.get_triggers()
        triggers.append(value)
        return self.set_triggers(triggers)

    def set_trigger(self, trigger: Trigger) -> bool:
        trigger = validate_trigger(trigger)
        response = self.get_trigger_with_index(trigger["id"])
        if not response:
            raise ValueError("Trigger has been deleted; refresh the menu")
        i, t = response
        triggers = self.get_triggers()
        triggers[i] = trigger
        return self.set_triggers(triggers)


class Configuration:
    PAGE_SIZE = 8
    ACTION_LABELS = {"answer": "Ответ", "delete": "Удаление сообщения",
                     "invoke": "Команда", "callback": "Callback"}

    def __init__(self, manager: TriggerManager, module=None, chat_id=None):
        self.manager = manager
        self.module = module
        self.chat_id = chat_id
        self._page = 0

    @staticmethod
    def _preview(text, limit=52):
        text = " ".join(str(text).split())
        return text if len(text) <= limit else text[:limit - 1] + "…"

    def _action_preview(self, trigger):
        action = trigger.get("action", {})
        data = action.get("data", {})
        kind = action.get("type", "")
        value = {"answer": data.get("text", ""), "invoke": data.get("command", ""),
                 "callback": data.get("callback_id", "")}.get(kind, "")
        label = self.ACTION_LABELS.get(kind, kind)
        return label + (": " + self._preview(value, 80) if value else "")

    def _menu(self, page=0):
        triggers = sorted(self.manager.get_triggers(), key=lambda t: t["id"])
        pages = max(1, (len(triggers) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        page = max(0, min(page, pages - 1))
        self._page = page
        selected = triggers[page * self.PAGE_SIZE:(page + 1) * self.PAGE_SIZE]
        lines = ["<b>Триггеры</b>", "Выбери правило, чтобы посмотреть, изменить или удалить."]
        if not triggers:
            lines.append("\nСписок пуст. Создай первое правило кнопкой ниже.")
        markup = []
        for trigger in selected:
            state = "🟢" if trigger.get("enabled", True) else "⚪"
            pattern = self._preview(trigger["m"], 100)
            lines.append(f"\n{state} <b>#{trigger['id']}</b> <code>{utils.escape_html(pattern)}</code>"
                         f"\n{utils.escape_html(self._action_preview(trigger))}")
            markup.append([{"text": f"{state} #{trigger['id']} · {self._preview(trigger['m'], 36)}",
                            "callback": self._open_trigger_config,
                            "kwargs": {"trigger": trigger}}])
        if pages > 1:
            nav = []
            if page > 0:
                nav.append({"text": "← Назад", "callback": self._open_triggers_menu,
                            "kwargs": {"page": page - 1}})
            if page + 1 < pages:
                nav.append({"text": "Дальше →", "callback": self._open_triggers_menu,
                            "kwargs": {"page": page + 1}})
            markup.append(nav)
            lines.append(f"\nСтраница {page + 1}/{pages}")
        markup.append([{"text": "➕ Создать триггер", "input": "Введите текст, на который реагировать",
                        "handler": self._create_trigger}])
        if self.module is not None:
            active = bool(self.module.config["status"])
            markup.append([{"text": "Модуль: " + ("включён 🟢" if active else "выключен ⚪"),
                            "callback": self._toggle_module}])
            if self.chat_id is not None:
                included = self.chat_id in self.module.get("chats", [])
                markup.append([{"text": ("Убрать текущий чат" if included else "Добавить текущий чат"),
                                "callback": self._toggle_chat}])
        markup.append([{"text": "Обновить", "callback": self._open_triggers_menu,
                        "kwargs": {"page": page}},
                       {"text": "Закрыть", "action": "close"}])
        return "\n".join(lines), markup

    def _trigger_config_markup(self, trigger):
        enabled = trigger.get("enabled", True)
        rows = [
            [{"text": "Выключить" if enabled else "Включить",
              "callback": self._toggle_rule, "kwargs": {"trigger": trigger}},
             {"text": "🗑 Удалить", "callback": self._confirm_delete,
              "kwargs": {"trigger": trigger}}],
            [self._input_button(trigger, "m", "Текст триггера"),
             self._input_button(trigger, "delay", "Задержка")],
        ]
        if trigger["action"]["type"] == "answer":
            rows.append([self._input_button(trigger, "action.data.text", "Текст ответа")])
        rows.extend([
            [{"text": "Фильтры", "callback": self._open_filters_config_menu,
              "kwargs": {"trigger": trigger}},
             {"text": "Действие", "callback": self._open_action_config_menu,
              "kwargs": {"trigger": trigger}}],
            [{"text": "← К списку", "callback": self._open_triggers_menu,
              "kwargs": {"page": self._page}}],
        ])
        return rows

    def _trigger_config_text(self, trigger):
        state = "включён" if trigger.get("enabled", True) else "выключен"
        pattern = utils.escape_html(str(trigger["m"])[:1200])
        action = trigger["action"]
        data = action.get("data", {})
        detail = {"answer": data.get("text", ""), "invoke": data.get("command", "") + " " + data.get("args", ""),
                  "callback": data.get("callback_id", "")}.get(action["type"], "")
        filters = trigger.get("filters", {})
        lines = [f"<b>Триггер #{trigger['id']}</b> · {state}", f"\n<b>Реагирует на:</b>\n<code>{pattern}</code>",
                 f"\n<b>Действие:</b> {self.ACTION_LABELS.get(action['type'], action['type'])}"]
        if detail:
            lines.append(utils.escape_html(str(detail)[:1200]))
        elif action["type"] == "answer":
            lines.append("<i>Текст ответа ещё не задан</i>")
        lines.append(f"\n<b>Задержка:</b> {trigger.get('delay', 0)} с")
        flags = []
        if filters.get("ignorecase"): flags.append("без учёта регистра")
        if filters.get("contains"): flags.append("по части сообщения")
        if filters.get("is_admin"): flags.append("только администраторы")
        for key, title in (("from_users", "авторы"), ("chats", "чаты")):
            if key in filters:
                flags.append(title + ": " + str(filters[key]))
        lines.append("<b>Фильтры:</b> " + utils.escape_html(self._preview(", ".join(flags), 600) if flags else "без ограничений"))
        return "\n".join(lines)

    async def _toggle_module(self, call):
        self.module.config["status"] = not self.module.config["status"]
        await self._open_triggers_menu(call, self._page)

    async def _toggle_chat(self, call):
        chats = list(self.module.get("chats", []))
        if self.chat_id in chats:
            chats.remove(self.chat_id)
        else:
            chats.append(self.chat_id)
        self.module.set("chats", chats)
        await self._open_triggers_menu(call, self._page)

    async def _create_trigger(self, call, query):
        if not query.strip():
            await call.answer("Текст триггера не может быть пустым")
            return
        if self.module is None:
            await call.answer("Открой меню заново через .tmenu")
            return
        trigger = {"id": self.module.increment_trigger_id(), "m": query,
                   "enabled": False, "delay": 0, "filters": {},
                   "action": {"type": "answer", "data": {"text": ""}}}
        self.manager.add_trigger(trigger)
        await self._open_trigger_config(call, trigger)

    async def _toggle_rule(self, call, trigger):
        current = self.manager.get_trigger(trigger["id"])
        if current is None:
            await call.answer("Этот триггер уже удалён")
            await self._open_triggers_menu(call, self._page)
            return
        enabled = not current.get("enabled", True)
        required = {"answer": "text", "invoke": "command", "callback": "callback_id"}.get(current["action"]["type"])
        if enabled and required and not current["action"].get("data", {}).get(required):
            await call.answer("Сначала задай данные действия")
            return
        current["enabled"] = enabled
        self.manager.set_trigger(current)
        await self._open_trigger_config(call, current)

    async def _confirm_delete(self, call, trigger):
        current = self.manager.get_trigger(trigger["id"])
        if current is None:
            await call.answer("Этот триггер уже удалён")
            await self._open_triggers_menu(call, self._page)
            return
        expected = json.dumps(current, sort_keys=True, ensure_ascii=False)
        await call.edit(
            text="<b>Удалить этот триггер?</b>\n\n" + self._trigger_config_text(current),
            reply_markup=[
                [{"text": "🗑 Да, удалить #" + str(current["id"]), "callback": self._delete_trigger,
                  "kwargs": {"trigger_id": current["id"], "expected": expected}}],
                [{"text": "Отмена", "callback": self._open_trigger_config,
                  "kwargs": {"trigger": current}}],
            ],
        )

    async def _delete_trigger(self, call, trigger_id, expected):
        current = self.manager.get_trigger(trigger_id)
        if current is None:
            await call.answer("Этот триггер уже удалён")
        elif json.dumps(current, sort_keys=True, ensure_ascii=False) != expected:
            await call.answer("Правило изменилось. Проверь его перед удалением.")
            await self._confirm_delete(call, current)
            return
        else:
            self.manager.set_triggers([t for t in self.manager.get_triggers() if t["id"] != trigger_id])
            await call.answer("Триггер #" + str(trigger_id) + " удалён")
        await self._open_triggers_menu(call, self._page)

    def _trigger_filters_markup(self, trigger: Trigger) -> HikkaReplyMarkup:
        types = Filters.__annotations__.items()
        f = []
        for k, v in types:
            if v == bool:
                f.append(self._bool_filter_config(trigger, k))
            elif v == List[int]:
                f.append(self._list_int_filter_config(trigger, k))

        f.append(
            [
                {
                    "text": "⬅️ Back",
                    "callback": self._open_trigger_config,
                    "kwargs": {"trigger": trigger},
                }
            ]
        )

        return f

    def _bool_filter_config(self, trigger, key):
        labels = {"ignorecase": "Без учёта регистра", "contains": "По части текста",
                  "is_admin": "Только администраторы"}
        trigger_id = trigger["id"]
        async def callback(call):
            current = self.manager.get_trigger(trigger_id)
            if current is None:
                await call.answer("Этот триггер уже удалён")
                await self._open_triggers_menu(call, self._page)
                return
            current["filters"][key] = not current["filters"].get(key, False)
            self.manager.set_trigger(current)
            await self._open_filters_config_menu(call, current)
        state = "✅" if trigger["filters"].get(key, False) else "⚪"
        return [{"text": state + " " + labels.get(key, key), "callback": callback}]

    def _list_int_filter_config(self, trigger: Trigger, key: str) -> HikkaReplyMarkup:
        async def callback(call: InlineCall, query: str, action: str) -> None:
            val: List[int] = trigger["filters"].get(key)
            if val is None:
                await call.answer("filter not found")
                return
            if action == "append":
                if not query.isdigit():
                    logger.error("input value to append must be an integer")
                    return
                val.append(int(query))
            elif action == "set":
                try:
                    query = ast.literal_eval(query)
                    if isinstance(query, int):
                        val = [query]
                    elif iter(query) and isinstance(query[0], int):
                        val = list(query)
                    else:
                        raise ValueError(
                            "input value must be list of integers or integers. For example: [-123, 456, 678]; 123"
                        )

                except (ValueError, TypeError) as e:
                    logger.warning(f"{query}, {type(query)}")
                    logger.error(e)
                    return

            elif action == "delete":
                try:
                    query = ast.literal_eval(query)
                    if not isinstance(query, int):
                        raise ValueError("input value must be an integer")

                    with suppress(ValueError):
                        val.remove(query)

                except ValueError as e:
                    logger.error(e)
                    return

            trigger["filters"][key] = val
            self.manager.set_trigger(trigger)
            await open_configuration(call)

        async def open_configuration(call: InlineCall) -> None:
            val: Optional[List[int]] = trigger["filters"].get(key)
            if val is None:
                val = []
                trigger["filters"][key] = val

            await call.edit(
                text=f"<b>Configuring </b><code>{key}</code><b> of trigger </b><code>{trigger['id']}</code>: \n<code>{val}</code>",
                reply_markup=[
                    [
                        {
                            "text": f"➕ Add value",
                            "input": "✍️ Enter value to append",
                            "handler": callback,
                            "kwargs": {"action": "append"},
                        },
                    ],
                    [
                        {
                            "text": f"➖ Delete value",
                            "input": "✍️ Enter value to delete",
                            "handler": callback,
                            "kwargs": {"action": "delete"},
                        },
                    ],
                    [
                        {
                            "text": f"✍️ Set",
                            "input": "✍️ Enter list to replace",
                            "handler": callback,
                            "kwargs": {"action": "set"},
                        }
                    ],
                    [
                        {
                            "text": "⬅️ Back",
                            "callback": self._open_filters_config_menu,
                            "kwargs": {"trigger": trigger},
                        }
                    ],
                ],
            )

        return [
            {
                "text": {"from_users": "Авторы (ID)", "chats": "Чаты (ID)"}.get(key, key),
                "callback": open_configuration,
            }
        ]

    def _input_button(
        self, trigger: Trigger, path: str, title: str
    ) -> HikkaReplyMarkup:
        return {
            "text": f"✍️ {title.capitalize()}",
            "input": f"Введите новое значение: {title}",
            "handler": self._update_trigger_input_handler,
            "kwargs": {
                "path": path,
                "trigger": trigger,
            },
        }

    async def _update_trigger_input_handler(
        self, call: InlineCall, query: str, path: str, trigger: Trigger
    ) -> None:
        trigger = self.manager.get_trigger(trigger["id"])
        if trigger is None:
            await call.answer("Этот триггер уже удалён")
            await self._open_triggers_menu(call, self._page)
            return
        try:
            val = dict_getter(trigger, path)
        except ValueError:
            await call.answer("error")
            return

        try:
            value = parse_value(val, query)
            dict_updater(trigger, path, value)
            self.manager.set_trigger(trigger)
        except (ValueError, TypeError, KeyError, SyntaxError) as error:
            await call.answer(str(error)[:180])
            return

        await call.edit(
            text=self._trigger_config_text(trigger),
            reply_markup=self._trigger_config_markup(trigger),
        )

    async def _open_filters_config_menu(
        self, call: InlineCall, trigger: Trigger
    ) -> None:
        markup = self._trigger_filters_markup(trigger)
        await call.edit(text="⚙️ <b>Настройки фильтров</b>", reply_markup=markup)

    async def __change_action_type(
        self, call: InlineCall, val: str, trigger: Trigger
    ) -> None:
        if val not in ACTION_TYPES:
            await call.answer("error")
            return
        trigger = self.manager.get_trigger(trigger["id"])
        if trigger is None:
            await call.answer("Этот триггер уже удалён")
            return
        if trigger["action"]["type"] != val:
            defaults = {"answer": {"text": ""}, "delete": {},
                        "invoke": {"command": "", "args": ""}, "callback": {"callback_id": ""}}
            trigger["action"] = {"type": val, "data": defaults[val]}
            trigger["enabled"] = False
        self.manager.set_trigger(trigger)
        await call.answer("✅")
        await self._open_action_type_config_menu(call, trigger)

    async def _open_action_type_config_menu(
        self, call: InlineCall, trigger: Trigger
    ) -> None:
        markup = utils.chunks(
            [
                {
                    "text": f"{'⚫️' if trigger['action']['type'] == t else '⚪️'} {t}",
                    "callback": self.__change_action_type,
                    "kwargs": {"val": t, "trigger": trigger},
                }
                for t in ACTION_TYPES
            ],
            2,
        )
        markup.append(
            [
                {
                    "text": "⬅️ Back",
                    "callback": self._open_action_config_menu,
                    "kwargs": {"trigger": trigger},
                }
            ]
        )

        await call.edit("⚙️ <b>Выберите действие:</b>", reply_markup=markup)

    async def _open_action_config_menu(
        self, call: InlineCall, trigger: Trigger
    ) -> None:
        markup = [
            [
                {
                    "text": "♦️ Type",
                    "callback": self._open_action_type_config_menu,
                    "kwargs": {"trigger": trigger},
                }
            ],
            [self._input_button(trigger, "action.data", "data")],
            [
                {
                    "text": "⬅️ Back",
                    "callback": self._open_trigger_config,
                    "kwargs": {"trigger": trigger},
                }
            ],
        ]
        await call.edit(
            text=f"⚙️ <b>Настройки действия</b>\n<code>{utils.escape_html(str(trigger['action']))}</code>",
            reply_markup=markup,
        )

    async def _open_triggers_menu(self, call: InlineCall, page=0):
        text, markup = self._menu(page)
        await call.edit(text=text, reply_markup=markup)

    async def _open_trigger_config(self, call: InlineCall, trigger: Trigger):
        current = self.manager.get_trigger(trigger["id"])
        if current is None:
            await call.answer("Этот триггер уже удалён")
            await self._open_triggers_menu(call, self._page)
            return
        await call.edit(text=self._trigger_config_text(current),
                        reply_markup=self._trigger_config_markup(current))

    async def render_specified_trigger(self, form, message, trigger):
        return await form(text=self._trigger_config_text(trigger), message=message,
                          reply_markup=self._trigger_config_markup(trigger), force_me=True)

    async def render(self, form, message):
        text, markup = self._menu()
        return await form(text=text, message=message, reply_markup=markup, force_me=True)


@loader.tds
class Triggers(loader.Module):
    """Triggers watch chat messages and can do anything, reply to a message with a given text, delete a message, execute any userbot command. Overall, a very cool module"""

    strings = {
        "name": "Triggers",
        "_cfg_status": "module working or not",
        "_cfg_allow_invoke": "can triggers run ANY userbot commands?",
        "_cfg_allow_callback": "can triggers run ANY python code?",
        "_cfg_throttle_time": "cooldown between trigger executions",
        "no_reply": "<emoji document_id=5210952531676504517>❌</emoji> No reply!",
        "no_args": "<emoji document_id=5210952531676504517>❌</emoji> No args!",
        "text_add": (
            "<emoji document_id=5427009714745517609>✅</emoji> <b>Trigger successfully added</b>\n"
            "<i>id:</i> <code>{id}</code>"
        ),
        "empty": "  <emoji document_id=5411324253662356461>🫗</emoji> Empty\n",
        "text_all": (
            "<emoji document_id=5443038326535759644>💬</emoji> <b>Your triggers:</b>\n"
            "{triggers}\n"
            "<i>in {chats} chats</i>"
        ),
        "chat_added": "<emoji document_id=5456140674028019486>⚡️</emoji> <b>Chat {chat} successfully added</b>",
        "chat_removed": "<emoji document_id=5440660757194744323>‼️</emoji> <b>Chat {chat} successfully removed</b>",
        "success": "<emoji document_id=5427009714745517609>✅</emoji> <b>Success</b>",
        "not_found": "<emoji document_id=5210952531676504517>❌</emoji> <b>Trigger not found!</b>",
        "not_valid": "<emoji document_id=5210952531676504517>❌</emoji> <b>Trigger is not valid!</b>",
        "error": "<emoji document_id=5210952531676504517>❌</emoji> <b>Unexpected error: {e}</b>",
    }

    strings_ru = {
        "_cfg_status": "Модуль работает или нет",
        "_cfg_allow_invoke": "могут ли триггеры запускать ЛЮБЫЕ команды юзербота?",
        "_cfg_allow_callback": "могут ли триггеры запускать АБСОЛЮТНО любой код на python?",
        "_cfg_throttle_time": "Пауза между выполнением триггеров. Изменения применяются сразу.",
        "no_reply": "<emoji document_id=5210952531676504517>❌</emoji> Нет реплая!",
        "no_args": "<emoji document_id=5210952531676504517>❌</emoji> Нет аргументов!",
        "text_add": (
            "<emoji document_id=5427009714745517609>✅</emoji> <b>Триггер успешно добавлен</b>\n"
            "<i>id:</i> <code>{id}</code>"
        ),
        "empty": "  <emoji document_id=5411324253662356461>🫗</emoji> Пусто\n",
        "text_all": (
            "<emoji document_id=5443038326535759644>💬</emoji> <b>Ваши триггеры:</b>\n"
            "{triggers}\n"
            "<i>в {chats} чатах</i>"
        ),
        "chat_added": "<emoji document_id=5456140674028019486>⚡️</emoji> <b>Чат {chat} успешно добавлен</b>",
        "chat_removed": "<emoji document_id=5440660757194744323>‼️</emoji> <b>Чат {chat} успешно убран</b>",
        "success": "<emoji document_id=5427009714745517609>✅</emoji> <b>Успешно</b>",
        "not_found": "<emoji document_id=5210952531676504517>❌</emoji> <b>Триггер не найден!</b>",
        "not_valid": "<emoji document_id=5210952531676504517>❌</emoji> <b>Триггер не валиден!</b>",
        "error": "<emoji document_id=5210952531676504517>❌</emoji> <b>Неожиданная ошибка. Обратитесь к разработчику модуля или попробуйте изменить данные: {e}</b>",
        "_cls_doc": "Триггеры следят за сообщениями в чате и могут сделать что угодно, ответить на сообщение заданным текстом, удалить сообщение, выполнить любую команду юзербота. В общем очень крутой модуль",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "status",
                False,
                lambda: self.strings("_cfg_status"),
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "allow_invoke",
                False,
                lambda: self.strings("_cfg_allow_invoke"),
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "allow_callback",
                True,
                lambda: self.strings("_cfg_allow_callback"),
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "throttle_time",
                1.0,
                lambda: self.strings("_cfg_throttle_time"),
                validator=loader.validators.Float(minimum=0),
            ),
        )

        self.cache = _TriggerCooldown(maxsize=10_000, ttl=float(self.config["throttle_time"]))
        self.manager = TriggerManager(self.get, self.set)

    async def client_ready(self):
        self.cache = _TriggerCooldown(ttl=float(self.config["throttle_time"]))
        logger.info("Triggers menu v3 loaded; saved triggers: %d",
                    len(self.manager.get_triggers()))

    def increment_trigger_id(self) -> int:
        triggers: List[Trigger] = self.get("triggers", [])
        candidate = max((t.get("id", -1) for t in triggers), default=-1) + 1
        candidate = max(candidate, self.get("next_trigger_id", 0))
        self.set("next_trigger_id", candidate + 1)
        return candidate

    async def _execute_callback(
        self, callback_id: str, message: Message, trigger: Trigger
    ) -> None:
        callbacks: Dict[str, int] = self.get("callbacks", {})
        if not (asset_id := callbacks.get(callback_id)):
            logger.error("callback with id %s not found", callback_id)
            return
        asset: Optional[Message] = await self.db.fetch_asset(asset_id)
        if not asset:
            logger.error("callback code not found", asset_id)
            return

        code = asset.text
        reply = await message.get_reply_message()
        kwargs = {
            "client": self.client,
            "c": self.client,
            "message": message,
            "m": message,
            "reply": reply,
            "r": reply,
            "trigger": trigger,
            "t": trigger,
            "utils": utils,
        }

        try:
            await meval(code, globals(), **kwargs)
        except Exception as e:
            logger.exception("callback code error: %s", e)

    @loader.command(
        ru_doc="[текст, на который будет тригеррится модуль] <реплай на текст ответа> - Добавить базовый триггер",
        alias="taddbase",
    )
    async def triggeraddbase(self, message: Message):
        """[text that the module will trigger on] <reply on the response text> - Add base trigger"""
        triggers = self.get("triggers", [])

        args = utils.get_args_raw(message)
        if not args:
            await utils.answer(message, self.strings("no_args"))
            return

        reply = await message.get_reply_message()
        if not reply or not reply.text:
            await utils.answer(message, self.strings("no_reply"))
            return

        trigger = Trigger(
            m=args,
            id=self.increment_trigger_id(),
            action=Action(type="answer", data={"text": reply.text}),
            delay=0,
            filters=Filters(),
        )
        triggers.append(trigger)
        self.set("triggers", triggers)

        text = self.strings("text_add").format(id=trigger["id"])

        await utils.answer(message, text)

    @loader.command(ru_doc="[триггер] - Добавить триггер из сырых данных", alias="tadd")
    async def triggeradd(self, message: Message):
        """[trigger] - Add a trigger from raw data"""
        args = utils.get_args_raw(message)
        if not args:
            await utils.answer(message, self.strings("no_args"))
            return

        try:
            trigger = json.loads(args)
            if not isinstance(trigger, dict):
                raise ValueError("Trigger must be a JSON object")
            trigger["id"] = self.increment_trigger_id()
            self.manager.add_trigger(validate_trigger(trigger))
        except (ValueError, TypeError, KeyError) as error:
            await utils.answer(message, self.strings("error").format(e=utils.escape_html(str(error))))
            return

        text = self.strings("text_add").format(id=trigger["id"])

        await utils.answer(message, text)

    @loader.command(ru_doc="Посмотреть все триггеры")
    async def triggers(self, message: Message):
        """View all triggers"""

        triggers = self.manager.get_triggers()
        t = ""

        if not triggers:
            t = self.strings("empty")
        else:
            for trigger in triggers:
                t += f"  • {utils.escape_html(trigger['m'])} {trigger['id']} action={trigger['action']['type'].lower()} enabled={trigger.get('enabled', True)};\n"

        text = self.strings("text_all").format(
            triggers=t, chats=len(self.get("chats", []))
        )

        await utils.answer(message, text)

    @loader.command(ru_doc="Добавить чат, где будут работать триггеры", alias="tchat")
    async def triggerchat(self, message: Message):
        """Add chat, where triggers will work"""
        chats = self.get("chats", [])
        chat_id = utils.get_chat_id(message)
        flag = False

        if chat_id not in chats:
            chats.append(chat_id)
            flag = True
        else:
            chats.remove(chat_id)

        self.set("chats", chats)

        text = (
            self.strings("chat_added").format(chat=chat_id)
            if flag
            else self.strings("chat_removed").format(chat=chat_id)
        )

        await utils.answer(message, text)

    @loader.command()
    async def tmenu(self, message: Message):
        """Открыть меню триггеров: просмотр, создание, изменение и удаление."""
        config = Configuration(self.manager, self, utils.get_chat_id(message))
        await config.render(self.inline.form, message)

    @loader.command(ru_doc="[необязятельно: айди триггера] - Конфиг модуля")
    async def tconfig(self, message: Message):
        """[optional: trigger id] - Triggers config."""
        config = Configuration(self.manager, self, utils.get_chat_id(message))
        args = utils.get_args(message)
        if len(args) < 1 or not args[0].isdigit():
            await config.render(self.inline.form, message)
            return

        tid = int(args[0])
        trigger = self.manager.get_trigger(tid)
        if not trigger:
            await config.render(self.inline.form, message)
            return

        await config.render_specified_trigger(self.inline.form, message, trigger)


    @loader.command(ru_doc="[айди триггера] - Удалить триггер", alias="tdel")
    async def triggerdel(self, message: Message):
        """[trigger's id] - Delete trigger"""
        args = utils.get_args_raw(message).split()
        if not args:
            await utils.answer(message, self.strings("no_args"))
            return

        if not args[0].isdigit():
            await utils.answer(
                message, self.strings("error").format(e="Input id must be an integer")
            )
            return

        triggers = self.manager.get_triggers()
        for trigger in triggers:
            if trigger["id"] == int(args[0]):
                triggers.remove(trigger)
                self.manager.set_triggers(triggers)
                await utils.answer(message, self.strings("success"))
                return

        await utils.answer(message, self.strings("not_found"))

    @loader.command(ru_doc="[айди колбека: str] <реплай на пайтон код> - Добавить колбек, который триггер сможет выполнить")
    async def tcallback(self, message: Message):
        """[callback_id: str] <reply to python code> - Add a callback that trigger can execute"""
        args = utils.get_args_raw(message).split()
        if not args:
            await utils.answer(message, self.strings("no_args"))
            return
        callback_id = args[0]

        reply = await message.get_reply_message()
        if not reply or not reply.raw_text:
            await utils.answer(message, self.strings("no_reply"))
            return

        asset_id = await self.db.store_asset(reply)
        callbacks = self.get("callbacks", {})
        callbacks[callback_id] = asset_id
        self.set("callbacks", callbacks)

        await utils.answer(message, self.strings("success"))

    @loader.command(ru_doc="[айди триггера] - Получить триггер", alias="tget")
    async def triggerget(self, message: Message):
        """[trigger's id] - Get trigger"""
        args = utils.get_args_raw(message).split()
        if not args:
            await utils.answer(message, self.strings("no_args"))
            return

        if not args[0].isdigit():
            await utils.answer(
                message, self.strings("error").format(e="Input id must be an integer")
            )
            return

        trigger = self.manager.get_trigger(int(args[0]))
        if trigger:
            await utils.answer(message, "<code>" + utils.escape_html(json.dumps(trigger, ensure_ascii=False)) + "</code>")
            return

        await utils.answer(message, self.strings("not_found"))

    @loader.command(
        ru_doc="[айди триггера] [измененный триггер] - Изменить триггер", alias="tset"
    )
    async def triggerset(self, message: Message):
        """[trigger's id] [edited trigger] - Edit trigger"""
        args = utils.get_args_raw(message).split(maxsplit=1)
        if not args:
            await utils.answer(message, self.strings("no_args"))
            return
        if len(args) < 2:
            await utils.answer(message, self.strings("no_args"))
            return

        if not args[0].isdigit():
            await utils.answer(
                message, self.strings("error").format(e="Input id must be an integer")
            )
            return
        trigger_id = int(args[0])
        trigger = self.manager.get_trigger(trigger_id)
        if not trigger:
            await utils.answer(message, self.strings("not_found"))
            return

        try:
            new_trigger = json.loads(args[1])
            if not isinstance(new_trigger, dict):
                raise ValueError("Trigger must be a JSON object")
            new_trigger["id"] = trigger["id"]
            self.manager.set_trigger(validate_trigger(new_trigger))
        except Exception as e:
            await utils.answer(message, self.strings("error").format(e=utils.escape_html(str(e))))
            return

        await utils.answer(message, self.strings("success"))

    @loader.command(
        ru_doc="[айди триггера] [путь] [значение] - Изменить одно значение триггера",
        alias="tupd",
    )
    async def triggerupdate(self, message: Message):
        """[trigger's id] [path] [value] - Edit trigger"""
        args = utils.get_args_raw(message).split(maxsplit=2)
        if not args or len(args) < 3:
            await utils.answer(message, self.strings("no_args"))
            return
        if not args[0].isdigit():
            await utils.answer(
                message, self.strings("error").format(e="Input id must be an integer")
            )
            return

        trigger = self.manager.get_trigger(int(args[0]))
        if not trigger:
            await utils.answer(message, self.strings("not_found"))
            return

        path = args[1]
        value = args[2]
        try:
            current = dict_getter(trigger, path)
            value = parse_value(current, value)
            if path == "id":
                raise ValueError("Trigger ID cannot be changed")
            dict_updater(trigger, path, value)
            self.manager.set_trigger(validate_trigger(trigger))
        except (ValueError, TypeError, KeyError, SyntaxError) as error:
            await utils.answer(message, self.strings("error").format(e=utils.escape_html(str(error))))
            return

        await utils.answer(message, self.strings("success"))

    @loader.command(alias="ton")
    async def triggeron(self, message: Message):
        """<id> Enable one trigger."""
        await self._toggle_trigger(message, True)

    @loader.command(alias="toff")
    async def triggeroff(self, message: Message):
        """<id> Disable one trigger without deleting it."""
        await self._toggle_trigger(message, False)

    async def _toggle_trigger(self, message, enabled):
        raw = utils.get_args_raw(message).strip()
        if not raw.isdigit():
            await utils.answer(message, self.strings("error").format(e="Expected trigger ID"))
            return
        trigger = self.manager.get_trigger(int(raw))
        if trigger is None:
            await utils.answer(message, self.strings("not_found"))
            return
        trigger["enabled"] = enabled
        try:
            self.manager.set_trigger(trigger)
        except (ValueError, TypeError, KeyError) as error:
            await utils.answer(message, self.strings("error").format(e=utils.escape_html(str(error))))
            return
        await utils.answer(message, self.strings("success"))

    @loader.watcher(only_messages=True)
    async def triggers_handler(self, message: Message):
        if not self.config["status"]:
            return
        text = getattr(message, "raw_text", None) or getattr(message, "text", None)
        if not text:
            return
        chat_id = utils.get_chat_id(message)
        if chat_id not in self.get("chats", []):
            return
        ttl = float(self.config["throttle_time"])
        if self.cache.ttl != ttl:
            self.cache = _TriggerCooldown(ttl=ttl)
        for stored in self.manager.get_triggers():
            try:
                trigger = validate_trigger(stored)
                if not trigger["enabled"]:
                    continue
                filters = trigger["filters"]
                if "chats" in filters and chat_id not in filters["chats"]:
                    continue
                if "from_users" in filters and message.sender_id not in filters["from_users"]:
                    continue
                pattern, candidate = trigger["m"], text
                if filters.get("ignorecase"):
                    pattern, candidate = pattern.casefold(), candidate.casefold()
                if candidate != pattern and not (filters.get("contains") and pattern in candidate):
                    continue
                if filters.get("is_admin"):
                    if not getattr(message, "is_group", False) or message.sender_id is None:
                        continue
                    permissions = await self._client.get_permissions(await message.get_chat(), message.sender_id)
                    if not (permissions.is_admin or permissions.is_creator):
                        continue
                if trigger["id"] in self.cache:
                    continue
                self.cache[trigger["id"]] = None
                if trigger["delay"]:
                    await asyncio.sleep(trigger["delay"])
                action = trigger["action"]
                if action["type"] == "answer":
                    await message.reply(action["data"]["text"].replace("{text}", utils.escape_html(text)))
                elif action["type"] == "delete":
                    await message.delete()
                elif action["type"] == "invoke" and self.config["allow_invoke"]:
                    await self.invoke(action["data"]["command"], action["data"].get("args", ""), message=message)
                elif action["type"] == "callback" and self.config["allow_callback"]:
                    await self._execute_callback(action["data"]["callback_id"], message, trigger)
            except Exception as error:
                logger.warning("Triggers: rule %s failed (%s)", stored.get("id", "unknown") if isinstance(stored, dict) else "unknown", type(error).__name__)
