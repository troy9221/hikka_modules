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
from typing import Dict, List, Optional, Sequence, Tuple

from telethon.errors import FloodWaitError
from telethon.tl.types import Message

from .. import loader, utils

logger = logging.getLogger(__name__)

# Public-domain / traditional couplets only. Copyrighted rap, rock and pop stay out of the repo.
GENRE_LABELS = {
    "folk": "Народные",
    "romance": "Романсы",
    "shanty": "Шанти",
    "blues": "Блюз",
    "gospel": "Спиричуэлс",
    "country": "Кантри",
    "oldpop": "Старые хиты",
    "ballad": "Баллады",
    "custom": "Свои",
}
GENRE_ORDER = (
    "folk",
    "romance",
    "shanty",
    "blues",
    "gospel",
    "country",
    "oldpop",
    "ballad",
    "custom",
)
GENRE_ALIASES: Dict[str, Tuple[str, ...]] = {
    "folk": ("народные", "народ", "folk", "фолк"),
    "romance": ("романсы", "романс", "romance"),
    "shanty": ("шанти", "shanty", "море"),
    "blues": ("блюз", "blues"),
    "gospel": ("спиричуэлс", "gospel", "госпел", "духовные"),
    "country": ("кантри", "country", "ковбой"),
    "oldpop": ("хиты", "oldies", "эстрада"),
    "ballad": ("баллады", "баллада", "ballad"),
}
ROCK_GENRES = ("shanty", "blues", "ballad")
ROCK_QUERIES = {"рок", "rock"}
RAP_QUERIES = {"рэп", "rap", "хип-хоп", "хипхоп", "hiphop", "hip-hop", "hip hop"}

SONGS = [
    {
        "id": "kalinka",
        "title": "Калинка",
        "genre": "folk",
        "aliases": ("калинка", "kalinka"),
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
        "genre": "folk",
        "aliases": ("берёза", "береза", "berioza"),
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
        "genre": "folk",
        "aliases": ("мороз", "moroz"),
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
        "genre": "folk",
        "aliases": ("месяц", "светит", "mesyats"),
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
        "genre": "folk",
        "aliases": ("коробейники", "korobeiniki", "тетра"),
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
        "genre": "folk",
        "aliases": ("разин", "стрежень", "razin"),
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
        "genre": "folk",
        "aliases": ("кузница", "kuznitsa"),
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
        "genre": "folk",
        "aliases": ("яблочко", "yablochko"),
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
        "genre": "folk",
        "aliases": ("ворон", "voron", "чёрный", "черный"),
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
        "genre": "folk",
        "aliases": ("сени", "seni", "ах вы сени"),
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
    {
        "id": "sad",
        "title": "Во саду ли в огороде",
        "genre": "folk",
        "aliases": ("сад", "огород", "вишенка"),
        "lines": [
            "Во саду ли в огороде",
            "Вишенка росла",
            "Во саду ли в огороде",
            "Вишенка росла",
            "Разрезвилася девица",
            "Душа красная",
            "Разрезвилася девица",
            "Душа красная",
        ],
    },
    {
        "id": "valenki",
        "title": "Валенки",
        "genre": "folk",
        "aliases": ("валенки", "valenki"),
        "lines": [
            "Валенки, валенки",
            "Эх, неподшиты, стареньки",
            "Нельзя валенки носить",
            "Не в чем к милому ходить",
            "Валенки, валенки",
            "Эх, неподшиты, стареньки",
            "Нельзя валенки носить",
            "Не в чем к милому ходить",
        ],
    },
    {
        "id": "dubinushka",
        "title": "Дубинушка",
        "genre": "folk",
        "aliases": ("дубинушка", "ухнем", "dubinushka"),
        "lines": [
            "Эх, дубинушка, ухнем",
            "Эх, зелёная, сама пойдёт",
            "Потянем мы дубину",
            "Сам пойдёт, сам пойдёт",
            "Ай-да ухнем",
            "Ай-да ухнем",
            "Ещё разик, ещё раз",
            "Ещё разик, ещё раз",
        ],
    },
    {
        "id": "rechka",
        "title": "Вдоль да по речке",
        "genre": "folk",
        "aliases": ("речке", "казанке", "селезень"),
        "lines": [
            "Вдоль да по речке",
            "Вдоль да по Казанке",
            "Сизый селезень плывёт",
            "Сизый селезень плывёт",
            "Вдоль да по бережку",
            "Вдоль да по крутому",
            "Добрый молодец идёт",
            "Добрый молодец идёт",
        ],
    },
    {
        "id": "to_ne_vecher",
        "title": "Ой, то не вечер",
        "genre": "folk",
        "aliases": ("то не вечер", "казачья", "вечер"),
        "lines": [
            "Ой, то не вечер, то не вечер",
            "Мне малым-мало спалось",
            "Мне малым-мало спалось",
            "Мне много во сне виделось",
            "Мне много во сне виделось",
            "Ой, то не вечер, то не вечер",
            "Мне малым-мало спалось",
            "Мне много во сне виделось",
        ],
    },
    {
        "id": "step",
        "title": "Степь да степь кругом",
        "genre": "folk",
        "aliases": ("степь", "ямщик", "step"),
        "lines": [
            "Степь да степь кругом",
            "Путь далёк лежит",
            "В той степи глухой",
            "Ямщик замирает",
            "Степь да степь кругом",
            "Путь далёк лежит",
            "Колокольчик однозвучный",
            "Уныло гремит",
        ],
    },
    {
        "id": "zabaykalye",
        "title": "По диким степям Забайкалья",
        "genre": "folk",
        "aliases": ("забайкалья", "бродяга", "zabaykalye"),
        "lines": [
            "По диким степям Забайкалья",
            "Где золото роют в горах",
            "Бродяга, судьба несчастная",
            "Таскает кандалы в горах",
            "По диким степям Забайкалья",
            "Где золото роют в горах",
            "Бродяга, судьба несчастная",
            "Таскает кандалы в горах",
        ],
    },
    {
        "id": "ochi",
        "title": "Очи чёрные",
        "genre": "romance",
        "aliases": ("очи", "чёрные", "черные", "ochi"),
        "lines": [
            "Очи чёрные, очи страстные",
            "Очи жгучие и прекрасные",
            "Как люблю я вас",
            "Как боюсь я вас",
            "Знать, увидел вас",
            "В недобрый час",
            "Очи чёрные, очи страстные",
            "Очи жгучие и прекрасные",
        ],
    },
    {
        "id": "ryabina",
        "title": "Тонкая рябина",
        "genre": "romance",
        "aliases": ("рябина", "рябина тонкая", "ryabina"),
        "lines": [
            "Что стоишь, качаясь",
            "Тонкая рябина",
            "Головой склоняясь",
            "До самого тына",
            "А через дорогу",
            "За рекой широкой",
            "Так же одиноко",
            "Дуб стоит высокий",
        ],
    },
    {
        "id": "two_guitars",
        "title": "Две гитары",
        "genre": "romance",
        "aliases": ("гитары", "две гитары"),
        "lines": [
            "Две гитары за стеною",
            "Жалобно заныли",
            "С детства памятный мотив",
            "Мне вы навеяли",
            "Две гитары, зазвенев",
            "Жалобно заныли",
            "С детства памятный мотив",
            "Мне вы навеяли",
        ],
    },
    {
        "id": "drunken_sailor",
        "title": "Drunken Sailor",
        "genre": "shanty",
        "aliases": ("drunken", "sailor", "пьяный матрос"),
        "lines": [
            "What shall we do with a drunken sailor",
            "What shall we do with a drunken sailor",
            "What shall we do with a drunken sailor",
            "Early in the morning",
            "Way hay and up she rises",
            "Way hay and up she rises",
            "Way hay and up she rises",
            "Early in the morning",
        ],
    },
    {
        "id": "blow_the_man_down",
        "title": "Blow the Man Down",
        "genre": "shanty",
        "aliases": ("blow", "man down"),
        "lines": [
            "I'll sing you a song, a good song of the sea",
            "With a way, hey, blow the man down",
            "And trust that you'll join in the chorus with me",
            "Give me some time to blow the man down",
            "Way, hey, blow the man down",
            "Give me some time to blow the man down",
        ],
    },
    {
        "id": "spanish_ladies",
        "title": "Spanish Ladies",
        "genre": "shanty",
        "aliases": ("spanish ladies", "ladies"),
        "lines": [
            "Farewell and adieu to you, Spanish ladies",
            "Farewell and adieu to you, ladies of Spain",
            "For we've received orders to sail for old England",
            "And we hope in a short time to see you again",
            "We'll rant and we'll roar like true British sailors",
            "We'll rant and we'll roar all on the salt sea",
        ],
    },
    {
        "id": "rising_sun",
        "title": "House of the Rising Sun",
        "genre": "blues",
        "aliases": ("rising sun", "new orleans", "house of the"),
        "lines": [
            "There is a house in New Orleans",
            "They call the Rising Sun",
            "And it's been the ruin of many a poor boy",
            "And God, I know I'm one",
            "My mother was a tailor",
            "She sewed my new blue jeans",
            "My father was a gamblin' man",
            "Down in New Orleans",
        ],
    },
    {
        "id": "st_james",
        "title": "St. James Infirmary",
        "genre": "blues",
        "aliases": ("st james", "infirmary", "saint james"),
        "lines": [
            "I went down to St. James Infirmary",
            "I saw my baby there",
            "Stretched out on a long white table",
            "So sweet, so cold, so fair",
            "Let her go, let her go, God bless her",
            "Wherever she may be",
            "She can search this whole wide world over",
            "She'll never find another like me",
        ],
    },
    {
        "id": "careless_love",
        "title": "Careless Love",
        "genre": "blues",
        "aliases": ("careless", "careless love"),
        "lines": [
            "Love, oh love, oh careless love",
            "Love, oh love, oh careless love",
            "Love, oh love, oh careless love",
            "See what careless love has done",
            "I love my mama and papa too",
            "I love my mama and papa too",
            "I love my mama and papa too",
            "I'd leave them both to go with you",
        ],
    },
    {
        "id": "amazing_grace",
        "title": "Amazing Grace",
        "genre": "gospel",
        "aliases": ("amazing", "grace", "амазинг"),
        "lines": [
            "Amazing grace, how sweet the sound",
            "That saved a wretch like me",
            "I once was lost, but now am found",
            "Was blind, but now I see",
            "'Twas grace that taught my heart to fear",
            "And grace my fears relieved",
            "How precious did that grace appear",
            "The hour I first believed",
        ],
    },
    {
        "id": "saints",
        "title": "When the Saints Go Marching In",
        "genre": "gospel",
        "aliases": ("saints", "marching", "святые"),
        "lines": [
            "Oh when the saints go marching in",
            "Oh when the saints go marching in",
            "Lord, I want to be in that number",
            "When the saints go marching in",
            "Oh when the sun refuse to shine",
            "Oh when the sun refuse to shine",
            "Lord, I want to be in that number",
            "When the sun refuse to shine",
        ],
    },
    {
        "id": "swing_low",
        "title": "Swing Low, Sweet Chariot",
        "genre": "gospel",
        "aliases": ("swing low", "chariot", "колесница"),
        "lines": [
            "Swing low, sweet chariot",
            "Coming for to carry me home",
            "Swing low, sweet chariot",
            "Coming for to carry me home",
            "I looked over Jordan, and what did I see",
            "Coming for to carry me home",
            "A band of angels coming after me",
            "Coming for to carry me home",
        ],
    },
    {
        "id": "home_on_the_range",
        "title": "Home on the Range",
        "genre": "country",
        "aliases": ("home on the range", "buffalo", "range"),
        "lines": [
            "Oh give me a home where the buffalo roam",
            "Where the deer and the antelope play",
            "Where seldom is heard a discouraging word",
            "And the skies are not cloudy all day",
            "Home, home on the range",
            "Where the deer and the antelope play",
            "Where seldom is heard a discouraging word",
            "And the skies are not cloudy all day",
        ],
    },
    {
        "id": "clementine",
        "title": "Oh My Darling Clementine",
        "genre": "country",
        "aliases": ("clementine", "клементин"),
        "lines": [
            "In a cavern, in a canyon",
            "Excavating for a mine",
            "Dwelt a miner forty-niner",
            "And his daughter Clementine",
            "Oh my darling, oh my darling",
            "Oh my darling Clementine",
            "You are lost and gone forever",
            "Dreadful sorry, Clementine",
        ],
    },
    {
        "id": "red_river",
        "title": "Red River Valley",
        "genre": "country",
        "aliases": ("red river", "valley"),
        "lines": [
            "From this valley they say you are going",
            "We will miss your bright eyes and sweet smile",
            "For they say you are taking the sunshine",
            "That has brightened our pathway a while",
            "Come and sit by my side if you love me",
            "Do not hasten to bid me adieu",
            "But remember the Red River Valley",
            "And the one that has loved you so true",
        ],
    },
    {
        "id": "oh_susanna",
        "title": "Oh! Susanna",
        "genre": "oldpop",
        "aliases": ("susanna", "сьюзанна", "alabama"),
        "lines": [
            "I come from Alabama with a banjo on my knee",
            "I'm going to Louisiana, my true love for to see",
            "It rained all night the day I left",
            "The weather it was dry",
            "Oh, Susanna, oh don't you cry for me",
            "For I come from Alabama with a banjo on my knee",
        ],
    },
    {
        "id": "jingle_bells",
        "title": "Jingle Bells",
        "genre": "oldpop",
        "aliases": ("jingle", "колокольчики", "sleigh"),
        "lines": [
            "Dashing through the snow",
            "In a one-horse open sleigh",
            "O'er the fields we go",
            "Laughing all the way",
            "Jingle bells, jingle bells",
            "Jingle all the way",
            "Oh what fun it is to ride",
            "In a one-horse open sleigh",
        ],
    },
    {
        "id": "auld_lang_syne",
        "title": "Auld Lang Syne",
        "genre": "oldpop",
        "aliases": ("auld lang syne", "олд ланг", "syne"),
        "lines": [
            "Should auld acquaintance be forgot",
            "And never brought to mind",
            "Should auld acquaintance be forgot",
            "And auld lang syne",
            "For auld lang syne, my dear",
            "For auld lang syne",
            "We'll take a cup of kindness yet",
            "For auld lang syne",
        ],
    },
    {
        "id": "scarborough",
        "title": "Scarborough Fair",
        "genre": "oldpop",
        "aliases": ("scarborough", "parsley", "скарборо"),
        "lines": [
            "Are you going to Scarborough Fair",
            "Parsley, sage, rosemary and thyme",
            "Remember me to one who lives there",
            "She once was a true love of mine",
            "Tell her to make me a cambric shirt",
            "Parsley, sage, rosemary and thyme",
            "Without no seams nor needle work",
            "Then she'll be a true love of mine",
        ],
    },
    {
        "id": "cucaracha",
        "title": "La Cucaracha",
        "genre": "oldpop",
        "aliases": ("cucaracha", "таракан"),
        "lines": [
            "La cucaracha, la cucaracha",
            "Ya no puede caminar",
            "Porque no tiene, porque le falta",
            "Las patitas de atrás",
            "La cucaracha, la cucaracha",
            "Ya no puede caminar",
            "Porque no tiene, porque le falta",
            "Las patitas de atrás",
        ],
    },
    {
        "id": "john_henry",
        "title": "John Henry",
        "genre": "ballad",
        "aliases": ("john henry", "steel", "джон генри"),
        "lines": [
            "John Henry was a steel-driving man",
            "Lord, Lord",
            "John Henry was a steel-driving man",
            "He hammered on the mountain",
            "Till his hammer caught on fire",
            "John Henry was a steel-driving man",
            "Lord, Lord",
            "John Henry was a steel-driving man",
        ],
    },
]

MAX_CUSTOM_LINES = 80
MAX_CUSTOM_SONGS = 50


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9а-яё]+", "_", (title or "").lower()).strip("_")
    return (slug or "song")[:32]


def _genre_of(song: dict) -> str:
    if song.get("custom"):
        return "custom"
    genre = str(song.get("genre") or "folk")
    return genre if genre in GENRE_LABELS else "folk"


def _match_genre(query: str) -> Optional[str]:
    raw = (query or "").strip().lower()
    if not raw:
        return None
    for genre, aliases in GENRE_ALIASES.items():
        if raw == genre or raw in aliases:
            return genre
    return None


@loader.tds
class SingMod(loader.Module):
    """Поёт текстом в одном сообщении: одна строка меняется. .sing — список, .sing 1 / название / жанр / random — спеть, .singadd — своя песня, .singdel — удалить свою. Рэп, рок, поп — только .singadd."""

    strings = {
        "name": "Sing",
        "list": (
            "<b>🎤 Sing</b> — песни текстом\n"
            "В комплекте народные, романсы, шанти, блюз, спиричуэлс, кантри, старые хиты.\n"
            "Рэп, рок, поп — <code>.singadd</code>\n"
            "<code>.sing 1</code> · <code>.sing блюз</code> · <code>.sing random</code> · "
            "<code>.singstop</code>\n\n"
            "{}"
        ),
        "group": "\n<b>{label}</b>",
        "item": "<code>{idx}</code> · {title}",
        "unknown": "<b>Нет такой песни.</b> Список: <code>.sing</code>",
        "busy": "<b>Уже пою.</b> Стоп: <code>.singstop</code>",
        "stopped": "<b>🎤 стоп</b>",
        "idle": "<b>Сейчас ничего не пою</b>",
        "no_rap": (
            "<b>Популярный рэп в комплект нельзя</b> (копирайт).\n"
            "Добавь свой текст: реплай на куплет и <code>.singadd Название</code>"
        ),
        "no_genre": "<b>В этом жанре пока пусто.</b> Список: <code>.sing</code>",
        "add_usage": (
            "Как добавить свою песню (текст остаётся только у тебя):\n"
            "1) Отправь куплет сообщением или .txt-файлом — каждая строка отдельный такт\n"
            "2) Реплай: <code>.singadd Название</code>\n\n"
            "Рэп, рок, поп, Кино, КиШ, Сектор Газа — только так.\n"
            "Права — поле <code>credits</code> в конфиге, во время песни не показываются."
        ),
        "added": "Добавлено: <b>{}</b> ({} строк). Спеть: <code>.sing {}</code>",
        "no_lines": "<b>Нет текста.</b> Реплай на куплет или допиши строки после названия.",
        "too_many_lines": "<b>Слишком длинно.</b> Максимум {} строк.",
        "too_many_songs": "<b>Слишком много своих песен.</b> Максимум {}. Удали: <code>.singdel</code>",
        "deleted": "Удалено: <b>{}</b>",
        "not_custom": "Встроенные песни удалять нельзя. Только свои: <code>.singdel название</code>",
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
                    "genre": "custom",
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

    def _by_genre(self, genre: str, catalog: Optional[Sequence[dict]] = None) -> List[dict]:
        source = list(catalog) if catalog is not None else self._catalog()
        return [song for song in source if _genre_of(song) == genre]

    def _find_song(self, query: str):
        catalog = self._catalog()
        raw = (query or "").strip().lower()
        if not raw:
            return None
        if raw in {"r", "rand", "random", "рандом", "случайная"}:
            return random.choice(catalog) if catalog else None
        if raw in ROCK_QUERIES:
            pool = [song for song in SONGS if song.get("genre") in ROCK_GENRES]
            return random.choice(pool) if pool else None
        genre = _match_genre(raw)
        if genre:
            pool = self._by_genre(genre, catalog)
            return random.choice(pool) if pool else None
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

    async def _lines_from_reply(self, reply: Message) -> List[str]:
        if not reply:
            return []
        text = getattr(reply, "raw_text", None) or ""
        if text.strip():
            return [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not getattr(reply, "document", None):
            return []
        try:
            data = await reply.download_media(bytes)
        except Exception:
            return []
        if not data:
            return []
        try:
            body = data.decode("utf-8")
        except UnicodeDecodeError:
            body = data.decode("cp1251", errors="replace")
        return [ln.strip() for ln in body.splitlines() if ln.strip()]

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
        catalog = self._catalog()
        rows: List[str] = []
        seen_groups = set()
        for i, song in enumerate(catalog, 1):
            genre = _genre_of(song)
            if genre not in seen_groups:
                seen_groups.add(genre)
                rows.append(
                    self.strings["group"].format(
                        label=utils.escape_html(GENRE_LABELS.get(genre, genre))
                    )
                )
            mark = " · своя" if song.get("custom") else ""
            rows.append(
                self.strings["item"].format(
                    idx=i,
                    title=utils.escape_html(song["title"]) + mark,
                )
            )
        return self.strings["list"].format("\n".join(rows).strip())

    @loader.command(
        ru_doc="без аргументов — список; номер, название, жанр (блюз/рок) или random — спеть",
    )
    async def sing(self, message: Message):
        """без аргументов — список; номер, название, жанр (блюз/рок) или random — спеть"""
        args = utils.get_args_raw(message).strip()
        if not args:
            await utils.answer(message, self._list_text())
            return
        if args.lower() in RAP_QUERIES:
            await utils.answer(message, self.strings["no_rap"])
            return
        song = self._find_song(args)
        if not song:
            if _match_genre(args) or args.lower() in ROCK_QUERIES:
                await utils.answer(message, self.strings["no_genre"])
                return
            await utils.answer(message, self.strings["unknown"])
            return
        if self._task and not self._task.done():
            await utils.answer(message, self.strings["busy"])
            return
        self._task = asyncio.create_task(self._sing(message, song))

    @loader.command(
        ru_doc="<название> — своя песня: реплай на текст или .txt, либо строки ниже названия",
    )
    async def singadd(self, message: Message):
        """<название> — своя песня: реплай на текст или .txt, либо строки ниже названия"""
        raw = utils.get_args_raw(message)
        title, lines = self._parse_lyrics(message, raw)
        if not lines:
            lines = await self._lines_from_reply(await message.get_reply_message())
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
