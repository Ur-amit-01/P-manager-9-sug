import os
import logging
import logging.config
from pyrogram import Client
from config import *
from plugins.Post.Posting import restore_pending_deletions
from plugins.Post.Invite_link import generate_all_links
import asyncio
from plugins.helper.sync_channels import sync_channel_names

logging.config.fileConfig('logging.conf')
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)

class Bot(Client):
    def __init__(self):
        super().__init__(
            name="renamer",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            workers=50,
            plugins={"root": "plugins"},
            sleep_threshold=5,
        )
        self.admin_panel = None  # Initialize as None first

    async def start(self):
        await super().start()
        me = await self.get_me()
        self.mention = me.mention
        self.username = me.username

        await restore_pending_deletions(self)

        asyncio.create_task(generate_all_links(self))
        logging.info(f"{me.first_name} Invite link generation started in background. 🔗")

        asyncio.create_task(sync_channel_names(self))
        logging.info(f"{me.first_name} Channel name sync started in background. 📣")

        logging.info(f"{me.first_name} ✅✅ BOT started successfully ✅✅")
        
        # Notify admins if enabled in config
        if RESTART_NOTIFICATION:
            for admin_id in ADMIN:
                try:
                    await self.send_message(
                        admin_id,
                        "**Missed me ??**\n"
                        "**I'm baaack online ~ 🎀🌝**")
                except Exception as e:
                    logging.warning(f"Failed to send restart notification to {admin_id}: {e}")
        else:
            logging.info("Restart notifications are disabled in config")

    async def stop(self, *args):
        await super().stop()
        logging.info("Bot Stopped 🙄")

bot = Bot()
bot.run()
