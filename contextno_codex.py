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
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from .. import loader, utils

__version__ = (1, 5, 0)

BOT = "contextno_rf_bot"
CODEX_TIMEOUTS = {"low": 30, "medium": 55}
STALL_ROUNDS = 4
GUESS_ROLES = ("bridge", "neighbor", "alternative")
GROUP_PERMISSIONS = {"allow": "разрешено", "deny": "запрещено"}
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
TOP_RE = re.compile(r"^\s*Топ ближайших слов:\s*$", re.I | re.M)
ROW_RE = re.compile(rf"^[^\w\n]*({WORD})\s+\(({NUMBER})\)\s*$", re.I)
SCORE_RE = re.compile(
    rf"^Слово:\s*({WORD})[^\n]*\n\s*Близость:\s*({NUMBER})\s*$", re.I | re.M
)
UNKNOWN_RE = re.compile(
    rf"^Слово\s+[«\"„]?({WORD})[»\"“]?\s+не найдено в словаре", re.I
)
NEW_RE = re.compile(r"^[^\w\n]*Новая игра начата\b", re.I)
WIN_RE = re.compile(
    r"\b(?:игра завершена|слово угадано|угадал[аи]?\s+(?:загаданное\s+)?слово"
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
                },
                "required": ["word", "theme", "role"],
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
    "word — одно слово кириллицей, строчными буквами, в начальной форме. "
    "theme — название проверяемой смысловой связи в 2–5 словах. "
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
        if re.fullmatch(r"-[1-9][0-9]*", group_id) and permission in GROUP_PERMISSIONS and title:
            return f"{group_id} | {permission} | {title}"
    raise loader.validators.ValidationError("Введите отрицательный ID | allow или deny | Название группы.")


@dataclass
class Round:
    latest_id: int = 0
    latest_bot_message: object = None
    best: int = 0
    scores: dict = field(default_factory=dict)
    unknown: set = field(default_factory=set)
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
                "group_rules", [],
                "Правила для всех тем группы. Добавляйте по одному в формате "
                "ID | allow или deny | Название группы. Например, -1001234567890 | allow | Контекстно с друзьями. "
                "Для одного ID действует последнее правило. Команда .contextno group показывает ID текущей группы.",
                validator=loader.validators.Series(
                    loader.validators.Validator(validate_group_rule, "строкой ID | allow или deny | Название группы"),
                ),
                on_change=self._prune_disabled_rounds,
            ),
        )
        self._codex_lock = asyncio.Lock()

    async def client_ready(self):
        if not self.get("codex_model_migrated", False):
            if self.config["codex_model"] == "gpt-5.4-mini":
                self.config["codex_model"] = "auto"
            self.set("codex_model_migrated", True)

    async def on_unload(self):
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
                return permission, title
        return None

    def _is_enabled(self, key):
        rule = self._group_rule(key.split(":", 1)[0])
        return rule[0] == "allow" if rule else key in self.get("enabled", [])

    def _prune_disabled_rounds(self):
        for key in list(self._rounds):
            if not self._is_enabled(key):
                game = self._rounds.pop(key)
                if game.worker:
                    game.worker.cancel()

    def _set_group_rule(self, group_id, permission, title=""):
        rules = [rule for rule in self.config["group_rules"] if rule.split(" | ", 1)[0] != group_id]
        if permission in GROUP_PERMISSIONS:
            rules.append(f"{group_id} | {permission} | {title}")
        self.config["group_rules"] = rules

    async def _group_command(self, message, permission):
        if not message.is_group:
            return "Выполни .contextno group в группе, чтобы узнать её ID и название."
        if permission not in {"", "allow", "deny", "clear"}:
            return "Используй .contextno group allow, deny или clear."
        group_id = str(message.chat_id)
        chat = await message.get_chat()
        title = " ".join((getattr(chat, "title", None) or f"Группа {group_id}").split())
        label = f"{escape(title)} (<code>{group_id}</code>)"
        if permission:
            self._set_group_rule(group_id, permission, title)
            if permission == "clear":
                return f"{label}. Правило удалено. Действуют настройки чата или темы."
            return f"{label}. Во всех темах {GROUP_PERMISSIONS[permission]}."
        rule = self._group_rule(group_id)
        policy = f"Во всех темах {GROUP_PERMISSIONS[rule[0]]}." if rule else "Правила для группы пока нет."
        return f"{label}. {policy}"

    @loader.command()
    async def contextno(self, message):
        """<on|off|status|check|models|groups|group> — управление автоподбором и правилами групп."""
        action = utils.get_args_raw(message).strip().lower() or "status"
        key = chat_key(message)
        group_id = key.split(":", 1)[0]
        if action in {"on", "off"}:
            rule = self._group_rule(group_id)
            if rule:
                permission = "allow" if action == "on" else "deny"
                self._set_group_rule(group_id, permission, rule[1])
                result = f"{escape(rule[1])}. Во всех темах {GROUP_PERMISSIONS[permission]}."
            else:
                enabled = set(self.get("enabled", []))
                if action == "on":
                    enabled.add(key)
                else:
                    enabled.discard(key)
                self.set("enabled", sorted(enabled))
                self._prune_disabled_rounds()
                result = "Автоподбор включён." if action == "on" else "Автоподбор выключен."
        elif action == "groups":
            rules = {}
            for rule in self.config["group_rules"]:
                saved_id, permission, title = rule.split(" | ", 2)
                rules[saved_id] = f"{escape(title)} (<code>{saved_id}</code>) — {GROUP_PERMISSIONS[permission]}"
            result = "\n".join(rules.values()) or "Правил пока нет. Открой .config ContextnoCodex → group_rules."
        elif action == "group" or action.startswith("group "):
            result = await self._group_command(message, action[5:].strip())
        elif action == "status":
            game = self._rounds.get(key)
            result = "Автоподбор включён." if self._is_enabled(key) else "Автоподбор выключен."
            rule = self._group_rule(group_id)
            if rule:
                result += f" {escape(rule[1])} (<code>{group_id}</code>) — {GROUP_PERMISSIONS[rule[0]]}."
            result += f" Порог входа: топ-{self.config['start_rank']}."
            if game and game.best:
                result += f" Лучшее место в топе: {game.best}. Попыток: {len(game.guesses)}."
                if game.last_guess_score:
                    word, rank = game.last_guess_score
                    result += f" Последняя оценённая догадка: {word} ({rank})."
                if game.closed:
                    result += " Раунд завершён."
                if game.last_error:
                    result += f" Последняя ошибка: {game.last_error}"
        elif action == "models":
            result = f"Выбор модели в .config ContextnoCodex → codex_model.\n\n{CODEX_MODELS_HELP}"
        elif action == "check":
            await utils.answer(message, "Проверяю Codex CLI…")
            try:
                loop = asyncio.get_running_loop()
                started = loop.time()
                candidates = await self._suggest({"ближайшие": [["орден", 450], ["медаль", 2200]]})
                word = next((w for w, _, _ in candidates if normalize(w) not in {"орден", "медаль"}), "")
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
        sender = getattr(message, "sender", None) or await message.get_sender()
        if not getattr(sender, "bot", False) or (getattr(sender, "username", None) or "").lower() != BOT:
            return
        if not self._is_enabled(key):
            return

        game = self._rounds.setdefault(key, Round())
        if game.latest_bot_message is None or message.id > game.latest_bot_message.id:
            game.latest_bot_message = message
        if message.id <= game.latest_id:
            return

        text = (message.raw_text or "").strip()
        top = parse_top(text)
        score = SCORE_RE.search(text)
        unknown = UNKNOWN_RE.match(text)
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
        if unknown:
            word = normalize(unknown.group(1))
            game.unknown.add(word)
            if word != game.pending:
                return
            game.pending = ""
            feedback = True
        elif top:
            game.best = min(rank for _, rank in top)
        elif not score:
            return

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
        if (
            self._can_play(game)
            and (top or feedback)
            and not game.worker
        ):
            game.worker = asyncio.create_task(self._play(key, game))

    def _guess_context(self, game, retried):
        ranked = sorted(game.scores.values(), key=lambda item: item[1])
        history = []
        stalled = 0
        role_misses = dict.fromkeys(GUESS_ROLES, 0)
        for word, (theme, role, best_before) in game.guesses.items():
            attempt = {"слово": word, "связь": theme, "роль": role}
            score = game.scores.get(word)
            if score:
                _, rank = score
                if rank < best_before:
                    stalled = 0
                    role_misses = dict.fromkeys(GUESS_ROLES, 0)
                else:
                    stalled += 1
                    role_misses[role] += 1
                history.append({**attempt, "ранг": rank, "лучший_до": best_before})
            elif word in game.unknown:
                history.append({**attempt, "результат": "нет в словаре"})

        best = ranked[0][1]
        role_order = sorted(GUESS_ROLES, key=role_misses.__getitem__)
        if best <= 10:
            strategy = (
                "Сохрани сильнейшую подсказку, но ищи слово, которое объясняет её вместе "
                "с ближайшим словом из другой группы. Не перечисляй подряд синонимы лидера."
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
            "приоритет_ролей": role_order,
            "исключить": sorted(game.guesses.keys() | game.unknown | game.scores.keys()),
        }
        if retried:
            data["повторный_подбор"] = "Предыдущий ответ не содержал новых слов."
        recheck = stalled > 0 and stalled % STALL_ROUNDS == 0
        effort = "medium" if retried or best <= 10 or recheck else "low"
        return data, effort

    async def _play(self, key, game):
        retried = False
        game.last_error = ""
        try:
            while self._is_enabled(key) and self._can_play(game):
                data, effort = self._guess_context(game, retried)
                candidates = await self._suggest(data, effort)
                if self._rounds.get(key) is not game or not self._is_enabled(key) or not self._can_play(game):
                    return
                excluded = game.guesses.keys() | game.unknown | game.scores.keys()
                role_order = data["приоритет_ролей"]
                available = (item for item in candidates if normalize(item[0]) not in excluded)
                candidate = min(available, key=lambda item: role_order.index(item[2]), default=None)
                if candidate is None:
                    if not retried:
                        retried = True
                        continue
                    game.last_error = "Codex дважды не предложил нового слова."
                    return
                retried = False
                guess, theme, role = candidate
                normalized = normalize(guess)
                game.pending = normalized
                best_before = min(rank for _, rank in game.scores.values())
                game.guesses[normalized] = (theme, role, best_before)
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
            if (
                isinstance(word, str) and len(word) <= 40 and WORD_RE.fullmatch(word)
                and isinstance(theme, str) and role in GUESS_ROLES
            ):
                suggestions.append((word, theme.strip()[:80], role))
        return suggestions

