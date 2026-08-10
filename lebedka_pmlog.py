
#
# 🔒 Licensed under the GNU GPLv3
# 🌐 https://www.gnu.org/licenses/gpl-3.0.html

# meta developer: @LebedKA_SYS
# scope: hikka_only
# scope: hikka_min 1.3.3

import asyncio
import logging
from datetime import datetime
from io import BytesIO

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
        "_cfg_bots": "🤖 Log messages from bots too (default: off).",
        "_cfg_loglist": (
            "📋 List of chat/user ids for the filter below. Easier to manage"
            " with .pmlogadd / .pmlogdel / .pmloglist."
        ),
        "_cfg_selfdestructive": (
            "🔥 Save self-destructive (TTL) photos/videos so they stay in the"
            " log. ⚠️ Violates Telegram TOS — use at your own risk."
        ),
        "_cfg_whitelist": (
            "🛡 List mode: ON = blacklist (log everyone EXCEPT the list), OFF ="
            " whitelist (log ONLY the list)."
        ),
        "_cfg_realtime_usernames": (
            "🔄 Rename the topic when the user changes their name and post a"
            " notice about it."
        ),
        "_cfg_mark_read": "👁 Mark logged messages as read in the log chat.",
        "_cfg_loggroups": (
            "👥 Also log group/supergroup chats that are added to the list"
            " above (by default only private chats are logged)."
        ),
        "_cmd_doc_pmlogadd": "Add chat/user id(s) to the log list (reply, id(s) or current chat).",
        "_cmd_doc_pmlogdel": "Remove chat/user id(s) from the log list (reply, id(s) or current chat).",
        "_cmd_doc_pmloglist": "Show the current log list.",
        "no_id": "🚫 <b>Could not determine the id. Reply to a message, pass an id or run in the target chat.</b>",
        "added": "✅ <b>Id</b> <code>{}</code> <b>added to the log list.</b>",
        "already_added": "ℹ️ <b>Id</b> <code>{}</code> <b>is already in the log list.</b>",
        "removed": "✅ <b>Id</b> <code>{}</code> <b>removed from the log list.</b>",
        "not_in_list": "ℹ️ <b>Id</b> <code>{}</code> <b>is not in the log list.</b>",
        "list_empty": "📭 <b>The log list is empty.</b>",
        "list_header": "📄 <b>Log list</b> ({} mode):\n{}",
        "mode_white": "whitelist",
        "mode_black": "blacklist",
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
        "_cfg_bots": "🤖 Логировать ли сообщения ботов (по умолчанию выкл).",
        "_cfg_loglist": (
            "📋 Список id чатов/пользователей для фильтра ниже. Удобнее"
            " управлять командами .pmlogadd / .pmlogdel / .pmloglist."
        ),
        "_cfg_selfdestructive": (
            "🔥 Сохранять самоуничтожающиеся (TTL) фото/видео, чтобы они"
            " оставались в логе. ⚠️ Нарушает «Условия использования Telegram»"
            " (ToS) — на свой страх и риск."
        ),
        "_cfg_whitelist": (
            "🛡 Режим списка: ВКЛ = чёрный список (логировать всех, КРОМЕ"
            " списка), ВЫКЛ = белый список (логировать ТОЛЬКО из списка)."
        ),
        "_cfg_realtime_usernames": (
            "🔄 Переименовывать тему при смене имени пользователя и писать об"
            " этом уведомление."
        ),
        "_cfg_mark_read": "👁 Отмечать залогированные сообщения прочитанными в чате лога.",
        "_cfg_loggroups": (
            "👥 Логировать также группы/супергруппы, добавленные в список выше"
            " (по умолчанию логируются только личные чаты)."
        ),
        "_cmd_doc_cpmlog": "Это откроет конфиг для модуля.",
        "_cmd_doc_pmlogadd": "Добавить id чатов/пользователей в список логирования (реплай, id через пробел/запятую или текущий чат).",
        "_cmd_doc_pmlogdel": "Удалить id чатов/пользователей из списка логирования (реплай, id через пробел/запятую или текущий чат).",
        "_cmd_doc_pmloglist": "Показать текущий список логирования.",
        "no_id": "🚫 <b>Не удалось определить id. Ответьте на сообщение, укажите id или запустите в нужном чате.</b>",
        "added": "✅ <b>Id</b> <code>{}</code> <b>добавлен в список логирования.</b>",
        "already_added": "ℹ️ <b>Id</b> <code>{}</code> <b>уже есть в списке логирования.</b>",
        "removed": "✅ <b>Id</b> <code>{}</code> <b>удалён из списка логирования.</b>",
        "not_in_list": "ℹ️ <b>Id</b> <code>{}</code> <b>отсутствует в списке логирования.</b>",
        "list_empty": "📭 <b>Список логирования пуст.</b>",
        "list_header": "📄 <b>Список логирования</b> (режим: {}):\n{}",
        "mode_white": "белый список",
        "mode_black": "чёрный список",
    }

    all_strings = {
        "strings": strings,
        "strings_en": strings,
        "strings_de": strings_de,
        "strings_ru": strings_ru,
    }

    _old_names = ["Apo PMLogger", "Apo-PMLog"]

    def __init__(self):
        self._ratelimit = []
        self._topic_cache = {}
        self._group_topic_cache = {}
        self._topic_locks = {}
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
                True,
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
            loader.ConfigValue(
                "log_groups",
                False,
                doc=lambda: self.strings("_cfg_loggroups"),
                validator=loader.validators.Boolean(),
            ),
        )

    async def client_ready(self):
        self._topic_cache = {}
        self._group_topic_cache = {}
        self._topic_locks = {}
        self.c, _ = await utils.asset_channel(
            self._client,
            "[LebedKA] PMLog",
            "Chat for logged PMs. The ID's in the topic titles are the user ID's, don't remove them!",
            silent=True,
            invite_bot=False,
        )
        if not self.c.forum:
            await self._client(ToggleForumRequest(self.c.id, True))
        self.gc = None
        if self.config["log_groups"]:
            await self._ensure_group_channel()

    async def _ensure_group_channel(self):
        """Lazily creates/returns the separate channel used for group logs."""
        if getattr(self, "gc", None):
            return self.gc
        self.gc, _ = await utils.asset_channel(
            self._client,
            "[LebedKA] PMLogGroups",
            "Chat for logged group messages. The ID's in the topic titles are the chat ID's, don't remove them!",
            silent=True,
            invite_bot=False,
        )
        if not self.gc.forum:
            await self._client(ToggleForumRequest(self.gc.id, True))
        return self.gc

    async def cpmlogcmd(self, message: Message):
        """
        This will open the config for the module.
        """
        name = self.strings("name")
        await self.allmodules.commands["config"](
            await utils.answer(message, f"{self.get_prefix()}config {name}")
        )

    @staticmethod
    def _normalize_id(chat_id: int) -> int:
        """
        Normalizes an id to the same form utils.get_chat_id() returns
        (positive id without the -100 supergroup/channel prefix), so ids
        added by the user match ids seen in the watcher.
        """
        s = str(chat_id)
        if s.startswith("-100"):
            return int(s[4:])
        if s.startswith("-"):
            return int(s[1:])
        return chat_id

    async def _resolve_target_ids(self, message: Message):
        args = utils.get_args_raw(message)
        if args:
            raw_ids = [
                part
                for part in args.replace(",", " ").split()
                if part
            ]
            targets = []
            for part in raw_ids:
                try:
                    targets.append(self._normalize_id(int(part)))
                except ValueError:
                    try:
                        entity = await self._client.get_entity(part)
                        targets.append(self._normalize_id(entity.id))
                    except Exception:
                        continue
            return targets
        reply = await message.get_reply_message()
        if reply:
            return [self._normalize_id(reply.sender_id)]
        return [utils.get_chat_id(message)]

    async def pmlogaddcmd(self, message: Message):
        """
        Add chat/user id(s) to the log list (reply, id(s) or current chat).
        """
        targets = await self._resolve_target_ids(message)
        if not targets:
            await utils.answer(message, self.strings("no_id"))
            return
        log_list = list(self.config["log_list"] or [])
        added, skipped = [], []
        for target in targets:
            if target in log_list:
                skipped.append(target)
            else:
                log_list.append(target)
                added.append(target)
        self.config["log_list"] = log_list
        lines = []
        if added:
            lines.append(
                self.strings("added").format(
                    ", ".join(str(i) for i in added)
                )
            )
        if skipped:
            lines.append(
                self.strings("already_added").format(
                    ", ".join(str(i) for i in skipped)
                )
            )
        await utils.answer(message, "\n".join(lines))

    async def pmlogdelcmd(self, message: Message):
        """
        Remove chat/user id(s) from the log list (reply, id(s) or current chat).
        """
        targets = await self._resolve_target_ids(message)
        if not targets:
            await utils.answer(message, self.strings("no_id"))
            return
        log_list = list(self.config["log_list"] or [])
        removed, missing = [], []
        for target in targets:
            if target in log_list:
                log_list.remove(target)
                removed.append(target)
            else:
                missing.append(target)
        self.config["log_list"] = log_list
        lines = []
        if removed:
            lines.append(
                self.strings("removed").format(
                    ", ".join(str(i) for i in removed)
                )
            )
        if missing:
            lines.append(
                self.strings("not_in_list").format(
                    ", ".join(str(i) for i in missing)
                )
            )
        await utils.answer(message, "\n".join(lines))

    async def pmloglistcmd(self, message: Message):
        """
        Show the current log list.
        """
        log_list = list(self.config["log_list"] or [])
        if not log_list:
            await utils.answer(message, self.strings("list_empty"))
            return
        mode = (
            self.strings("mode_white")
            if self.config["whitelist"]
            else self.strings("mode_black")
        )
        lines = []
        for i in log_list:
            try:
                entity = await self._client.get_entity(i)
                name = utils.escape_html(self._entity_name(entity))
                lines.append(f"• <b>{name}</b> — <code>{i}</code>")
            except Exception:
                lines.append(f"• <code>{i}</code>")
        items = "\n".join(lines)
        await utils.answer(
            message, self.strings("list_header").format(mode, items)
        )

    @staticmethod
    def _entity_name(entity) -> str:
        """Returns a display name for a user (first_name) or a group (title)."""
        return (
            getattr(entity, "title", None)
            or getattr(entity, "first_name", None)
            or getattr(entity, "username", None)
            or "Unknown"
        )

    def _get_topic_lock(self, channel, user_id: int) -> asyncio.Lock:
        """Returns a per-(channel, id) lock to serialize topic creation."""
        key = (channel.id, user_id)
        lock = self._topic_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._topic_locks[key] = lock
        return lock

    async def _topic_cacher(self, user: User, channel, cache: dict):
        """
        Finds the forum topic for a user/chat id and stores it in cache.
        Paginates through all topics — a single page of 100 is not enough
        for large log channels, and offset_date=now() skips existing topics.
        """
        if user.id in cache:
            return True

        needle = f"({user.id})"
        offset_date = datetime(1970, 1, 1)
        offset_id = 0
        offset_topic = 0
        seen = set()

        while True:
            forum = await self._client(
                GetForumTopicsRequest(
                    channel=channel.id,
                    offset_date=offset_date,
                    offset_id=offset_id,
                    offset_topic=offset_topic,
                    limit=100,
                )
            )
            topics = getattr(forum, "topics", None) or []
            if not topics:
                break

            page_ids = set()
            for topic in topics:
                page_ids.add(topic.id)
                if needle in (topic.title or ""):
                    cache[user.id] = topic
                    return True

            # Stop if the API keeps returning the same page.
            if page_ids <= seen or len(topics) < 100:
                break
            seen |= page_ids

            last = topics[-1]
            # Continue pagination from the last returned topic.
            offset_topic = last.id
            offset_id = getattr(last, "top_message", 0) or 0
            # date may be absent on ForumTopic; fall back to previous offset.
            offset_date = getattr(last, "date", None) or offset_date

        return False

    async def _topic_creator(self, user: User, channel, cache: dict):
        # Re-check the cache in case another coroutine created the topic
        # while we were waiting for the lock, to avoid duplicate topics.
        if await self._topic_cacher(user, channel, cache):
            return True

        result = await self._client(
            CreateForumTopicRequest(
                channel=channel.id,
                title=f"{self._entity_name(user)} ({user.id})",
                icon_color=42,
            )
        )

        # Prefer the created topic from the API response — re-fetching via
        # GetForumTopics can miss a brand-new topic (eventual consistency /
        # pagination), which used to drop already-downloaded TTL media.
        topic = self._topic_from_updates(result, user.id)
        if topic is not None:
            cache[user.id] = topic
            return True

        cache.pop(user.id, None)
        # Short delay then re-scan; topic list can lag right after create.
        await asyncio.sleep(0.5)
        return await self._topic_cacher(user, channel, cache)

    @staticmethod
    def _topic_from_updates(updates, user_id: int):
        """Extracts a newly created ForumTopic from CreateForumTopic updates."""
        needle = f"({user_id})"
        candidates = []

        for attr in ("updates", "chats", "users"):
            part = getattr(updates, attr, None)
            if part:
                candidates.extend(part)
        candidates.append(updates)

        for obj in candidates:
            # messages.ForumTopics-like / direct ForumTopic
            topics = getattr(obj, "topics", None)
            if topics:
                for topic in topics:
                    if needle in (getattr(topic, "title", None) or ""):
                        return topic
                    # Single newly created topic — accept even without id match
                    if len(topics) == 1 and getattr(topic, "id", None):
                        return topic

            title = getattr(obj, "title", None)
            topic_id = getattr(obj, "id", None)
            if title and needle in title and topic_id is not None:
                # Duck-typed ForumTopic
                if hasattr(obj, "top_message") or obj.__class__.__name__ == "ForumTopic":
                    return obj

            # UpdateNewChannelMessage with a service message that opens a topic
            message = getattr(obj, "message", None)
            action = getattr(message, "action", None) if message else None
            if action is not None and getattr(action, "title", None):
                if needle in action.title:
                    # reply_to_msg_id / id of the topic root message is the topic id
                    topic_id = getattr(
                        getattr(message, "reply_to", None),
                        "reply_to_msg_id",
                        None,
                    ) or getattr(message, "id", None)
                    if topic_id is not None:
                        class _Topic:
                            pass

                        t = _Topic()
                        t.id = topic_id
                        t.title = action.title
                        t.top_message = getattr(message, "id", topic_id)
                        return t

        return None

    async def _topic_handler(self, user: User, message: Message, channel, cache: dict):
        async with self._get_topic_lock(channel, user.id):
            if not await self._topic_cacher(user, channel, cache):
                if not await self._topic_creator(user, channel, cache):
                    return False

        if user.id not in cache:
            return False

        new_title = f"{self._entity_name(user)} ({user.id})"
        if (
            self.config["realtime_names"]
            and cache[user.id].title != new_title
        ):
            old_title = cache[user.id].title
            await self._client(
                EditForumTopicRequest(
                    channel=channel.id,
                    topic_id=cache[user.id].id,
                    title=new_title,
                )
            )
            cache[user.id].title = new_title
            await message.client.send_message(
                channel.id,
                f"New name:\n<code>{new_title}</code>\n\nOld name:\n<code>{old_title}</code>",
                reply_to=cache[user.id].id,
            )
        return True

    @staticmethod
    def _is_self_destructive(message: Message) -> bool:
        """
        Returns True if the message contains self-destructive (TTL) media
        or is itself a self-destructive message (e.g. secret chat ttl_seconds).
        """
        media = getattr(message, "media", None)
        # ttl_seconds can be on photo/document media; treat any non-None
        # value (including 0) as self-destructive.
        if media is not None and getattr(media, "ttl_seconds", None) is not None:
            return True
        if getattr(message, "ttl_seconds", None) is not None:
            return True
        return False

    async def _download_ttl_media(self, message: Message):
        """
        Downloads TTL media ASAP into BytesIO. Must run before any slow
        work (topic create/search), otherwise the file may already be gone.
        """
        buf = BytesIO()
        result = await self._client.download_media(message, file=buf)
        if result is None and buf.getbuffer().nbytes == 0:
            raise ValueError("download_media returned no data")
        if buf.getbuffer().nbytes == 0:
            raise ValueError("Downloaded media buffer is empty")
        buf.seek(0)
        return buf

    async def _mark_topic_read(self, msg: Message, channel):
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
                channel.id,
                read_max_id,
                2**31 - 1,
            )
        )

    async def _save_self_destructive(
        self, user: User, message: Message, channel, cache: dict, downloaded_media=None
    ):
        """
        Downloads self-destructive media and sends it to the log chat as a
        regular document (without TTL), so it won't disappear from the log.
        Also handles self-destructive text-only messages.
        """
        if user.id not in cache:
            raise KeyError(f"No forum topic cached for {user.id}")

        topic_id = cache[user.id].id
        ttl = (
            getattr(getattr(message, "media", None), "ttl_seconds", None)
            or getattr(message, "ttl_seconds", None)
            or 0
        )
        header = (
            f"🔥 <b>Self-destructive message</b> (TTL: <code>{ttl}s</code>)\n"
        )

        media = getattr(message, "media", None)
        if media is not None:
            try:
                if downloaded_media is not None:
                    file = downloaded_media
                else:
                    file = await self._download_ttl_media(message)

                if not getattr(file, "getbuffer", None) or file.getbuffer().nbytes == 0:
                    raise ValueError("Downloaded media buffer is empty")

                ext = ""
                if message.file and message.file.ext:
                    ext = message.file.ext
                file.name = (
                    (message.file.name if message.file else None)
                    or f"ttl_{ttl}{ext}"
                )
                file.seek(0)
                caption = header + utils.escape_html(message.text or "")
                msg = await self._client.send_file(
                    channel.id,
                    file,
                    force_document=True,
                    caption=caption,
                    reply_to=topic_id,
                )
            except Exception as e:
                logger.exception("Failed to download self-destructive media: %s", e)
                text = utils.escape_html(message.text or message.raw_text or "")
                msg = await self._client.send_message(
                    channel.id,
                    header + text + "\n\n<i>⚠️ Failed to download media</i>",
                    reply_to=topic_id,
                )
        else:
            text = utils.escape_html(message.text or message.raw_text or "")
            msg = await self._client.send_message(
                channel.id,
                header + text,
                reply_to=topic_id,
            )

        await self._mark_topic_read(msg, channel)
        return msg

    async def _save_regular(self, user: User, message: Message, channel, cache: dict):
        """
        Fallback logger for messages that cannot be forwarded (e.g. content
        protected chats). Re-uploads media by downloading it, so nothing is
        lost from the log.
        """
        topic_id = cache[user.id].id
        media = getattr(message, "media", None)
        if media is not None:
            file = BytesIO()
            await self._client.download_media(message, file=file)
            if file.getbuffer().nbytes == 0:
                raise ValueError("Downloaded media buffer is empty")
            ext = ""
            if message.file and message.file.ext:
                ext = message.file.ext
            file.name = (
                (message.file.name if message.file else None) or f"media{ext}"
            )
            file.seek(0)
            caption = utils.escape_html(message.text or "")
            msg = await self._client.send_file(
                channel.id,
                file,
                caption=caption,
                reply_to=topic_id,
            )
        else:
            text = utils.escape_html(message.text or message.raw_text or "")
            msg = await self._client.send_message(
                channel.id,
                text,
                reply_to=topic_id,
            )
        await self._mark_topic_read(msg, channel)
        return msg

    async def _queue_handler(self, message: Message):
        if not isinstance(message, Message):
            return

        chatidindb = utils.get_chat_id(message) in (self.config["log_list"] or [])

        if message.is_private:
            user = await message.get_sender()
            if user.id == self.tg_id:
                user = await message.get_chat()
            if (user.bot and not self.config["log_bots"]) or user.id == self.tg_id:
                return
            if (
                self.config["whitelist"]
                and chatidindb
                or not self.config["whitelist"]
                and not chatidindb
            ):
                return
            channel = self.c
            cache = self._topic_cache
        elif self.config["log_groups"] and chatidindb:
            user = await message.get_chat()
            channel = await self._ensure_group_channel()
            cache = self._group_topic_cache
        else:
            return
        is_self_destr = self._is_self_destructive(message)
        downloaded_media = None

        # Download TTL media immediately — before topic lookup/create.
        # Opening the photo on another device (or a slow topic create) used
        # to leave an empty/missing file by the time we tried to save it.
        if is_self_destr and self.config["log_self_destr"] and message.media:
            try:
                downloaded_media = await self._download_ttl_media(message)
            except Exception as e:
                logger.exception(
                    "Failed to pre-download self-destructive media: %s", e
                )

        try:
            topic_ok = await self._topic_handler(user, message, channel, cache)
            if not topic_ok:
                # Last chance: ensure topic exists before we drop bytes.
                async with self._get_topic_lock(channel, user.id):
                    topic_ok = await self._topic_creator(user, channel, cache)
                if not topic_ok:
                    logger.error(
                        "PMLog: no forum topic for %s — cannot save message",
                        user.id,
                    )
                    return

            if is_self_destr:
                if self.config["log_self_destr"]:
                    await self._save_self_destructive(
                        user, message, channel, cache, downloaded_media
                    )
                return

            msg = await message.forward_to(
                channel.id, top_msg_id=cache[user.id].id
            )
            await self._mark_topic_read(msg, channel)
        except Exception as e:
            if is_self_destr:
                if not self.config["log_self_destr"]:
                    logger.debug(
                        "Skipping self-destructive message (logging disabled): %s",
                        e,
                    )
                    return
                try:
                    if user.id not in cache:
                        async with self._get_topic_lock(channel, user.id):
                            await self._topic_creator(user, channel, cache)
                    if user.id in cache:
                        await self._save_self_destructive(
                            user, message, channel, cache, downloaded_media
                        )
                    else:
                        logger.exception(
                            "PMLog: TTL media downloaded but topic missing for %s: %s",
                            user.id,
                            e,
                        )
                except Exception as e2:
                    logger.exception(
                        "Failed to save self-destructive message: %s / %s", e, e2
                    )
                return

            try:
                if user.id not in cache:
                    async with self._get_topic_lock(channel, user.id):
                        await self._topic_creator(user, channel, cache)
                if user.id in cache:
                    await self._save_regular(user, message, channel, cache)
                else:
                    logger.exception("Failed to log message (no topic): %s", e)
            except Exception as e2:
                logger.exception("Failed to log message: %s / %s", e, e2)

    @loader.watcher(only_messages=True)
    async def watcher(self, message: Message):
        """Intercepts all incoming messages and logs PMs."""
        try:
            await self._queue_handler(message)
        except Exception as e:
            logger.exception("PMLog watcher error: %s", e)
