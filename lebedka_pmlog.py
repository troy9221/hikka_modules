
#
# 🔒 Licensed under the GNU GPLv3
# 🌐 https://www.gnu.org/licenses/gpl-3.0.html

# meta developer: @LebedKA_SYS
# meta banner: https://t.me/LebedKA_SYS/11
# meta pic: https://t.me/LebedKA_SYS/13
# meta repo: https://github.com/troy9221/hikka_modules

# scope: hikka_only
# scope: hikka_min 1.3.3

import contextlib
import logging
from datetime import datetime
from io import BytesIO

from telethon.errors import MessageIdInvalidError
from telethon.tl.types import Message, User

from telethon.tl.functions.messages import (
    ReadDiscussionRequest,
)
from telethon.tl.functions.channels import (
    GetForumTopicsRequest,
    CreateForumTopicRequest,
    ToggleForumRequest,
    EditForumTopicRequest,
)

from .. import loader, utils

logger = logging.getLogger(__name__)


@loader.tds
class LebedKAPMLogMod(loader.Module):
    """
    Logs PMs to a group/channel
    """

    strings = {
        "name": "LebedKA-PMLog",
        "developer": "@LebedKA_SYS",
        "_cfg_bots": "Whether to log bots or not.",
        "_cfg_loglist": "Add telegram id's to log them.",
        "_cfg_selfdestructive": (
            "Whether selfdestructive media should be logged or not. This"
            " violates TG TOS!"
        ),
        "_cfg_whitelist": (
            "Whether the list is a for excluded(True) or included(False) chats."
        ),
        "_cfg_realtime_usernames": "Whether to update the topic names in realtime or not.",
        "_cfg_mark_read": "Whether to mark the messages in the log as read or not.",
    }

    strings_en = {}

    strings_de = {
        "_cfg_bots": "Ob Bots geloggt werden sollen oder nicht.",
        "_cfg_loglist": "Fügen Sie Telegram-IDs hinzu, um sie zu protokollieren.",
        "_cfg_selfdestructive": (
            "Ob selbstzerstörende Medien geloggt werden sollen oder nicht. Dies"
            " verstößt gegen die TG TOS!"
        ),
        "_cfg_whitelist": (
            "Ob die Liste für ausgeschlossene (Wahr) oder eingeschlossene"
            " (Falsch) Chats ist."
        ),
        "_cmd_doc_cpmlog": "Dadurch wird die Konfiguration für das Modul geöffnet.",
    }

    strings_ru = {
        "_cfg_bots": "Логировать ли ботов или нет",
        "_cfg_loglist": "Добавьте айди Telegram, чтобы зарегистрировать их",
        "_cfg_selfdestructive": (
            "Должны ли самоуничтожающиеся медиафайлы регистрироваться или нет."
            " Это нарушает «Условия использования Telegram» (ToS)"
        ),
        "_cfg_whitelist": "Использовать белый список (True) или черный (False).",
        "_cmd_doc_cpmlog": "Это откроет конфиг для модуля.",
    }

    all_strings = {
        "strings": strings,
        "strings_en": strings,
        "strings_de": strings_de,
        "strings_ru": strings_ru,
    }

    # Old module names that should be migrated to the current one
    _old_names = ["Apo PMLogger", "Apo-PMLog"]

    def __init__(self):
        self._ratelimit = []
        self._topic_cache = {}
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "log_bots",
                False,
                doc=lambda: self.strings("_cfg_bots"),
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "log_list",
                [777000],
                doc=lambda: self.strings("_cfg_loglist"),
                validator=loader.validators.Series(
                    validator=loader.validators.TelegramID()
                ),
            ),
            loader.ConfigValue(
                "log_self_destr",
                False,
                doc=lambda: self.strings("_cfg_selfdestructive"),
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "realtime_names",
                True,
                doc=lambda: self.strings("_cfg_realtime_usernames"),
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "whitelist",
                True,
                doc=lambda: self.strings("_cfg_whitelist"),
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "mark_read",
                True,
                doc=lambda: self.strings("_cfg_mark_read"),
                validator=loader.validators.Boolean(),
            ),
        )

    async def client_ready(self):
        self._topic_cache = {}
        self.c, _ = await utils.asset_channel(
            self._client,
            "[LebedKA] PMLog",
            "Chat for logged PMs. The ID's in the topic titles are the user ID's, don't remove them!",
            silent=True,
            invite_bot=False,
        )
        if not self.c.forum:
            await self._client(ToggleForumRequest(self.c.id, True))

    async def cpmlogcmd(self, message: Message):
        """
        This will open the config for the module.
        """
        name = self.strings("name")
        await self.allmodules.commands["config"](
            await utils.answer(message, f"{self.get_prefix()}config {name}")
        )

    async def _topic_cacher(self, user: User):
        if user.id not in self._topic_cache:
            forum = await self._client(
                GetForumTopicsRequest(
                    channel=self.c.id,
                    offset_date=datetime.now(),
                    offset_id=0,
                    offset_topic=0,
                    limit=100,
                )
            )
            for topic in forum.topics:
                if str(user.id) in topic.title:
                    self._topic_cache[user.id] = topic
                    break
        return user.id in self._topic_cache

    async def _topic_creator(self, user: User):
        await self._client(
            CreateForumTopicRequest(
                channel=self.c.id,
                title=f"{user.first_name} ({user.id})",
                icon_color=42,
            )
        )
        return await self._topic_cacher(user)

    async def _topic_handler(self, user: User, message: Message):
        if not await self._topic_cacher(user):  # create topic if not exists
            await self._topic_creator(user)
        new_title = f"{user.first_name} ({user.id})"
        if (
            self.config["realtime_names"]
            and self._topic_cache[user.id].title != new_title
        ):
            old_title = self._topic_cache[user.id].title
            await self._client(
                EditForumTopicRequest(
                    channel=self.c.id,
                    topic_id=self._topic_cache[user.id].id,
                    title=new_title,
                )
            )
            self._topic_cache[user.id].title = new_title
            await message.client.send_message(
                self.c.id,
                f"New name:\n<code>{new_title}</code>\n\nOld name:\n<code>{old_title}</code>",
                reply_to=self._topic_cache[user.id].id,
            )
        return True

    @staticmethod
    def _is_self_destructive(message: Message) -> bool:
        """
        Returns True if the message contains self-destructive (TTL) media
        or is itself a self-destructive message (e.g. secret chat ttl_seconds).
        """
        media = getattr(message, "media", None)
        if media is not None and getattr(media, "ttl_seconds", None):
            return True
        if getattr(message, "ttl_seconds", None):
            return True
        return False

    async def _mark_topic_read(self, msg: Message):
        """Marks the forwarded message's topic as read in the log chat."""
        if not self.config["mark_read"]:
            return
        reply_to = getattr(msg, "reply_to", None)
        read_max_id = getattr(
            reply_to,
            "reply_to_top_id",
            None,
        ) or getattr(
            reply_to,
            "reply_to_msg_id",
            None,
        )
        if read_max_id is None:
            return
        await self._client(
            ReadDiscussionRequest(
                self.c.id,
                read_max_id,
                2**31 - 1,
            )
        )

    async def _save_self_destructive(self, user: User, message: Message):
        """
        Downloads self-destructive media and sends it to the log chat as a
        regular document (without TTL), so it won't disappear from the log.
        Also handles self-destructive text-only messages.
        """
        topic_id = self._topic_cache[user.id].id
        ttl = (
            getattr(getattr(message, "media", None), "ttl_seconds", None)
            or getattr(message, "ttl_seconds", None)
            or 0
        )
        header = (
            f"🔥 <b>Self-destructive message</b> (TTL: <code>{ttl}s</code>)\n"
        )

        if message.file:
            file = BytesIO()
            await self._client.download_file(message, file)
            file.name = (
                message.file.name
                or f"ttl_{ttl}{message.file.ext or ''}"
            )
            file.seek(0)
            caption = header + utils.escape_html(message.text or "")
            msg = await self._client.send_file(
                self.c.id,
                file,
                force_document=True,
                caption=caption,
                reply_to=topic_id,
            )
        else:
            text = utils.escape_html(message.text or message.raw_text or "")
            msg = await self._client.send_message(
                self.c.id,
                header + text,
                reply_to=topic_id,
            )

        await self._mark_topic_read(msg)
        return msg

    async def _queue_handler(self, message: Message):
        if not isinstance(message, Message) or not message.is_private:
            return
        user = await message.get_sender()
        if user.id == self.tg_id:
            user = await message.get_chat()
        if (user.bot and not self.config["log_bots"]) or user.id == self.tg_id:
            return
        chatidindb = utils.get_chat_id(message) in (self.config["log_list"] or [])
        if (
            self.config["whitelist"]
            and chatidindb
            or not self.config["whitelist"]
            and not chatidindb
        ):
            return
        try:
            if await self._topic_handler(user, message):
                # Self-destructive (TTL) media/messages must be downloaded
                # and re-sent as regular files, otherwise they either fail
                # to forward (MessageIdInvalidError) or keep their TTL and
                # disappear from the log chat as well.
                if self.config["log_self_destr"] and self._is_self_destructive(
                    message
                ):
                    await self._save_self_destructive(user, message)
                    return

                msg = await message.forward_to(
                    self.c.id, top_msg_id=self._topic_cache[user.id].id
                )
                await self._mark_topic_read(msg)
        except MessageIdInvalidError:
            if not message.file or not self.config["log_self_destr"]:
                return
            await self._save_self_destructive(user, message)

    @loader.watcher(only_messages=True)
    async def watcher(self, message: Message):
        """Intercepts all incoming messages and logs PMs."""
        with contextlib.suppress(Exception):
            await self._queue_handler(message)
