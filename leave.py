from .. import loader, utils
from asyncio import sleep
from telethon.tl.functions.channels import LeaveChannelRequest
@loader.tds
class LeaveMod(loader.Module):
	strings = {"name": "Just leave"}
	@loader.sudo
	async def leavecmd(self, message):
		""".leave [текст или 'del']"""
		if not message.chat:
			await message.edit("<i>[хуй]</i>")
			return
		client = message.client
		chat_id = message.chat_id
		text = utils.get_args_raw(message)
		if not text:
			text = "До связи."
		if text.lower() == "del":
			await message.delete()
		else:
			await message.edit(f"<b>{text}</b>")
		await sleep(1)
		await client(LeaveChannelRequest(chat_id))
		
		