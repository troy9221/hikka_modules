"""Hikka module for playing Контекстно with Codex CLI."""

# SPDX-License-Identifier: GPL-3.0-only
# scope: hikka_only

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from .. import loader, utils

__version__ = (1, 8, 0)

BOT = "contextno_rf_bot"
CODEX_TIMEOUTS = {"low": 30, "medium": 55}
STALL_ROUNDS = 4
GUESS_ROLES = ("bridge", "neighbor", "alternative")
EXPLORATION_RANK = 1000
CLOSE_RANK = 100
GUESS_DOMAINS = (
    "люди и отношения", "дом и повседневные вещи", "природа и животные",
    "места и движение", "работа и общество", "техника и материалы",
    "действия и процессы", "качества и состояния",
)
GROUP_PERMISSIONS = {"allow": "разрешено", "deny": "запрещено"}
GROUPS_PER_PAGE = 5
MOSCOW_TZ = timezone(timedelta(hours=3), "МСК")
PLAY_WINDOW_RE = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])\s*[-–—]\s*([01][0-9]|2[0-3]):([0-5][0-9])")
PLAY_TIME_UNITS = {"d": 86400, "h": 3600, "m": 60}
PLAY_TIME_TOKEN = re.compile(
    r"([0-9]{1,6})\s*(день|дня|дней|часов|часа|час|минуты|минута|минут|[dhmдчм])\s*"
)
RECENT_GAME_WINDOW = timedelta(minutes=15)
REPLY_STYLE_TAGS = {"italic": "i", "bold": "b", "plain": None}
CODEX_MODELS_HELP = (
    "auto — модель по умолчанию Codex CLI.\n"
    "gpt-6-luna — быстрый подбор слов.\n"
    "gpt-6.1-terra — быстрый вариант для более сложных подсказок.\n"
    "gpt-6.1-sol, gpt-6-sol — для сложных раундов.\n"
    "gpt-6-astra — для самых сложных раундов, если модель доступна.\n"
    "Можно ввести другой ID. Доступные модели показывает /model в терминале Codex."
)
WORD = r"[а-яё]+(?:-[а-яё]+)*"
NUMBER = r"[0-9]+(?:[ \u00a0\u202f][0-9]{3})*"
WORD_RE = re.compile(WORD)
TOP_RE = re.compile(r"^[^\w\n]*Топ(?:-\d+)? ближайших слов:[^\S\n]*$", re.I | re.M)
ROW_RE = re.compile(rf"^[^\w\n]*({WORD})\s+\(({NUMBER})\)\s*$", re.I)
SCORE_RE = re.compile(
    rf"^Слово:\s*({WORD})[^\n]*\n\s*Близость:\s*({NUMBER})\s*$", re.I | re.M
)
UNKNOWN_RE = re.compile(
    rf"^Слово\s+[«\"„]?({WORD})[»\"“]?\s+не найдено в словаре", re.I
)
DUPLICATE_RE = re.compile(
    rf"^Слово\s+[«\"„]?({WORD})[»\"“]?\s+уже\s+(?:было\s+)?использовано", re.I
)
NEW_RE = re.compile(r"^[^\w\n]*Новая игра начата\b", re.I)
WIN_RE = re.compile(
    r"\b(?:игра завершена|слово угадано|(?:у|от)гадал[аи]?\s+(?:загаданное\s+)?слово"
    r"|вы угадали)\b|\bугадал[аи]?\s*[:!]", re.I
)
ENV_KEYS = (
    "PATH", "HOME", "CODEX_HOME", "USER", "LOGNAME", "LANG", "LC_ALL",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR", "SYSTEMROOT",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "CODEX_CA_CERTIFICATE",
)
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "theme": {"type": "string"},
                    "role": {"type": "string", "enum": list(GUESS_ROLES)},
                    "domain": {"type": "string", "enum": list(GUESS_DOMAINS)},
                    "anchors": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["word", "theme", "role", "domain", "anchors"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["candidates"],
    "additionalProperties": False,
}
PROMPT = (
    "Игра Контекстно: нужно угадать скрытое русское слово по семантическим рангам "
    "проверенных слов. Ранг 1 — разгадка, меньший ранг означает более близкий "
    "контекст употребления. Сопоставь несколько лучших слов и их разные значения. "
    "Ищи общее окружение слов: типичные сочетания, предмет, действие, профессию "
    "или область, где они встречаются вместе. Сравни ранги прошлых догадок с лучшим "
    "рангом на момент отправки. Развивай связи, которые дали улучшение. "
    "Далёкие ответы ослабляют соответствующую гипотезу, но не исключают её полностью. "
    "Несколько близких однокоренных слов или синонимов считай одной группой подсказок. "
    "Отдельно ищи близкие слова из другой группы, даже если они стоят немного ниже. "
    "Верни по одному кандидату на каждую роль. "
    "bridge — слово, которое естественно сочетается с подсказками из двух групп. "
    "Проверь, что с каждой группой у него своя естественная связь. "
    "neighbor — точное соседнее понятие сильнейшей подсказки. "
    "alternative — другое значение, участник или условие ситуации, которое ещё не проверяли. "
    "Все три слова должны проверять разные связи. Следуй стратегии текущего хода. "
    "Упорядочь кандидатов: первым поставь наиболее полезный следующий ход с учётом фактических рангов. "
    "word — одно слово кириллицей, строчными буквами, в начальной форме. "
    "Выбирай обычные общеупотребительные слова, исключай имена, жаргон и редкие термины. "
    "При равных вариантах выбирай существительное в именительном падеже. "
    "Не предлагай выдуманные слова и не переноси грубую лексику из истории в догадки. "
    "theme — название проверяемой смысловой связи в 2–5 словах. "
    "domain — основная смысловая область предложенного слова. "
    "anchors — проверенные слова из списка опор, с которыми у кандидата есть "
    "прямая смысловая связь или естественное словосочетание. Если списка опор нет, верни пустой массив. "
    "Исключи уже проверенные слова и их грамматические формы."
)
logger = logging.getLogger(__name__)


class CodexError(Exception):
    """An error safe to report in Hikka."""


def normalize(word):
    return word.lower().replace("ё", "е")


def ranked_word(match):
    word, rank = match.groups()
    return word.lower(), int("".join(rank.split()))


def parse_top(text):
    header = TOP_RE.search(text)
    if not header:
        return []
    rows = []
    for line in text[header.end():].splitlines():
        if not line.strip():
            continue
        match = ROW_RE.fullmatch(line)
        if not match:
            break
        word, rank = ranked_word(match)
        if rank > 0:
            rows.append((word, rank))
    return rows


def chat_key(message):
    header = getattr(message, "reply_to", None)
    topic = 0
    if getattr(header, "forum_topic", False):
        topic = header.reply_to_top_id or header.reply_to_msg_id or 0
    return f"{message.chat_id}:{topic}"


def validate_group_rule(value):
    if value == "":
        return ""
    parts = [part.strip() for part in str(value).split("|", 2)]
    if len(parts) == 3:
        group_id, permission, title = parts
        permission = permission.lower()
        title = " ".join(title.split())
        if re.fullmatch(r"-[1-9][0-9]*", group_id) and re.fullmatch(r"allow(?:@\d{1,12})?|deny", permission) and title:
            return f"{group_id} | {permission} | {title}"
    raise loader.validators.ValidationError("Введите отрицательный ID | allow или deny | Название группы.")


def parse_play_duration(value):
    seconds = 0
    remaining = value.strip().lower()
    while remaining:
        match = PLAY_TIME_TOKEN.match(remaining)
        if not match:
            raise ValueError("Время не изменено. Введи, например, 2h, 2 часа или 30m.")
        amount, unit = match.groups()
        unit = {"д": "d", "ч": "h", "м": "m"}.get(unit[0], unit[0])
        seconds += int(amount) * PLAY_TIME_UNITS[unit]
        remaining = remaining[match.end():].lstrip()
    if not seconds:
        raise ValueError("Укажи время больше нуля, например 1m.")
    return seconds


def format_play_duration(seconds):
    minutes = (max(0, seconds) + 59) // 60
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    return " ".join(f"{value}{unit}" for value, unit in ((days, "d"), (hours, "h"), (minutes, "m")) if value) or "0m"


def parse_play_window(value):
    value = value.strip().lower()
    if value == "off":
        return None
    match = PLAY_WINDOW_RE.fullmatch(value)
    if not match:
        raise ValueError("Введи окно по Москве, например 09:00-18:00. Для удаления введи off.")
    start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
    start, end = start_hour * 60 + start_minute, end_hour * 60 + end_minute
    if start == end:
        raise ValueError("Начало и конец должны отличаться. Для игры без окна введи off.")
    return start, end


def format_play_window(window):
    start, end = window
    return f"{start // 60:02d}:{start % 60:02d}–{end // 60:02d}:{end % 60:02d} МСК"


def play_window_state(window, now):
    local = datetime.fromtimestamp(now, MOSCOW_TZ)
    minute = local.hour * 60 + local.minute
    start, end = window
    inside = (minute - start) % 1440 < (end - start) % 1440
    boundary = end if inside else start
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    transition = midnight + timedelta(minutes=boundary)
    if transition <= local:
        transition += timedelta(days=1)
    return inside, transition.timestamp() - now


@dataclass
class Round:
    latest_id: int = 0
    latest_bot_message: object = None
    best: int = 0
    scores: dict = field(default_factory=dict)
    unknown: set = field(default_factory=set)
    duplicates: set = field(default_factory=set)
    guesses: dict = field(default_factory=dict)
    last_guess_score: tuple | None = None
    last_error: str = ""
    pending: str = ""
    closed: bool = False
    worker: object = None


@loader.tds
class ContextnoCodexMod(loader.Module):
    """Играет в Контекстно через Codex CLI при достижении заданной близости."""

    strings = {"name": "ContextnoCodex"}

    def __init__(self):
        self._rounds = {}
        self._play_timers = {}
        self._window_timers = {}
        self._window_tasks = set()
        self._config_hook = None
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "codex_bin", "", "Путь к Codex CLI. По умолчанию используется FIRSTCONTACT_CODEX_BIN, PATH или ~/.local/bin.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "codex_model", "auto", CODEX_MODELS_HELP,
                validator=loader.validators.String(min_len=1),
            ),
            loader.ConfigValue(
                "reply_style", "italic",
                "Стиль догадок в Telegram. italic — курсив, bold — жирный, plain — обычный текст.",
                validator=loader.validators.Choice(list(REPLY_STYLE_TAGS)),
            ),
            loader.ConfigValue(
                "start_rank", 500,
                "Максимальное место в «Топе ближайших слов», при котором модуль начинает играть. "
                "Например, при 500 модуль вступает в игру с места 500 или ближе.",
                validator=loader.validators.Integer(minimum=2),
            ),
            loader.ConfigValue(
                "probe_moves", 1,
                "Сколько первых оценённых автоходов при слабых подсказках отвести на проверку гипотез. "
                "При месте 1000 или ближе бот сразу развивает сильную подсказку. 0 — без пробных ходов.",
                validator=loader.validators.Integer(minimum=0, maximum=5),
            ),
            loader.ConfigValue(
                "group_rules", [],
                "Список групп с кнопками включения, отключения и удаления. "
                "«Таймер» задаёт срок игры. «Окно» задаёт ежедневное время по Москве, например 09:00-18:00. "
                "При ручном вводе используйте формат "
                "ID | allow или deny | Название группы. Например, -1001234567890 | allow | Контекстно с друзьями. "
                "Для одного ID действует последнее правило. Команда .contextno group показывает ID текущей группы.",
                validator=loader.validators.Series(
                    loader.validators.Validator(validate_group_rule, "строкой ID | allow или deny | Название группы"),
                ),
                on_change=self._group_rules_changed,
            ),
        )
        self._codex_lock = asyncio.Lock()

    async def client_ready(self):
        if not self.get("codex_model_migrated", False):
            if self.config["codex_model"] == "gpt-5.4-mini":
                self.config["codex_model"] = "auto"
            self.set("codex_model_migrated", True)
        self._attach_group_settings()
        await self._migrate_enabled_groups()
        legacy = self.get("play_deadlines", {})
        if legacy:
            rules = []
            for rule in self.config["group_rules"]:
                group_id, permission, title = rule.split(" | ", 2)
                if permission == "allow" and group_id in legacy:
                    rule = f"{group_id} | allow@{legacy[group_id]} | {title}"
                rules.append(rule)
            self.config["group_rules"] = rules
            self._save_group_rules()
            self.set("play_deadlines", {})
        self._group_rules_changed()

    async def on_unload(self):
        for timer in self._play_timers.values():
            timer.cancel()
        self._play_timers.clear()
        for timer in self._window_timers.values():
            timer.cancel()
        self._window_timers.clear()
        for task in self._window_tasks:
            task.cancel()
        if self._config_hook:
            configurator, original, wrapper = self._config_hook
            if configurator.inline__configure_option is wrapper:
                configurator.inline__configure_option = original
            self._config_hook = None
        for game in self._rounds.values():
            if game.worker:
                game.worker.cancel()
        self._rounds.clear()

    def _can_play(self, game):
        return not game.closed and 1 < game.best <= self.config["start_rank"]

    def _group_rule(self, group_id):
        for rule in reversed(self.config["group_rules"]):
            saved_id, permission, title = rule.split(" | ", 2)
            if saved_id == group_id:
                mode, _, deadline = permission.partition("@")
                return mode, title, int(deadline) if deadline else None
        return None

    def _is_armed(self, group_id):
        rule = self._group_rule(group_id)
        return bool(rule and rule[0] == "allow" and (rule[2] is None or rule[2] > time.time()))

    def _is_enabled(self, key):
        group_id = key.split(":", 1)[0]
        if not self._is_armed(group_id):
            return False
        window = self.get("play_windows", {}).get(group_id)
        return not window or play_window_state(window, time.time())[0]

    def _arm_window(self, group_id):
        timer = self._window_timers.pop(group_id, None)
        if timer:
            timer.cancel()
        window = self.get("play_windows", {}).get(group_id)
        if window and self._is_armed(group_id):
            _, delay = play_window_state(window, time.time())
            self._window_timers[group_id] = asyncio.get_running_loop().call_later(
                delay, self._on_window_boundary, group_id,
            )

    def _on_window_boundary(self, group_id):
        self._arm_window(group_id)
        if not self._is_enabled(group_id):
            self._prune_disabled_rounds()
            return
        task = asyncio.create_task(self._resume_game(int(group_id)))
        self._window_tasks.add(task)
        task.add_done_callback(self._window_tasks.discard)

    def _expire_play_timer(self, group_id, deadline):
        rule = self._group_rule(group_id)
        if not rule or rule[2] != deadline:
            return
        if deadline > time.time():
            self._group_rules_changed()
            return
        self._set_group_rule(group_id, "deny", rule[1])

    def _group_rules_changed(self):
        self._prune_disabled_rounds()
        for timer in self._play_timers.values():
            timer.cancel()
        self._play_timers.clear()
        for timer in self._window_timers.values():
            timer.cancel()
        self._window_timers.clear()
        loop = asyncio.get_running_loop()
        group_ids = {rule.split(" | ", 1)[0] for rule in self.config["group_rules"]}
        for group_id in group_ids:
            _, _, deadline = self._group_rule(group_id)
            if deadline is not None:
                self._play_timers[group_id] = loop.call_later(
                    max(0, deadline - time.time()), self._expire_play_timer, group_id, deadline,
                )
            self._arm_window(group_id)

    def _time_left(self, group_id):
        rule = self._group_rule(group_id)
        deadline = rule[2] if rule else None
        return format_play_duration(deadline - int(time.time())) if deadline is not None else ""

    def _attach_group_settings(self):
        configurator = self.lookup("HikkaConfig")
        original = getattr(configurator, "inline__configure_option", None)
        if self._config_hook or not callable(original):
            return

        # Hikka's standard config has no per-option renderer hook.
        async def configure_option(call, mod, config_opt, force_hidden=False, obj_type=False):
            if self._config_hook and config_opt == "group_rules" and self.lookup(mod) is self:
                return await self._show_groups(call, back=(mod, obj_type))
            return await original(call, mod, config_opt, force_hidden, obj_type)

        self._config_hook = (configurator, original, configure_option)
        configurator.inline__configure_option = configure_option

    async def _migrate_enabled_groups(self):
        legacy = self.get("enabled", [])
        if not legacy:
            return
        rules = list(self.config["group_rules"])
        group_ids = dict.fromkeys(key.split(":", 1)[0] for key in legacy)
        for group_id in group_ids:
            if not re.fullmatch(r"-[1-9][0-9]*", group_id) or self._group_rule(group_id):
                continue
            title = f"Группа {group_id}"
            try:
                chat = await self._client.get_entity(int(group_id))
            except Exception:
                logger.debug("ContextnoCodex: не удалось получить название группы %s", group_id)
            else:
                if getattr(chat, "broadcast", False):
                    continue
                title = getattr(chat, "title", None) or title
            rules.append(f"{group_id} | allow | {title}")
        self.config["group_rules"] = rules
        self.set("enabled", [])

    def _prune_disabled_rounds(self):
        for key in list(self._rounds):
            if not self._is_enabled(key):
                game = self._rounds.pop(key)
                if game.worker:
                    game.worker.cancel()

    def _set_group_rule(self, group_id, permission, title="", duration=None):
        rules = {rule.split(" | ", 1)[0]: rule for rule in self.config["group_rules"]}
        current = self._group_rule(group_id)
        if permission == "allow":
            if duration is not None:
                permission = f"allow@{int(time.time()) + duration}"
            elif current and current[2] and self._is_armed(group_id):
                permission = f"allow@{current[2]}"
        if permission != "clear":
            rules[group_id] = f"{group_id} | {permission} | {title}"
        else:
            rules.pop(group_id, None)
        self.config["group_rules"] = list(rules.values())
        self._save_group_rules()
        if permission == "clear":
            windows = dict(self.get("play_windows", {}))
            if group_id in windows:
                windows.pop(group_id)
                self.set("play_windows", windows)

    def _save_group_rules(self):
        # Flush the rule and its deadline together before a reload can restore the old rule.
        config = dict(self.get("__config__", {}))
        config["group_rules"] = self.config["group_rules"]
        self.set("__config__", config)

    async def _show_groups(self, call, page=0, back=None, notice=""):
        rules = {}
        for rule in self.config["group_rules"]:
            group_id, permission, title = rule.split(" | ", 2)
            rules[group_id] = (permission, title)
        pages = max(1, (len(rules) + GROUPS_PER_PAGE - 1) // GROUPS_PER_PAGE)
        page = max(0, min(page, pages - 1))
        start = page * GROUPS_PER_PAGE
        rows = list(rules.items())[start:start + GROUPS_PER_PAGE]
        lines = ["<b>Группы ContextnoCodex</b>", ""]
        buttons = []
        for index, (group_id, (_, title)) in enumerate(rows, start + 1):
            enabled = self._is_armed(group_id)
            status = "включено" if enabled else "выключено"
            window = self.get("play_windows", {}).get(group_id)
            if window:
                if enabled and not self._is_enabled(group_id):
                    status = "ждёт начала окна"
                status += f", ежедневно {format_play_window(window)}"
            remaining = self._time_left(group_id) if enabled else ""
            if remaining:
                status += f", осталось {remaining}"
            lines.append(f"{index}. <b>{escape(title)}</b> · {status} · <code>{group_id}</code>")
            buttons.append([
                {
                    "text": f"{'Отключить' if enabled else 'Включить'} №{index}",
                    "callback": self._change_group,
                    "args": (group_id, "deny" if enabled else "allow", page, back),
                },
                {
                    "text": f"Таймер №{index}",
                    "input": "Время игры, например 2 часа, 1h 1m или 1d",
                    "handler": self._set_group_timer_from_menu,
                    "args": (group_id, page, back, call.inline_message_id),
                },
                {
                    "text": f"Окно №{index}",
                    "input": "Ежедневно по Москве: 09:00-18:00. Удалить окно: off",
                    "handler": self._set_group_window_from_menu,
                    "args": (group_id, page, back, call.inline_message_id),
                },
                {"text": f"Удалить №{index}", "callback": self._change_group, "args": (group_id, "clear", page, back)},
            ])
        if not rows:
            lines.append("Список пуст. Добавь группу по ID через настройки.")
        if pages > 1:
            lines.append(f"\nСтраница {page + 1} из {pages}")
            buttons.append([
                {"text": label, "callback": self._show_groups, "args": (target, back)}
                for label, target in (("⬅️", page - 1), ("➡️", page + 1))
                if 0 <= target < pages
            ])
        if back and self._config_hook:
            mod, obj_type = back
            configurator, original, _ = self._config_hook
            buttons.append([
                {"text": "Добавить по ID", "callback": original, "args": (mod, "group_rules"), "kwargs": {"obj_type": obj_type}},
            ])
            buttons.append([
                {"text": "Назад в настройки", "callback": configurator.inline__configure, "args": (mod,), "kwargs": {"obj_type": obj_type}},
            ])
        buttons.append([{"text": "Закрыть", "action": "close"}])
        if notice:
            lines.extend(("", notice))
        await call.edit("\n".join(lines), reply_markup=buttons)

    async def _set_group_timer_from_menu(self, call, query, group_id, page, back, inline_message_id):
        # The chosen inline result belongs to the input message, so edit the original menu.
        call.inline_message_id = inline_message_id
        rule = self._group_rule(group_id)
        if not rule:
            notice = "Группа удалена из списка."
        else:
            try:
                duration = parse_play_duration(query.lower())
            except ValueError as exc:
                notice = str(exc)
            else:
                self._set_group_rule(group_id, "allow", rule[1], duration)
                notice = f"Таймер установлен на {format_play_duration(duration)}."
                status = await self._resume_group(int(group_id))
                notice += f" {status}"
        await self._show_groups(call, page, back, escape(notice))

    async def _set_group_window_from_menu(self, call, query, group_id, page, back, inline_message_id):
        call.inline_message_id = inline_message_id
        if not self._group_rule(group_id):
            notice = "Группа удалена из списка."
        else:
            try:
                window = parse_play_window(query)
            except ValueError as exc:
                notice = str(exc)
            else:
                windows = dict(self.get("play_windows", {}))
                if window is None:
                    windows.pop(group_id, None)
                    notice = "Ежедневное окно удалено."
                else:
                    windows[group_id] = list(window)
                    notice = f"Ежедневное окно: {format_play_window(window)}."
                self.set("play_windows", windows)
                self._group_rules_changed()
                notice += f" {await self._resume_group(int(group_id))}"
        await self._show_groups(call, page, back, escape(notice))

    async def _resume_group(self, chat_id, key=None):
        group_id = str(chat_id)
        if not self._is_armed(group_id):
            return "Автоподбор выключен."
        if not self._is_enabled(group_id):
            return "Жду начала ежедневного окна."
        return await self._resume_game(chat_id, key)

    async def _change_group(self, call, group_id, permission, page, back):
        rule = self._group_rule(group_id)
        notice = ""
        if rule and (permission != "allow" or not self._is_armed(group_id)):
            self._set_group_rule(group_id, permission, rule[1])
            if permission == "allow":
                notice = await self._resume_group(int(group_id))
        await self._show_groups(call, page, back, escape(notice))

    async def _group_command(self, message, permission, duration=None):
        if not message.is_group:
            return "Выполни .contextno group в группе, чтобы узнать её ID и название."
        if permission not in {"", "allow", "deny", "clear"}:
            return "Используй .contextno group allow, deny или clear."
        group_id = str(message.chat_id)
        chat = await message.get_chat()
        title = " ".join((getattr(chat, "title", None) or f"Группа {group_id}").split())
        label = f"{escape(title)} (<code>{group_id}</code>)"
        if permission:
            self._set_group_rule(group_id, permission, title, duration)
            if permission == "clear":
                return f"{label}. Группа удалена из списка, автоподбор выключен."
            result = f"{label}. Во всех темах {GROUP_PERMISSIONS[permission]}."
            if permission == "allow":
                remaining = self._time_left(group_id)
                result += f" Осталось {remaining}." if remaining else " Без ограничения по времени."
                result += f" {await self._resume_group(message.chat_id, chat_key(message))}"
            return result
        rule = self._group_rule(group_id)
        policy = (
            f"Во всех темах {GROUP_PERMISSIONS['allow' if self._is_armed(group_id) else 'deny']}."
            if rule else "Правила для группы пока нет."
        )
        return f"{label}. {policy}"

    @loader.command()
    async def contextno(self, message):
        """on [1d 1h 1m] | off | status | check | models | groups | group — управление автоподбором."""
        action = utils.get_args_raw(message).strip().lower() or "status"
        key = chat_key(message)
        group_id = key.split(":", 1)[0]
        verb, _, argument = action.partition(" ")
        if verb == "on":
            try:
                duration = parse_play_duration(argument) if argument.strip() else None
            except ValueError as exc:
                result = str(exc)
            else:
                result = await self._group_command(message, "allow", duration)
        elif action == "off":
            result = await self._group_command(message, "deny")
        elif action == "groups":
            form = await self.inline.form("Группы ContextnoCodex", message=message, silent=True)
            if form:
                await self._show_groups(form)
                return
            result = "Открой .config ContextnoCodex → group_rules."
        elif action == "group" or action.startswith("group "):
            result = await self._group_command(message, action[5:].strip())
        elif action == "status":
            game = self._rounds.get(key)
            armed = self._is_armed(group_id)
            result = "Автоподбор включён." if armed else "Автоподбор выключен."
            rule = self._group_rule(group_id)
            if rule:
                permission = "allow" if armed else "deny"
                result += f" {escape(rule[1])} (<code>{group_id}</code>) — {GROUP_PERMISSIONS[permission]}."
            result += f" Порог входа: топ-{self.config['start_rank']}."
            window = self.get("play_windows", {}).get(group_id)
            if window:
                result += f" Ежедневное окно: {format_play_window(window)}."
            if armed:
                remaining = self._time_left(group_id)
                if remaining:
                    result += f" По таймеру осталось {remaining}."
                result += f" {self._game_status(game)}" if self._is_enabled(key) else " Жду начала ежедневного окна."
            if game and game.best:
                result += f" Лучшее место в топе: {game.best}. Попыток: {len(game.guesses)}."
                if self._can_play(game) and min(rank for _, rank in game.scores.values()) > EXPLORATION_RANK:
                    result += " Режим: широкий поиск по разным областям."
                if game.last_guess_score:
                    word, rank = game.last_guess_score
                    result += f" Последняя оценённая догадка: {word} ({rank})."
        elif action == "models":
            result = f"Выбор модели в .config ContextnoCodex → codex_model.\n\n{CODEX_MODELS_HELP}"
        elif action == "check":
            await utils.answer(message, "Проверяю Codex CLI…")
            try:
                loop = asyncio.get_running_loop()
                started = loop.time()
                candidates = await self._suggest({"ближайшие": [["орден", 450], ["медаль", 2200]]})
                word = next((item[0] for item in candidates if normalize(item[0]) not in {"орден", "медаль"}), "")
                elapsed = loop.time() - started
                result = (
                    f"Codex CLI ответил за {elapsed:.1f} с. Пример слова: {word}."
                    if word else "Codex не вернул новое слово."
                )
            except CodexError as exc:
                result = str(exc)
        else:
            result = "Используйте .contextno on, off, status, check, models, groups или group."
        await utils.answer(message, result)

    @loader.watcher("in", "only_messages")
    async def watcher(self, message):
        key = chat_key(message)
        if not self._is_enabled(key):
            return
        if await self._is_game_bot(message) and self._is_enabled(key):
            self._observe_game(key, message, live=True)

    async def _is_game_bot(self, message):
        sender = getattr(message, "sender", None) or await message.get_sender()
        return getattr(sender, "bot", False) and (getattr(sender, "username", None) or "").lower() == BOT

    def _queue_guess(self, key, game):
        if game and not game.worker and self._is_enabled(key) and self._can_play(game):
            game.worker = asyncio.create_task(self._play(key, game))

    def _game_status(self, game):
        if game and game.worker:
            return "Codex подбирает слово."
        if game and game.closed:
            return "Раунд завершён. Жду следующего."
        if not game or not game.best:
            return "Жду сообщение игрового бота с топом ближайших слов."
        if game.best > self.config["start_rank"]:
            return f"Лучшее место {game.best}. Для входа нужно {self.config['start_rank']} или ближе."
        if game.pending:
            return "Жду оценку отправленного слова."
        if game.last_error:
            return f"Последняя ошибка: {game.last_error}"
        return "Готов к следующему игровому сообщению."

    async def _resume_game(self, chat_id, key=None):
        game = self._rounds.get(key)
        if game and game.worker:
            return self._game_status(game)
        cutoff = datetime.now(timezone.utc) - RECENT_GAME_WINDOW
        recent = []
        try:
            async for item in self._client.iter_messages(chat_id, from_user=BOT, limit=30):
                if item.date < cutoff:
                    break
                if (key is None or chat_key(item) == key) and await self._is_game_bot(item):
                    recent.append(item)
        except Exception:
            logger.warning("ContextnoCodex: не удалось прочитать историю игрового бота", exc_info=True)
            return "Не удалось прочитать историю игры. Жду новое сообщение с топом."
        if not self._is_enabled(str(chat_id)):
            return "Автоподбор выключен."
        if key is None:
            for item in recent:
                text = (item.raw_text or "").strip()
                if parse_top(text) or SCORE_RE.search(text) or NEW_RE.match(text) or WIN_RE.search(text):
                    key = chat_key(item)
                    break
            if key is None:
                return self._game_status(None)
            recent = [item for item in recent if chat_key(item) == key]
        for item in reversed(recent):
            self._observe_game(key, item, live=False)
        game = self._rounds.get(key)
        if game and not game.pending and any(item.id == game.latest_id for item in recent):
            self._queue_guess(key, game)
        return self._game_status(game)

    def _observe_game(self, key, message, live):
        game = self._rounds.setdefault(key, Round())
        if game.latest_bot_message is None or message.id > game.latest_bot_message.id:
            game.latest_bot_message = message
        if message.id <= game.latest_id:
            return

        text = (message.raw_text or "").strip()
        top = parse_top(text)
        score = SCORE_RE.search(text)
        unknown = UNKNOWN_RE.match(text)
        duplicate = DUPLICATE_RE.match(text)
        started = NEW_RE.match(text)
        finished = WIN_RE.search(text)
        if started:
            if game.worker:
                game.worker.cancel()
            self._rounds[key] = Round(latest_id=message.id, latest_bot_message=game.latest_bot_message)
            return
        if game.closed:
            return

        latest_score = ranked_word(score) if score else None
        if latest_score and latest_score[1] < 1:
            latest_score = None
        ranks = top + ([latest_score] if latest_score else [])
        if latest_score and normalize(latest_score[0]) in game.guesses:
            game.last_guess_score = latest_score
        if finished or any(rank == 1 for _, rank in ranks):
            game.latest_id = message.id
            game.closed = True
            if game.worker:
                game.worker.cancel()
            return

        feedback = False
        if unknown or duplicate:
            word = normalize((unknown or duplicate).group(1))
            (game.unknown if unknown else game.duplicates).add(word)
            if word != game.pending:
                return
            game.pending = ""
            feedback = True
        elif not ranks:
            return

        if ranks:
            game.best = min(rank for _, rank in ranks)
            if not top and game.scores:
                game.best = min(game.best, min(rank for _, rank in game.scores.values()))
        for word, rank in top:
            game.scores[normalize(word)] = (word, rank)
        if latest_score:
            word, rank = latest_score
            normalized = normalize(word)
            game.scores.pop(normalized, None)
            game.scores[normalized] = (word, rank)
        if game.pending and game.pending in game.scores:
            game.last_guess_score = game.scores[game.pending]
            game.pending = ""
            feedback = True
        game.latest_id = message.id
        if live and (ranks or feedback):
            self._queue_guess(key, game)

    def _guess_context(self, game, retried):
        ranked = sorted(game.scores.values(), key=lambda item: item[1])
        history = []
        stalled = 0
        evaluated = 0
        role_misses = dict.fromkeys(GUESS_ROLES, 0)
        domain_probes = dict.fromkeys(GUESS_DOMAINS, 0)
        for word, (theme, role, domain, best_before) in game.guesses.items():
            attempt = {"слово": word, "связь": theme, "роль": role, "область": domain}
            if word in game.duplicates:
                history.append({**attempt, "результат": "слово уже использовано"})
                continue
            score = game.scores.get(word)
            if score:
                _, rank = score
                evaluated += 1
                if best_before > EXPLORATION_RANK:
                    domain_probes[domain] += 1
                if rank < best_before and (best_before <= EXPLORATION_RANK or rank * 4 <= best_before * 3):
                    stalled = 0
                    role_misses = dict.fromkeys(GUESS_ROLES, 0)
                else:
                    stalled += 1
                    role_misses[role] += 1
                history.append({**attempt, "ранг": rank, "лучший_до": best_before})
            elif word in game.unknown:
                history.append({**attempt, "результат": "нет в словаре"})

        best = ranked[0][1]
        probing = best > EXPLORATION_RANK and evaluated < self.config["probe_moves"]
        role_order = sorted(GUESS_ROLES, key=role_misses.__getitem__)
        preferred_domains = []
        anchors = []
        required_anchor = None
        if probing:
            role_order = ["alternative", "bridge", "neighbor"]
            strategy = (
                "Это пробный ход. Не предлагай наиболее вероятную разгадку и её прямые синонимы. "
                "Для alternative выбери обычное слово, которое проверяет другую трактовку лидера "
                "или помогает различить две темы. Проверь переносные значения и устойчивые выражения. "
                "Избегай случайных слов без объяснимой связи с подсказками."
            )
        elif best > EXPLORATION_RANK:
            if stalled == 0 and history and history[-1].get("ранг") == best and not retried:
                strategy = (
                    "Последняя догадка заметно улучшила ранг. Проверь одно распространённое "
                    "слово из найденного направления. Два запасных возьми из других областей."
                )
            else:
                least_tested = min(domain_probes.values())
                preferred_domains = [domain for domain in GUESS_DOMAINS if domain_probes[domain] == least_tested]
                role_order = ["alternative", "bridge", "neighbor"]
                strategy = (
                    "Ранги выше 1000 дают слабый сигнал. Проверь разные значения лидера: "
                    "буквальный смысл, переносный смысл, устойчивое выражение или характерное действие. "
                    "Выбирай обычные слова с объяснимой связью хотя бы с одной подсказкой. "
                    "Разнообразие областей полезно, когда обе гипотезы объясняют подсказки."
                )
        elif best <= CLOSE_RANK or (len(ranked) > 1 and ranked[1][1] <= best * 4):
            anchors = [(word, rank) for word, rank in ranked[:8] if rank <= best * 6]
            if len(ranked) == 1 or ranked[1][1] >= best * 3:
                required_anchor = ranked[0][0]
            role_order = list(GUESS_ROLES)
            strategy = (
                "Для каждого кандидата назови его прямые связи с опорными словами. "
                "Если задана обязательная опора, каждый кандидат должен прямо с ней сочетаться. "
                "В theme дай естественное словосочетание с опорой. "
                "Меняй связь внутри подтверждённой темы: состав, применение, результат, упаковка, "
                "состояние или форма. Отдавай приоритет обычным словам с несколькими связями. "
                "Промахи исключают конкретную ассоциацию, но не отменяют сильного лидера. "
                "Проверяй устойчивые выражения и переносные значения. "
                "Не опирайся только на более далёкие подсказки."
            )
        elif retried or stalled >= STALL_ROUNDS:
            strategy = (
                "Проверь альтернативное значение ближайших слов. "
                "Начни с новой смысловой связи, а остальные варианты возьми из других направлений."
            )
        else:
            strategy = (
                "Сопоставь несколько ближайших подсказок с разными значениями. "
                "Отдавай предпочтение устойчивым сочетаниям и конкретным понятиям."
            )
        data = {
            "ближайшие": ranked[:24],
            "последние_оценённые_слова": list(game.scores.values())[-20:],
            "история_догадок_модуля": history[-12:],
            "попыток_без_улучшения": stalled,
            "стратегия": strategy,
            "пробный_ход": probing,
            "приоритет_ролей": role_order,
            "предпочтительные_области": preferred_domains,
            "опорные_слова": anchors,
            "обязательная_опора": required_anchor,
            "исключить": sorted(game.guesses.keys() | game.unknown | game.duplicates | game.scores.keys()),
        }
        if retried:
            data["повторный_подбор"] = "Предложи другие слова и соблюдай требования к опорам, если они заданы."
        recheck = stalled > 0 and stalled % STALL_ROUNDS == 0
        first_probe = best > EXPLORATION_RANK and not any(domain_probes.values())
        effort = "medium" if retried or probing or anchors or recheck or first_probe else "low"
        return data, effort

    def _select_guess(self, candidates, excluded, data):
        role_order = data["приоритет_ролей"]
        preferred_domains = data["предпочтительные_области"]
        available = [item for item in candidates if normalize(item[0]) not in excluded]
        anchors = {normalize(word): rank for word, rank in data["опорные_слова"]}
        if anchors:
            required = normalize(data["обязательная_опора"] or "")
            for item in available:
                matches = item[4] & anchors.keys()
                if matches and (not required or required in matches):
                    return item
            return None
        if not preferred_domains:
            return next(iter(available), None)
        return min(
            available,
            key=lambda item: (bool(preferred_domains and item[3] not in preferred_domains), role_order.index(item[2])),
            default=None,
        )

    async def _play(self, key, game):
        retried = False
        game.last_error = ""
        try:
            while self._is_enabled(key) and self._can_play(game):
                data, effort = self._guess_context(game, retried)
                candidates = await self._suggest(data, effort)
                if self._rounds.get(key) is not game or not self._is_enabled(key) or not self._can_play(game):
                    return
                excluded = game.guesses.keys() | game.unknown | game.duplicates | game.scores.keys()
                candidate = self._select_guess(candidates, excluded, data)
                if candidate is None:
                    if not retried:
                        retried = True
                        continue
                    game.last_error = "Codex дважды не предложил подходящего нового слова."
                    return
                retried = False
                guess, theme, role, domain, _ = candidate
                normalized = normalize(guess)
                game.pending = normalized
                best_before = min(rank for _, rank in game.scores.values())
                game.guesses[normalized] = (theme, role, domain, best_before)
                revision = game.latest_id
                tag = REPLY_STYLE_TAGS[self.config["reply_style"]]
                text = f"<{tag}>{guess}</{tag}>" if tag else guess
                try:
                    await game.latest_bot_message.reply(text, parse_mode="html" if tag else None)
                except Exception:
                    game.guesses.pop(normalized, None)
                    game.pending = ""
                    raise
                if revision == game.latest_id or game.pending:
                    return
        except CodexError as exc:
            game.last_error = str(exc)
            logger.warning("ContextnoCodex: %s", exc)
        except Exception:
            game.last_error = "Hikka не смогла отправить догадку в Telegram."
            logger.exception("ContextnoCodex: ошибка при отправке слова")
        finally:
            game.worker = None

    async def _suggest(self, data, effort="low"):
        configured = self.config["codex_bin"].strip() or os.environ.get("FIRSTCONTACT_CODEX_BIN", "").strip()
        executable = shutil.which(configured or "codex")
        if not executable and not configured:
            executable = shutil.which(str(Path.home() / ".local" / "bin" / "codex"))
        if not executable:
            raise CodexError("Codex CLI не найден. Укажите codex_bin в .config ContextnoCodex.")
        model = self.config["codex_model"].strip()
        model_args = ["-m", model] if model and model != "auto" else []
        timeout = CODEX_TIMEOUTS[effort]
        env = {key: os.environ[key] for key in ENV_KEYS if key in os.environ}
        prompt = f"{PROMPT}\n\n{json.dumps(data, ensure_ascii=False)}".encode("utf-8")
        async with self._codex_lock:
            with tempfile.TemporaryDirectory(prefix="hikka-contextno-") as cwd:
                schema = Path(cwd) / "schema.json"
                schema.write_text(json.dumps(OUTPUT_SCHEMA), encoding="utf-8")
                output = Path(cwd) / "answer.json"
                try:
                    process = await asyncio.create_subprocess_exec(
                        executable, "-a", "never", *model_args,
                        "-c", f'model_reasoning_effort="{effort}"', "--disable", "shell_tool",
                        "--disable", "apps", "--disable", "plugins",
                        "-c", 'web_search="disabled"', "-c", "agents.enabled=false",
                        "-c", "mcp_servers={}", "exec", "--ignore-user-config",
                        "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only",
                        "--output-schema", str(schema), "--output-last-message", str(output), "-",
                        cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
                    )
                except OSError as exc:
                    raise CodexError("Hikka не смогла запустить Codex CLI.") from exc
                try:
                    _, stderr = await asyncio.wait_for(process.communicate(prompt), timeout)
                except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
                    if process.returncode is None:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                    await process.wait()
                    if isinstance(exc, asyncio.CancelledError):
                        raise
                    raise CodexError(f"Codex CLI не ответил за {timeout} секунд.") from exc
                if process.returncode:
                    detail = stderr.decode("utf-8", errors="replace").lower()
                    if any(term in detail for term in (
                        "model_not_found", "not supported when using codex", "unsupported model",
                        "model is not available", "model is not supported", "invalid model",
                    )):
                        raise CodexError(
                            "Выбранная модель недоступна в Codex. "
                            "В .config ContextnoCodex → codex_model выберите auto или модель из /model."
                        )
                    if any(term in detail for term in ("usage limit", "rate limit", "429")):
                        raise CodexError("Codex сообщил о лимите. Проверьте лимит Codex в аккаунте.")
                    if any(term in detail for term in (
                        "401 unauthorized", "invalid_grant", "refresh token", "not logged in", "login required",
                    )):
                        raise CodexError("Codex сообщил об ошибке входа. Проверьте codex login status под пользователем Hikka.")
                    if any(term in detail for term in ("unexpected argument", "unrecognized option")):
                        raise CodexError("Установленная версия Codex CLI не поддерживает один из параметров. Обновите Codex CLI.")
                    raise CodexError(
                        f"Codex CLI завершился с кодом {process.returncode}. "
                        "Попробуйте codex_model = auto и повторите .contextno check."
                    )
                try:
                    candidates = json.loads(output.read_text(encoding="utf-8"))["candidates"]
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise CodexError("Codex CLI вернул некорректный ответ.") from exc
        if not isinstance(candidates, list):
            raise CodexError("Codex CLI вернул некорректный список слов.")
        suggestions = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            word, theme, role = candidate.get("word"), candidate.get("theme"), candidate.get("role")
            domain = candidate.get("domain")
            anchors = candidate.get("anchors")
            if (
                isinstance(word, str) and len(word) <= 40 and WORD_RE.fullmatch(word)
                and isinstance(theme, str) and role in GUESS_ROLES and domain in GUESS_DOMAINS
                and isinstance(anchors, list)
            ):
                anchor_words = {normalize(item) for item in anchors if isinstance(item, str) and WORD_RE.fullmatch(item)}
                suggestions.append((word, theme.strip()[:80], role, domain, anchor_words))
        return suggestions

