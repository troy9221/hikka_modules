# ©️ Dan Gazizullin, 2021-2023
# This file is a part of Hikka Userbot
# 🌐 https://github.com/troy9221/Hikka
# You can redistribute it and/or modify it under the terms of the GNU AGPLv3
# 🔑 https://www.gnu.org/licenses/agpl-3.0.html

import asyncio
import contextlib
import datetime
import io
import json
import logging
import inspect
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from hikkatl.tl.types import Message

from .. import loader, utils
from ..inline.types import BotInlineCall

logger = logging.getLogger(__name__)


@loader.tds
class HikkaBackupMod(loader.Module):
    """Handles database and modules backups"""

    strings = {
        "name": "HikkaBackup",
        "backup_group_sent": "Backup sent to the backup group.",
        "backup_full_caption": (
            "<b>Hikka backup: settings and modules</b>\nReply to this archive:\n<code>{prefix}restorebackup</code> — restore everything\n<code>{prefix}restoredb</code> — settings only\n<code>{prefix}restoremods</code> — modules only"
        ),
        "backup_restored": "Settings and modules restored. Restarting Hikka.",
        "backup_db_caption": (
            "<b>Hikka settings</b>\nReply to this file with <code>{prefix}restoredb</code>."
        ),
        "backup_mods_caption": (
            "<b>Hikka modules</b>\nReply to this file with <code>{prefix}restoremods</code>.\nFor a full recovery, restore settings first, then modules."
        ),
    }
    strings_ru = {
        "backup_group_sent": "Бэкап отправлен в группу резервных копий.",
        "backup_full_caption": (
            "<b>Бэкап Hikka: настройки и модули</b>\nОтветьте на этот архив:\n<code>{prefix}restorebackup</code> — восстановить всё\n<code>{prefix}restoredb</code> — только настройки\n<code>{prefix}restoremods</code> — только модули"
        ),
        "backup_restored": "Настройки и модули восстановлены. Перезапускаю Hikka.",
        "backup_db_caption": (
            "<b>Настройки Hikka</b>\nОтветьте на этот файл командой <code>{prefix}restoredb</code>."
        ),
        "backup_mods_caption": (
            "<b>Модули Hikka</b>\nОтветьте на этот файл командой <code>{prefix}restoremods</code>.\nПри полном восстановлении сначала восстановите настройки, затем модули."
        ),
    }

    async def client_ready(self):
        if not self.get("period"):
            await self.inline.bot.send_photo(
                self.tg_id,
                photo="https://github.com/hikariatama/assets/raw/master/unit_alpha.png",
                caption=self.strings("period"),
                reply_markup=self.inline.generate_markup(
                    utils.chunks(
                        [
                            {
                                "text": f"🕰 {i} h",
                                "callback": self._set_backup_period,
                                "args": (i,),
                            }
                            for i in [1, 2, 4, 6, 8, 12, 24, 48, 168]
                        ],
                        3,
                    )
                    + [
                        [
                            {
                                "text": "🚫 Never",
                                "callback": self._set_backup_period,
                                "args": (0,),
                            }
                        ]
                    ]
                ),
            )

        self._backup_channel, _ = await utils.asset_channel(
            self._client,
            "hikka-backups",
            "📼 Your database backups will appear here",
            silent=True,
            archive=True,
            avatar="https://github.com/hikariatama/assets/raw/master/hikka-backups.png",
            _folder="hikka",
        )

    async def _set_backup_period(self, call: BotInlineCall, value: int):
        if not value:
            self.set("period", "disabled")
            await call.answer(self.strings("never"), show_alert=True)
            await call.delete()
            return

        self.set("period", value * 60 * 60)
        self.set("last_backup", round(time.time()))

        await call.answer(self.strings("saved"), show_alert=True)
        await call.delete()

    @loader.command()
    @loader.owner
    async def set_backup_period(self, message: Message):
        if (
            not (args := utils.get_args_raw(message))
            or not args.isdigit()
            or int(args) not in range(200)
        ):
            await utils.answer(message, self.strings("invalid_args"))
            return

        if not int(args):
            self.set("period", "disabled")
            await utils.answer(message, f"<b>{self.strings('never')}</b>")
            return

        period = int(args) * 60 * 60
        self.set("period", period)
        self.set("last_backup", round(time.time()))
        await utils.answer(message, f"<b>{self.strings('saved')}</b>")

    def _database_backup(self):
        backup = io.BytesIO(json.dumps(self._db).encode())
        backup.name = f"hikka-db-backup-{datetime.datetime.now():%d-%m-%Y-%H-%M}.json"
        return backup

    def _modules_backup(self):
        """Snapshot local and in-memory external module sources, plus loader URLs."""
        sources = {}
        for path in sorted(Path(loader.LOADED_MODULES_DIR).rglob(f"*_{self.tg_id}.py")):
            if path.is_file() and not path.is_symlink():
                if path.name in sources:
                    raise ValueError("Duplicate module filename in backup")
                sources[path.name] = path.read_bytes()
        for module in getattr(self.allmodules, "modules", ()):
            if getattr(module, "__origin__", "").startswith("<core"):
                continue
            filename = f"{type(module).__name__}_{self.tg_id}.py"
            namespace = sys.modules.get(type(module).__module__)
            if namespace is None:
                if filename not in sources:
                    raise ValueError("External module source is unavailable")
                continue
            source = getattr(getattr(namespace, "__loader__", None), "data", None)
            if source is None:
                try:
                    source = inspect.getsource(namespace)
                except (OSError, TypeError):
                    if filename not in sources:
                        raise ValueError(
                            "External module source is unavailable"
                        ) from None
                    continue
            if isinstance(source, str):
                source = source.encode("utf-8")
            if isinstance(source, bytes):
                sources[filename] = source
            elif filename not in sources:
                raise ValueError("External module source is unavailable")
        archive = io.BytesIO()
        archive.name = f"mods-{datetime.datetime.now():%d-%m-%Y-%H-%M}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipf:
            for name, source in sorted(sources.items()):
                zipf.writestr(name, source)
            zipf.writestr(
                "db_mods.json",
                json.dumps(self.lookup("Loader").get("loaded_modules", {})).encode(),
            )
        archive.seek(0)
        return archive

    def _full_backup(self):
        archive = io.BytesIO()
        archive.name = f"hikka-backup-{datetime.datetime.now():%d-%m-%Y-%H-%M}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as full:
            full.writestr("hikka-db.json", self._database_backup().getvalue())
            with zipfile.ZipFile(self._modules_backup()) as modules:
                for entry in modules.infolist():
                    full.writestr(entry.filename, modules.read(entry))
        archive.seek(0)
        return archive

    async def _send_backup(self):
        archive = self._full_backup()
        await self._client.send_file(
            self._backup_channel,
            archive,
            caption=self.strings("backup_full_caption").format(
                prefix=utils.escape_html(self.get_prefix())
            ),
            parse_mode="html",
        )

    @staticmethod
    def _write_module(path, content):
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".restore-", delete=False
        ) as temp:
            temp.write(content)
            temporary = Path(temp.name)
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def _restore_payload(self, data, *, configuration=False, modules=False):
        if len(data) > 64 * 1024 * 1024:
            raise ValueError("Backup exceeds restore size limit")
        config, urls, sources = None, None, {}
        if zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                names = [entry.filename for entry in entries]
                if (
                    len(names) != len(set(names))
                    or len(names) > 4096
                    or sum(entry.file_size for entry in entries) > 64 * 1024 * 1024
                ):
                    raise ValueError("Invalid or oversized backup archive")
                if configuration:
                    config = json.loads(archive.read("hikka-db.json"))
                if modules:
                    urls = json.loads(archive.read("db_mods.json"))
                    for name in names:
                        if name in ("hikka-db.json", "db_mods.json"):
                            continue
                        if (
                            Path(name).name != name
                            or "\\" in name
                            or not name.endswith(f"_{self.tg_id}.py")
                        ):
                            raise ValueError("Invalid module filename in backup")
                        sources[name] = archive.read(name)
        else:
            if configuration and modules:
                raise ValueError("Full recovery requires a ZIP backup")
            decoded = json.loads(data)
            if configuration:
                config = decoded
            if modules:
                urls = decoded
        if configuration:
            if not isinstance(config, dict):
                raise ValueError("Invalid configuration backup")
            with contextlib.suppress(KeyError):
                config["hikka.inline"].pop("bot_token")
            if not self._db.process_db_autofix(config):
                raise ValueError("Invalid configuration backup")
            if not modules:
                registry = self.lookup("Loader")
                namespace = type(registry).__name__
                if namespace in config:
                    config[namespace]["loaded_modules"] = registry.get(
                        "loaded_modules", {}
                    ).copy()
        if modules and (
            not isinstance(urls, dict)
            or not all(
                isinstance(key, str)
                and isinstance(value, str)
                and utils.check_url(value)
                for key, value in urls.items()
            )
        ):
            raise ValueError("Invalid module URL registry")
        root = Path(loader.LOADED_MODULES_PATH)
        targets = {root / name: content for name, content in sources.items()}
        if any(
            path.is_symlink() or path.resolve().parent != root.resolve()
            for path in targets
        ):
            raise ValueError("Unsafe module restore destination")
        # Validate the entire archive before touching the database or module files.
        previous_config = json.loads(json.dumps(self._db))
        previous_files = {
            path: path.read_bytes() if path.exists() else None for path in targets
        }
        touched = []
        try:
            for path, content in targets.items():
                self._write_module(path, content)
                touched.append(path)
            if configuration:
                self._db.clear()
                self._db.update(config)
            if modules:
                self.lookup("Loader").set("loaded_modules", urls)
            if self._db.save() is False:
                raise OSError("Unable to save restored configuration")
        except Exception:
            for path in reversed(touched):
                if previous_files[path] is None:
                    path.unlink(missing_ok=True)
                else:
                    self._write_module(path, previous_files[path])
            self._db.clear()
            self._db.update(previous_config)
            self._db.save()
            raise

    @loader.loop(interval=1, autostart=True)
    async def handler(self):
        try:
            if self.get("period") == "disabled":
                raise loader.StopLoop

            if not self.get("period"):
                await asyncio.sleep(3)
                return

            if not self.get("last_backup"):
                self.set("last_backup", round(time.time()))
                await asyncio.sleep(self.get("period"))
                return

            await asyncio.sleep(
                self.get("last_backup") + self.get("period") - time.time()
            )

            await self._send_backup()
            self.set("last_backup", round(time.time()))
        except loader.StopLoop:
            raise
        except Exception:
            logger.exception("HikkaBackup failed")
            await asyncio.sleep(60)

    @loader.command()
    @loader.owner
    async def backupdb(self, message: Message):
        await self._send_backup()
        await utils.answer(message, self.strings("backup_group_sent"))

    @loader.command()
    @loader.owner
    async def restoredb(self, message: Message):
        if not (reply := await message.get_reply_message()) or not reply.media:
            await utils.answer(
                message,
                self.strings("reply_to_file"),
            )
            return

        file = await reply.download_media(bytes)
        try:
            self._restore_payload(file, configuration=True)
        except (ValueError, KeyError, OSError, zipfile.BadZipFile):
            await utils.answer(message, self.strings("reply_to_file"))
            return

        await utils.answer(message, self.strings("db_restored"))
        await self.invoke("restart", "-f", peer=message.peer_id)

    @loader.command()
    @loader.owner
    async def backupmods(self, message: Message):
        archive = self._modules_backup()
        await self._client.send_file(
            self._backup_channel,
            archive,
            caption=self.strings("backup_mods_caption").format(
                prefix=utils.escape_html(self.get_prefix())
            ),
            parse_mode="html",
        )
        await utils.answer(message, self.strings("backup_group_sent"))

    @loader.command()
    @loader.owner
    async def restoremods(self, message: Message):
        if not (reply := await message.get_reply_message()) or not reply.media:
            await utils.answer(message, self.strings("reply_to_file"))
            return

        file = await reply.download_media(bytes)
        try:
            self._restore_payload(file, modules=True)
        except (ValueError, KeyError, OSError, zipfile.BadZipFile):
            await utils.answer(message, self.strings("reply_to_file"))
            return

        await utils.answer(message, self.strings("mods_restored"))
        await self.invoke("restart", "-f", peer=message.peer_id)

    @loader.command()
    @loader.owner
    async def restorebackup(self, message: Message):
        """Reply to a full ZIP backup to restore settings and modules together."""
        if not (reply := await message.get_reply_message()) or not reply.media:
            await utils.answer(message, self.strings("reply_to_file"))
            return
        try:
            self._restore_payload(
                await reply.download_media(bytes), configuration=True, modules=True
            )
        except (ValueError, KeyError, OSError, zipfile.BadZipFile):
            await utils.answer(message, self.strings("reply_to_file"))
            return
        await utils.answer(message, self.strings("backup_restored"))
        await self.invoke("restart", "-f", peer=message.peer_id)
