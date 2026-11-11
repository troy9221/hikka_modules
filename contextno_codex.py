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
from pathlib import Path

from .. import loader, utils

__version__ = (1, 2, 0)

BOT = "contextno_rf_bot"
TOP_LIMIT = 500
ROUND_ATTEMPTS = 12
CODEX_TIMEOUT = 30
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
    "properties": {"words": {"type": "array", "items": {"type": "string"}}},
    "required": ["words"],
    "additionalProperties": False,
}
PROMPT = (
    "Игра Контекстно: нужно угадать скрытое русское слово по семантическим рангам "
    "проверенных слов. Ранг 1 — разгадка, меньший ранг означает более близкий "
    "контекст употребления. Найди общую тему ближайших слов с учётом далёких попыток. "
    "Верни 3 новых варианта по убыванию вероятности в массиве words. "
    "Каждый вариант — одно слово кириллицей, строчными буквами, в начальной форме. "
    "Исключи проверенные, отправленные и неизвестные словарю слова."
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


@dataclass
class Round:
    latest_id: int = 0
    latest_bot_message: object = None
    best: int = 0
    scores: dict = field(default_factory=dict)
    unknown: set = field(default_factory=set)
    guesses: set = field(default_factory=set)
    pending: str = ""
    closed: bool = False
    worker: object = None


@loader.tds
class ContextnoCodexMod(loader.Module):
    """Играет в Контекстно через Codex CLI после входа в топ-500."""

    strings = {"name": "ContextnoCodex"}

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "codex_bin", "", "Путь к Codex CLI. По умолчанию используется FIRSTCONTACT_CODEX_BIN, PATH или ~/.local/bin.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "codex_model", "auto", CODEX_MODELS_HELP,
                validator=loader.validators.String(min_len=1),
            ),
        )
        self._rounds = {}
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

    @loader.command()
    async def contextno(self, message):
        """<on|off|status|check|models> — управление автоподбором и справка по моделям."""
        action = utils.get_args_raw(message).strip().lower() or "status"
        key = chat_key(message)
        enabled = set(self.get("enabled", []))
        if action in {"on", "off"}:
            if action == "on":
                enabled.add(key)
            else:
                enabled.discard(key)
                game = self._rounds.pop(key, None)
                if game and game.worker:
                    game.worker.cancel()
            self.set("enabled", sorted(enabled))
            result = "Автоподбор включён." if action == "on" else "Автоподбор выключен."
        elif action == "status":
            game = self._rounds.get(key)
            result = "Автоподбор включён." if key in enabled else "Автоподбор выключен."
            if game and game.best:
                result += f" Лучшее место: {game.best}. Попыток: {len(game.guesses)}/{ROUND_ATTEMPTS}."
        elif action == "models":
            result = f"Выбор модели в .config ContextnoCodex → codex_model.\n\n{CODEX_MODELS_HELP}"
        elif action == "check":
            await utils.answer(message, "Проверяю Codex CLI…")
            try:
                loop = asyncio.get_running_loop()
                started = loop.time()
                words = await self._suggest({"ближайшие": [["орден", 450], ["медаль", 2200]]})
                word = next((w for w in words if normalize(w) not in {"орден", "медаль"}), "")
                elapsed = loop.time() - started
                result = (
                    f"Codex CLI ответил за {elapsed:.1f} с. Пример слова: {word}."
                    if word else "Codex не вернул новое слово."
                )
            except CodexError as exc:
                result = str(exc)
        else:
            result = "Используйте .contextno on, off, status, check или models."
        await utils.answer(message, result)

    @loader.watcher("in", "only_messages")
    async def watcher(self, message):
        key = chat_key(message)
        if key not in self.get("enabled", []):
            return
        sender = getattr(message, "sender", None) or await message.get_sender()
        if not getattr(sender, "bot", False) or (getattr(sender, "username", None) or "").lower() != BOT:
            return
        if key not in self.get("enabled", []):
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

        ranks = top + ([ranked_word(score)] if score else [])
        if finished or any(rank == 1 for _, rank in ranks):
            game.latest_id = message.id
            game.closed = True
            if game.worker:
                game.worker.cancel()
            return

        if unknown:
            word = normalize(unknown.group(1))
            game.unknown.add(word)
            if word != game.pending:
                return
            game.pending = ""
        elif top:
            game.best = min(rank for _, rank in top)
        elif not score:
            return

        for word, rank in top:
            game.scores[normalize(word)] = (word, rank)
        if score:
            word, rank = ranked_word(score)
            normalized = normalize(word)
            game.scores.pop(normalized, None)
            game.scores[normalized] = (word, rank)
            if normalized == game.pending:
                game.pending = ""
        game.latest_id = message.id
        if (
            1 < game.best <= TOP_LIMIT
            and len(game.guesses) < ROUND_ATTEMPTS
            and (top or unknown)
            and not game.worker
        ):
            game.worker = asyncio.create_task(self._play(key, game))

    async def _play(self, key, game):
        try:
            while 1 < game.best <= TOP_LIMIT and len(game.guesses) < ROUND_ATTEMPTS:
                revision = game.latest_id
                ranked = sorted(game.scores.values(), key=lambda item: item[1])
                recent = list(game.scores.values())[-20:]
                words = await self._suggest({
                    "ближайшие": ranked[:24],
                    "последние": recent,
                    "уже_отправлены": sorted(game.guesses),
                    "нет_в_словаре": sorted(game.unknown)[-40:],
                })
                if self._rounds.get(key) is not game or game.closed or not 1 < game.best <= TOP_LIMIT:
                    return
                excluded = game.guesses | game.unknown | game.scores.keys()
                guess = next((word for word in words if normalize(word) not in excluded), "")
                if not guess:
                    if revision != game.latest_id:
                        continue
                    return
                game.pending = normalize(guess)
                game.guesses.add(game.pending)
                revision = game.latest_id
                await game.latest_bot_message.reply(guess, parse_mode=None)
                if revision == game.latest_id or game.pending:
                    return
        except CodexError as exc:
            logger.warning("ContextnoCodex: %s", exc)
        except Exception:
            logger.exception("ContextnoCodex: ошибка при отправке слова")
        finally:
            game.worker = None

    async def _suggest(self, data):
        configured = self.config["codex_bin"].strip() or os.environ.get("FIRSTCONTACT_CODEX_BIN", "").strip()
        executable = shutil.which(configured or "codex")
        if not executable and not configured:
            executable = shutil.which(str(Path.home() / ".local" / "bin" / "codex"))
        if not executable:
            raise CodexError("Codex CLI не найден. Укажите codex_bin в .config ContextnoCodex.")
        model = self.config["codex_model"].strip()
        model_args = ["-m", model] if model and model != "auto" else []
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
                        "-c", 'model_reasoning_effort="low"', "--disable", "shell_tool",
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
                    _, stderr = await asyncio.wait_for(process.communicate(prompt), CODEX_TIMEOUT)
                except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
                    if process.returncode is None:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                    await process.wait()
                    if isinstance(exc, asyncio.CancelledError):
                        raise
                    raise CodexError(f"Codex CLI не ответил за {CODEX_TIMEOUT} секунд.") from exc
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
                    words = json.loads(output.read_text(encoding="utf-8"))["words"]
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise CodexError("Codex CLI вернул некорректный ответ.") from exc
        if not isinstance(words, list):
            raise CodexError("Codex CLI вернул некорректный список слов.")
        return [
            word for word in words
            if isinstance(word, str) and len(word) <= 40 and WORD_RE.fullmatch(word)
        ]

