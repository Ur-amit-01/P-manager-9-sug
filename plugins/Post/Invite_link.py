from datetime import datetime, timedelta
import time
import re
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import ChannelInvalid, ChatAdminRequired, PeerIdInvalid
from plugins.helper.db import db
import random
import asyncio
from config import *
from plugins.Post.admin_panel import admin_filter

@Client.on_message(filters.command(["genlink", "genlink1", "genlink2", "genlink3"]) & filters.private & admin_filter)
async def generate_invite_links(client, message: Message):
    if not await db.is_admin(message.from_user.id):
        await message.reply("**❌ You are not authorized to use this command!**")
        return
    
    # Parse time argument
    expire_time = None
    time_suffix = ""
    if len(message.command) > 1:
        time_arg = message.command[1].lower()
        if match := re.match(r"^(\d+)([mhd])$", time_arg):
            num, unit = match.groups()
            num = int(num)
            if unit == 'm':
                expire_time = timedelta(minutes=num)
                time_suffix = f"⏳ Expires in {num} minutes"
            elif unit == 'h':
                expire_time = timedelta(hours=num)
                time_suffix = f"⏳ Expires in {num} hours"
            elif unit == 'd':
                expire_time = timedelta(days=num)
                time_suffix = f"⏳ Expires in {num} days"

    # Determine group
    cmd = message.command[0]
    group = "0"  # Default for "genlink"
    if len(cmd) > 7:  # If it's genlink1, genlink2, etc.
        group = cmd[-1]  # Get the last character (1, 2, or 3)

    # Initial processing message
    processing_msg = await message.reply(f"🔄 <b>Generating fresh links for group {group}...</b>")

    # Generate links for specific group
    channels = await db.get_channels_by_group(group)
    
    if not channels:
        await processing_msg.delete()
        await message.reply(f"**No channels in group {group} yet.🙁**")
        return

    links = {}
    success_count = 0
    failed_channels = []
    
    for channel in channels:
        try:
            # Extract channel ID from the stored format (e.g., "-1002089378646_0")
            channel_id_str = channel['_id']
            
            # Method 1: Try to extract numeric channel ID
            if '_' in channel_id_str:
                channel_id = int(channel_id_str.split('_')[0])
            else:
                # If not in the format with underscore, try to parse directly
                channel_id = int(channel_id_str)
            
            # Try to get current channel name from Telegram
            channel_name = None
            try:
                # Try to get channel info
                chat_info = await client.get_chat(channel_id)
                channel_name = chat_info.title or chat_info.first_name or chat_info.username or f"Channel {channel_id}"
            except Exception as e:
                print(f"Error fetching channel info for {channel_id}: {e}")
                # Fallback to stored name if available
                channel_name = channel.get('name', f"Channel {channel_id}")
            
            # Create invite link
            invite = await client.create_chat_invite_link(
                chat_id=channel_id,
                name=f"Link_{datetime.now().strftime('%m%d%H%M')}",
                expire_date=datetime.now() + expire_time if expire_time else None,
                creates_join_request=False
            )
            
            # Store with original channel ID string as key
            links[channel_id_str] = {
                'link': invite.invite_link,
                'name': channel_name,
                'group': group,
                'clean_id': channel_id,  # Store the clean ID for revocation
                'invite_name': invite.name  # Store the invite link name for potential revocation
            }
            success_count += 1
            
        except ValueError as e:
            print(f"Error parsing channel ID {channel['_id']}: {e}")
            failed_channels.append(f"{channel.get('name', channel['_id'])} - Invalid ID format")
        except ChannelInvalid as e:
            print(f"Channel invalid or bot not admin: {channel.get('name', channel['_id'])}")
            failed_channels.append(f"{channel.get('name', channel['_id'])} - Invalid channel or no admin access")
        except ChatAdminRequired as e:
            print(f"Bot needs admin permissions: {channel.get('name', channel['_id'])}")
            failed_channels.append(f"{channel.get('name', channel['_id'])} - Bot needs admin permissions")
        except PeerIdInvalid as e:
            print(f"Invalid peer ID: {channel.get('name', channel['_id'])}")
            failed_channels.append(f"{channel.get('name', channel['_id'])} - Invalid channel ID")
        except Exception as e:
            print(f"Error creating link for {channel.get('name', channel['_id'])}: {str(e)}")
            failed_channels.append(f"{channel.get('name', channel['_id'])} - {str(e)}")

    # Prepare response
    header = (
        f"✨ <b>Generated Fresh links for {success_count} channels in group {group}.</b>\n"
        f"**{time_suffix}**\n\n"
    )
    
    if failed_channels:
        header += f"❌ <b>Failed to generate links for {len(failed_channels)} channels:</b>\n"
        header += "\n".join(f"• {channel}" for channel in failed_channels[:5])
        if len(failed_channels) > 5:
            header += f"\n• ...and {len(failed_channels) - 5} more"
        header += "\n\n"
    
    if not links:
        await processing_msg.delete()
        await message.reply(f"❌ Failed to generate any links for group {group}.\n\n<b>Failures:</b>\n" + "\n".join(f"• {channel}" for channel in failed_channels[:10]))
        return
    
    # Convert links to list for chunking
    links_list = list(links.values())
    
    # Split into chunks of 30
    chunk_size = 30
    chunks = [links_list[i:i + chunk_size] for i in range(0, len(links_list), chunk_size)]
    
    # Send first message with header and first chunk
    first_chunk = "\n".join(
        f"• <a href='{info['link']}'><b>{info['name']}</b></a>"
        for info in chunks[0]
    )
    
    footer = (
        f"\n\n**⚠️ <i>These links will be revoked if you click 'Revoke Now' below or after {time_suffix.lower().replace('⏳ ', '')}</i>**"
        if time_suffix else "\n\n**⚠️ <i>These links will be revoked if you click 'Revoke Now' below</i>**"
    )
    
    # Create buttons only for the first message
    buttons = []
    if links:
        buttons.append([InlineKeyboardButton("🔴 Revoke Now", callback_data=f"revoke_group_{group}")])
    
    await processing_msg.delete()
    first_message = await message.reply(
        header + first_chunk + footer,
        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
        disable_web_page_preview=True
    )
    
    # Send remaining chunks as separate messages
    for i, chunk in enumerate(chunks[1:], 2):
        chunk_text = "\n".join(
            f"• <a href='{info['link']}'><b>{info['name']}</b></a>"
            for info in chunk
        )
        await message.reply(
            f"✨ <b>Generated Links for group {group} (Part {i}/{len(chunks)})</b>\n\n" + chunk_text,
            disable_web_page_preview=True
        )

    # Store links in a dictionary with group as key
    if not hasattr(client, 'generated_links'):
        client.generated_links = {}
    
    client.generated_links[group] = links

    # Schedule auto-revocation
    if expire_time:
        asyncio.create_task(auto_revoke_links(client, links, expire_time, group))

async def auto_revoke_links(client, links, delay, group):
    await asyncio.sleep(delay.total_seconds())
    if hasattr(client, 'generated_links') and group in client.generated_links:
        revoked_count = 0
        for channel_id_str, info in links.items():
            try:
                # Revoke the invite link
                # We need to pass both chat_id and invite_link
                await client.revoke_chat_invite_link(
                    chat_id=info['clean_id'],
                    invite_link=info['link']
                )
                revoked_count += 1
            except Exception as e:
                print(f"Error auto-revoking link for {info['name']}: {e}")
                continue
        
        print(f"Auto-revoked {revoked_count} links for group {group}")
        
        # Remove group from generated links
        if group in client.generated_links:
            del client.generated_links[group]

@Client.on_callback_query(filters.regex("^revoke_group_"))
async def revoke_group_links(client, callback_query: CallbackQuery):
    # Extract group from callback data
    group = callback_query.data.split("_")[-1]
    
    if not hasattr(client, 'generated_links') or group not in client.generated_links:
        await callback_query.answer(f"❌ No active links found for group {group}!", show_alert=True)
        return

    await callback_query.answer("⏳ Revoking links...")
    
    revoked = 0
    failed = 0
    links = client.generated_links[group]
    
    for channel_id_str, info in links.items():
        try:
            # Revoke the invite link
            await client.revoke_chat_invite_link(
                chat_id=info['clean_id'],
                invite_link=info['link']
            )
            revoked += 1
        except Exception as e:
            print(f"Error revoking link for {info['name']}: {e}")
            failed += 1
            continue

    # Update original message
    result_text = f"✅ <b>Revoked {revoked} links from group {group}</b>\n"
    if failed > 0:
        result_text += f"❌ <i>Failed to revoke {failed} links</i>\n"
    result_text += f"**All revoked links are now invalid**"
    
    await callback_query.message.send_message(
        result_text,
        reply_markup=None,
        disable_web_page_preview=True
    )
    
    # Remove group from generated links
    if group in client.generated_links:
        del client.generated_links[group]
