# This file is a part of Lumen / Hikka modules
# https://github.com/troy9221/Lumen_modules
# https://github.com/troy9221/hikka_modules

# meta developer: @LebedKA_SYS
# scope: hikka_min 1.6.0
# scope: lumen_min 0.2.0

import asyncio
import contextlib
import logging
import random
import re
from typing import List

from telethon.errors import FloodWaitError
from telethon.tl.types import Message

from .. import loader, utils

logger = logging.getLogger(__name__)

# Starter public-domain verses only (short couplets).
SONGS = [
    {
        "id": "kalinka",
        "title": "Калинка",
        "aliases": ("калинка", "kalinka", "1"),
        "lines": [
            "Калинка, калинка, калинка моя",
            "В саду ягода малинка, малинка моя",
            "Ах, под сосною, под зелёною",
            "Спать положите вы меня",
            "Калинка, калинка, калинка моя",
            "В саду ягода малинка, малинка моя",
            "Ай-люли, ай-люли",
            "Под сосною, под зелёною",
        ],
    },
    {
        "id": "berioza",
        "title": "Во поле берёза стояла",
        "aliases": ("берёза", "береза", "berioza", "2"),
        "lines": [
            "Во поле берёза стояла",
            "Во поле кудрявая стояла",
            "Люли-люли, стояла",
            "Люли-люли, стояла",
            "Некому берёзу заломати",
            "Некому кудряву заломати",
            "Люли-люли, заломати",
            "Люли-люли, заломати",
        ],
    },
    {
        "id": "moroz",
        "title": "Ой, мороз, мороз",
        "aliases": ("мороз", "moroz", "3"),
        "lines": [
            "Ой, мороз, мороз",
            "Не морозь меня",
            "Не морозь меня",
            "Моего коня",
            "Моего коня",
            "Конь вороненький",
            "Увези меня",
            "В край далёкий",
        ],
    },
    {
        "id": "mesyats",
        "title": "Светит месяц",
        "aliases": ("месяц", "светит", "mesyats", "4"),
        "lines": [
            "Светит месяц, светит ясный",
            "Светит белая луна",
            "Осветила путь-дороженьку",
            "Где любимая была",
            "Выйду ночью за ворота",
            "Погляжу на ту сторонку",
            "Светит месяц, светит ясный",
            "Светит белая луна",
        ],
    },
    {
        "id": "korobeiniki",
        "title": "Коробейники",
        "aliases": ("коробейники", "korobeiniki", "тетра", "5"),
        "lines": [
            "Ой, полна, полна коробушка",
            "Есть и ситцы, и парча",
            "Пожалей, моя зазнобушка",
            "Молодецкого плеча",
            "Выди, выди в рожь высокую",
            "Там до ночки погодим",
            "Обниму я стан твой гибкий",
            "И всю ночку просидим",
        ],
    },
    {
        "id": "razin",
        "title": "Из-за острова на стрежень",
        "aliases": ("разин", "стрежень", "razin", "6"),
        "lines": [
            "Из-за острова на стрежень",
            "На простор речной волны",
            "Выплывают расписные",
            "Острогрудые челны",
            "На переднем Стенька Разин",
            "Обнявшись сидит с княжной",
            "Свадьбу новую справляет",
            "Сам весёлый и хмельной",
        ],
    },
    {
        "id": "kuznitsa",
        "title": "Во кузнице",
        "aliases": ("кузница", "kuznitsa", "7"),
        "lines": [
            "Во кузнице, во кузнице",
            "Кузнец куёт, кузнец куёт",
            "Кузнец куёт коронушку",
            "Невесте на головушку",
            "Ты ковай, ковай, козаченька",
            "Пока жаркая пора",
            "Во кузнице огонь горит",
            "Звенит, звенит там наковальня",
        ],
    },
    {
        "id": "yablochko",
        "title": "Яблочко",
        "aliases": ("яблочко", "yablochko", "8"),
        "lines": [
            "Эх, яблочко, да куда котишься",
            "Ко мне в рот попадёшь — не воротишься",
            "Эх, яблочко, да садовое",
            "Куда катишься, удалое",
            "Яблочко румяное, наливное",
            "Катись по дорожке прямой",
            "Эх, яблочко, да куда котишься",
            "В хороводе нас с тобой не спросишься",
        ],
    },
    {
        "id": "voron",
        "title": "Чёрный ворон",
        "aliases": ("ворон", "voron", "чёрный", "черный", "9"),
        "lines": [
            "Чёрный ворон, что ты вьёшься",
            "Над моею головой",
            "Ты добычи не дождёшься",
            "Чёрный ворон, я не твой",
            "Чёрный ворон, я не твой",
            "Не клюй ты мои очи",
            "Ещё жив я, ворон чёрный",
            "Ещё бьётся сердце в груди",
        ],
    },
    {
        "id": "seni",
        "title": "Ах вы, сени, мои сени",
        "aliases": ("сени", "seni", "ах вы сени", "10"),
        "lines": [
            "Ах вы, сени, мои сени",
            "Сени новые мои",
            "Сени новые, кленовые",
            "Решётчатые",
            "Как и в тех ли во сенях",
            "Во новых, во кленовых",
            "Как ходила-то гуляла",
            "Девица душа",
        ],
    },
]

MAX_CUSTOM_LINES = 40
MAX_CUSTOM_SONGS = 50


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9а-яё]+", "_", (title or "").lower()).strip("_")
    return (slug or "song")[:32]


@loader.tds
class SingMod(loader.Module):
    """Поёт текстом в одном сообщении: одна строка меняется. .sing — список, .sing 1 / название / random — спеть, .singadd — своя песня (реплай на текст), .singdel — удалить свою. Права в конфиге credits, во время песни не показываются."""

    strings = {
        "name": "Sing",
        "list": (
            "<b>🎤 Sing</b> — песни текстом\n"
            "<code>.sing</code> список · <code>.sing 1</code> спеть · "
            "<code>.sing random</code> случайная · <code>.singstop</code> стоп\n"
            "<code>.singadd название</code> реплай на текст · "
            "<code>.singdel номер</code>\n\n"
            "{}"
        ),
        "item": "<code>{idx}</code> · <b>{title}</b>  <i>{aliases}</i>",
        "unknown": "<b>Нет такой песни.</b> Список: <code>.sing</code>",
        "busy": "<b>Уже пою.</b> Стоп: <code>.singstop</code>",
        "stopped": "<b>🎤 стоп</b>",
        "idle": "<b>Сейчас ничего не пою</b>",
        "add_usage": (
            "Реплай на текст песни (каждая строка — куплет):\n"
            "<code>.singadd Название</code>\n"
            "Права на тексты — в конфиге модуля, поле <code>credits</code>."
        ),
        "added": "Добавлено: <b>{}</b> ({} строк). Спеть: <code>.sing {}</code>",
        "no_lines": "<b>Нет текста.</b> Реплай на куплет или допиши строки после названия.",
        "too_many_lines": "<b>Слишком длинно.</b> Максимум {} строк.",
        "too_many_songs": "<b>Слишком много своих песен.</b> Максимум {}. Удали: <code>.singdel</code>",
        "deleted": "Удалено: <b>{}</b>",
        "not_custom": "Встроенные песни удалять нельзя. Только свои: <code>.singdel 11</code>",
        "del_usage": "Удалить свою: <code>.singdel номер</code> или <code>.singdel название</code>",
    }

    def __init__(self):
        self._task = None
        self._stop = False
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "delay",
                1.8,
                "Пауза между строками, секунды",
            ),
            loader.ConfigValue(
                "credits",
                (
                    "Сектор Газа — © правообладатели наследия Ю. Клинских\n"
                    "Король и Шут — © правообладатели\n"
                    "Кино / В. Цой — © правообладатели наследия В. Цоя"
                ),
                "Права на пользовательские тексты. Во время песни не показывается.",
            ),
        )

    async def client_ready(self, client, db):
        self._client = client

    def _custom(self) -> List[dict]:
        raw = self.get("custom", []) or []
        out: List[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            lines = [str(x).strip() for x in (item.get("lines") or []) if str(x).strip()]
            if not title or not lines:
                continue
            aliases = item.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            out.append(
                {
                    "id": str(item.get("id") or _slug(title)),
                    "title": title,
                    "aliases": tuple(str(a) for a in aliases),
                    "lines": lines,
                    "custom": True,
                }
            )
        return out

    def _catalog(self) -> List[dict]:
        return list(SONGS) + self._custom()

    def _save_custom(self, songs: List[dict]) -> None:
        payload = [
            {
                "id": s["id"],
                "title": s["title"],
                "aliases": list(s.get("aliases") or []),
                "lines": list(s["lines"]),
            }
            for s in songs
        ]
        self.set("custom", payload)

    def _find_song(self, query: str):
        catalog = self._catalog()
        raw = (query or "").strip().lower()
        if not raw:
            return None
        if raw in {"r", "rand", "random", "рандом", "случайная"}:
            return random.choice(catalog) if catalog else None
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(catalog):
                return catalog[idx - 1]
        for song in catalog:
            aliases = song.get("aliases") or ()
            if raw == str(song.get("id", "")).lower() or raw in {str(a).lower() for a in aliases}:
                return song
            if raw in song["title"].lower():
                return song
        return None

    def _parse_lyrics(self, message: Message, raw: str):
        title = (raw or "").strip()
        lines: List[str] = []
        if "\n" in title:
            head, rest = title.split("\n", 1)
            title = head.strip()
            lines = [ln.strip() for ln in rest.splitlines() if ln.strip()]
        return title, lines

    def _delay(self, line: str) -> float:
        try:
            base = float(self.config["delay"])
        except (TypeError, ValueError):
            base = 1.8
        base = max(0.8, min(base, 8.0))
        return base + min(1.4, max(0.0, (len(line) - 18) * 0.035))

    def _render(self, line: str) -> str:
        return f"<b>♪ {utils.escape_html(line)}</b>"

    async def _edit(self, message: Message, text: str) -> Message:
        try:
            return await utils.answer(message, text) or message
        except FloodWaitError as exc:
            await asyncio.sleep(int(getattr(exc, "seconds", 3)) + 1)
            return await utils.answer(message, text) or message

    async def _sing(self, message: Message, song: dict):
        self._stop = False
        msg = await self._edit(message, "♪ …")
        try:
            for line in song["lines"]:
                if self._stop:
                    await self._edit(msg, self.strings["stopped"])
                    return
                msg = await self._edit(msg, self._render(line))
                await asyncio.sleep(self._delay(line))
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await self._edit(msg, self.strings["stopped"])
            raise
        except Exception:
            logger.exception("sing failed")
        finally:
            self._task = None

    def _list_text(self) -> str:
        rows = []
        for i, song in enumerate(self._catalog(), 1):
            aliases = ", ".join(a for a in (song.get("aliases") or ()) if not str(a).isdigit())
            mark = " · своя" if song.get("custom") else ""
            rows.append(
                self.strings["item"].format(
                    idx=i,
                    title=utils.escape_html(song["title"]) + mark,
                    aliases=utils.escape_html(aliases),
                )
            )
        return self.strings["list"].format("\n".join(rows))

    @loader.command(
        ru_doc="без аргументов — список; номер, название или random — спеть (одна строка на экране)",
    )
    async def sing(self, message: Message):
        """без аргументов — список; номер, название или random — спеть (одна строка на экране)"""
        args = utils.get_args_raw(message).strip()
        if not args:
            await utils.answer(message, self._list_text())
            return
        song = self._find_song(args)
        if not song:
            await utils.answer(message, self.strings["unknown"])
            return
        if self._task and not self._task.done():
            await utils.answer(message, self.strings["busy"])
            return
        self._task = asyncio.create_task(self._sing(message, song))

    @loader.command(
        ru_doc="<название> — добавить свою песню: реплай на текст или строки ниже названия",
    )
    async def singadd(self, message: Message):
        """<название> — добавить свою песню: реплай на текст или строки ниже названия"""
        raw = utils.get_args_raw(message)
        title, lines = self._parse_lyrics(message, raw)
        reply = await message.get_reply_message()
        if reply and getattr(reply, "raw_text", None) and not lines:
            lines = [ln.strip() for ln in reply.raw_text.splitlines() if ln.strip()]
        if not title:
            await utils.answer(message, self.strings["add_usage"])
            return
        if not lines:
            await utils.answer(message, self.strings["no_lines"])
            return
        if len(lines) > MAX_CUSTOM_LINES:
            await utils.answer(message, self.strings["too_many_lines"].format(MAX_CUSTOM_LINES))
            return
        custom = self._custom()
        if len(custom) >= MAX_CUSTOM_SONGS:
            await utils.answer(message, self.strings["too_many_songs"].format(MAX_CUSTOM_SONGS))
            return
        song_id = _slug(title)
        existing_ids = {s["id"] for s in custom}
        if song_id in existing_ids or any(s["id"] == song_id for s in SONGS):
            n = 2
            while f"{song_id}_{n}" in existing_ids:
                n += 1
            song_id = f"{song_id}_{n}"
        custom.append(
            {
                "id": song_id,
                "title": title,
                "aliases": (title.lower(), song_id),
                "lines": lines,
            }
        )
        self._save_custom(custom)
        idx = len(SONGS) + len(custom)
        await utils.answer(
            message,
            self.strings["added"].format(
                utils.escape_html(title),
                len(lines),
                idx,
            ),
        )

    @loader.command(
        ru_doc="<номер или название> — удалить свою песню (встроенные нельзя)",
    )
    async def singdel(self, message: Message):
        """<номер или название> — удалить свою песню (встроенные нельзя)"""
        args = utils.get_args_raw(message).strip()
        if not args:
            await utils.answer(message, self.strings["del_usage"])
            return
        song = self._find_song(args)
        if not song:
            await utils.answer(message, self.strings["unknown"])
            return
        if not song.get("custom"):
            await utils.answer(message, self.strings["not_custom"])
            return
        custom = [s for s in self._custom() if s["id"] != song["id"]]
        self._save_custom(custom)
        await utils.answer(message, self.strings["deleted"].format(utils.escape_html(song["title"])))

    @loader.command(ru_doc="остановить текущую песню")
    async def singstop(self, message: Message):
        """остановить текущую песню"""
        if not self._task or self._task.done():
            await utils.answer(message, self.strings["idle"])
            return
        self._stop = True
        await utils.answer(message, self.strings["stopped"])

    async def on_unload(self):
        self._stop = True
        task = self._task
        if task and not task.done():
            task.cancel()
