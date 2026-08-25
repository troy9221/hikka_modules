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
from typing import List

from telethon.errors import FloodWaitError
from telethon.tl.types import Message

from .. import loader, utils

logger = logging.getLogger(__name__)

# Traditional / public-domain folk verses only (short couplets).
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


def _find_song(query: str):
    raw = (query or "").strip().lower()
    if not raw:
        return None
    if raw in {"r", "rand", "random", "рандом", "случайная"}:
        return random.choice(SONGS)
    for song in SONGS:
        if raw == song["id"] or raw in song["aliases"]:
            return song
        if raw in song["title"].lower():
            return song
    return None


@loader.tds
class SingMod(loader.Module):
    """Поёт народные песни текстом: правит одно сообщение строка за строкой."""

    strings = {
        "name": "Sing",
        "list": (
            "<b>🎤 Sing</b> — песни текстом\n"
            "<code>.sing</code> список · <code>.sing 1</code> спеть · "
            "<code>.sing random</code> случайная · <code>.singstop</code> стоп\n\n"
            "{}"
        ),
        "item": "<code>{idx}</code> · <b>{title}</b>  <i>{aliases}</i>",
        "unknown": "<b>Нет такой песни.</b> Список: <code>.sing</code>",
        "busy": "<b>Уже пою.</b> Стоп: <code>.singstop</code>",
        "stopped": "<b>🎤 стоп</b>",
        "idle": "<b>Сейчас ничего не пою</b>",
        "done": "★",
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
                "history",
                3,
                "Сколько предыдущих строк оставлять на экране",
                validator=loader.validators.Integer(minimum=1, maximum=8),
            ),
        )

    async def client_ready(self, client, db):
        self._client = client

    def _delay(self, line: str) -> float:
        try:
            base = float(self.config["delay"])
        except (TypeError, ValueError):
            base = 1.8
        base = max(0.8, min(base, 8.0))
        return base + min(1.4, max(0.0, (len(line) - 18) * 0.035))

    def _render(self, title: str, shown: List[str], *, finale: bool = False) -> str:
        history = int(self.config["history"] or 3)
        window = shown[-history:]
        rows = [f"🎤 <b>{utils.escape_html(title)}</b>", ""]
        for i, line in enumerate(window):
            text = utils.escape_html(line)
            if i == len(window) - 1 and not finale:
                rows.append(f"<b>♪ {text}</b>")
            else:
                rows.append(f"<i>{text}</i>")
        if finale:
            rows.append("")
            rows.append(f"<b>{self.strings['done']}</b>")
        return "\n".join(rows)

    async def _edit(self, message: Message, text: str) -> Message:
        try:
            return await utils.answer(message, text) or message
        except FloodWaitError as exc:
            await asyncio.sleep(int(getattr(exc, "seconds", 3)) + 1)
            return await utils.answer(message, text) or message

    async def _sing(self, message: Message, song: dict):
        self._stop = False
        shown: List[str] = []
        msg = await self._edit(
            message,
            f"🎤 <b>{utils.escape_html(song['title'])}</b>\n\n♪ …",
        )
        try:
            for line in song["lines"]:
                if self._stop:
                    await self._edit(msg, self.strings["stopped"])
                    return
                shown.append(line)
                msg = await self._edit(msg, self._render(song["title"], shown))
                await asyncio.sleep(self._delay(line))
            if not self._stop:
                await self._edit(msg, self._render(song["title"], shown, finale=True))
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
        for i, song in enumerate(SONGS, 1):
            aliases = ", ".join(a for a in song["aliases"] if not a.isdigit())
            rows.append(
                self.strings["item"].format(
                    idx=i,
                    title=song["title"],
                    aliases=utils.escape_html(aliases),
                )
            )
        return self.strings["list"].format("\n".join(rows))

    @loader.command()
    async def sing(self, message: Message):
        """[номер|название|random] — спеть песню текстом"""
        args = utils.get_args_raw(message).strip()
        if not args:
            await utils.answer(message, self._list_text())
            return
        song = _find_song(args)
        if not song:
            await utils.answer(message, self.strings["unknown"])
            return
        if self._task and not self._task.done():
            await utils.answer(message, self.strings["busy"])
            return
        self._task = asyncio.create_task(self._sing(message, song))

    @loader.command()
    async def singstop(self, message: Message):
        """Остановить текущую песню"""
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
