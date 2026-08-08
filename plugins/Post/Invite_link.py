from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import ChannelInvalid, ChatAdminRequired, PeerIdInvalid
from plugins.helper.db import db
from plugins.Post.admin_panel import admin_filter

GROUPS = ["0", "1", "2", "3"]


async def generate_group_link(client, channel):
    """Revoke the old stored link (if any) and create a fresh one for a single channel."""
    channel_id_str = channel["_id"]
    channel_id = channel["channel_id"]
    group = channel["group"]

    # Revoke the previous link for this channel, if we have one on record.
    old = await db.invite_links.find_one({"_id": channel_id_str})
    if old:
        try:
            await client.revoke_chat_invite_link(chat_id=channel_id, invite_link=old["link"])
        except Exception as e:
            print(f"Could not revoke old link for {channel.get('name', channel_id)}: {e}")

    # Get a current display name (fall back to the stored one).
    try:
        chat = await client.get_chat(channel_id)
        name = chat.title or chat.first_name or chat.username or f"Channel {channel_id}"
    except Exception:
        name = channel.get("name") or f"Channel {channel_id}"

    invite = await client.create_chat_invite_link(
        chat_id=channel_id,
        name=f"Link_{datetime.now().strftime('%m%d%H%M')}",
    )

    await db.save_invite_link(channel_id_str, {
        "channel_id": channel_id,
        "group": group,
        "name": name,
        "link": invite.invite_link,
        "generated_at": datetime.now(),
    })
    return True


async def generate_links_for_group(client, group):
    """Regenerate links for every channel in a group. Returns (success, failed_names)."""
    channels = await db.get_channels_by_group(group)
    success, failed = 0, []

    for channel in channels:
        try:
            await generate_group_link(client, channel)
            success += 1
        except (ChannelInvalid, ChatAdminRequired, PeerIdInvalid) as e:
            failed.append(f"{channel.get('name', channel['_id'])} - {e.__class__.__name__}")
        except Exception as e:
            failed.append(f"{channel.get('name', channel['_id'])} - {e}")

    return success, failed


async def generate_all_links(client):
    """Called on bot startup: regenerate invite links for every group."""
    for group in GROUPS:
        try:
            success, failed = await generate_links_for_group(client, group)
            if failed:
                print(f"Group {group}: generated {success}, failed {len(failed)} -> {failed}")
        except Exception as e:
            print(f"Error generating links for group {group}: {e}")


async def send_group_links(client, message: Message, group):
    links = await db.get_invite_links_by_group(group)

    if not links:
        await message.reply(
            f"❌ No links stored for group {group} yet.\n"
            f"They're generated automatically when the bot starts."
        )
        return

    chunk_size = 30
    chunks = [links[i:i + chunk_size] for i in range(0, len(links), chunk_size)]

    for i, chunk in enumerate(chunks, 1):
        text = "\n".join(f"• <a href='{doc['link']}'><b>{doc['name']}</b></a>" for doc in chunk)
        header = f"🔗 <b>Group {group} Links</b>" + (f" (Part {i}/{len(chunks)})" if len(chunks) > 1 else "")
        await message.reply(f"{header}\n\n{text}", disable_web_page_preview=True)


@Client.on_message(filters.command(["link", "link1", "link2", "link3"]) & filters.private & admin_filter)
async def get_links(client, message: Message):
    cmd = message.command[0]
    group = cmd[-1] if cmd != "link" else "0"
    await send_group_links(client, message, group)


@Client.on_message(filters.command(["regenlink", "regenlink1", "regenlink2", "regenlink3"]) & filters.private & admin_filter)
async def regen_links(client, message: Message):
    """Optional manual trigger, in case you don't want to wait for a restart."""
    cmd = message.command[0]
    group = cmd[-1] if cmd != "regenlink" else "0"

    processing = await message.reply(f"🔄 <b>Regenerating links for group {group}...</b>")
    success, failed = await generate_links_for_group(client, group)

    text = f"✅ <b>Regenerated {success} link(s) for group {group}</b>\n"
    if failed:
        text += f"❌ <b>Failed:</b>\n" + "\n".join(f"• {f}" for f in failed[:5])

    await processing.edit_text(text)
