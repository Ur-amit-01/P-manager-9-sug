from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from plugins.helper.db import db
import time
import random
import asyncio
from config import *
from plugins.Post.admin_panel import admin_filter

# Command to add the current channel to the database
@Client.on_message(filters.command(["add", "add1", "add2", "add3"]) & filters.channel)
async def add_current_channel(client, message: Message):
    channel_id = message.chat.id
    channel_name = message.chat.title
    group = message.command[0].replace("add", "") or "0"  # "add" becomes "0", "add1" becomes "1", etc.

    try:
        added = await db.add_channel(channel_id, channel_name, group)
        if added:
            await message.reply(f"**Channel '{channel_name}' added to group {group}! ✅**")
        else:
            await message.reply(f"ℹ️ Channel '{channel_name}' already exists in group {group}.")
    except Exception as e:
        print(f"Error adding channel: {e}")
        await message.reply("❌ Failed to add channel. Contact developer.")

@Client.on_message(filters.command(["rem", "rem1", "rem2", "rem3"]) & filters.channel)
async def remove_current_channel(client, message: Message):
    channel_id = message.chat.id
    channel_name = message.chat.title
    group = message.command[0].replace("rem", "") or "0"  # "rem" becomes "0", "rem1" becomes "1", etc.

    try:
        if await db.is_channel_exist(channel_id, group):
            await db.delete_channel(channel_id, group)
            await message.reply(f"**Channel '{channel_name}' removed from group {group}!**")
        else:
            await message.reply(f"ℹ️ Channel '{channel_name}' not found in group {group}.")
    except Exception as e:
        print(f"Error removing channel: {e}")
        await message.reply("❌ Failed to remove channel. Try again.")

@Client.on_message(filters.command(["channels", "channels1", "channels2", "channels3"]) & filters.private & admin_filter)
async def list_channels(client, message: Message):
    try:
        await message.react(emoji=random.choice(REACTIONS), big=True)
    except:
        pass
    
    if not await db.is_admin(message.from_user.id):
        await message.reply("**❌ You are not authorized to use this command!**")
        return
    
    group = "0"  # Default for "channels"
    if len(message.command[0]) > 8:  # If it's channels1, channels2, etc.
        group = message.command[0][-1]  # Get the last character
    
    # Get channels from database
    channels = await db.get_channels_by_group(group)

    if not channels:
        await message.reply(f"**No channels in group {group} yet.🙁**")
        return

    total_channels = len(channels)
    header = f"> **Channels in group {group} :- ({total_channels})**\n\n"
    messages = []
    current_message = header
    
    # Counter for numbering channels
    counter = 1
    
    for channel_data in channels:
        try:
            # Extract channel ID from stored format (e.g., "-1002163011245_0")
            channel_id_str = str(channel_data['_id'])
            
            # Split to get the actual channel ID (remove the "_group" suffix)
            if '_' in channel_id_str:
                actual_channel_id = int(channel_id_str.split('_')[0])
            else:
                actual_channel_id = int(channel_id_str)
            
            # Try to fetch current channel info
            try:
                chat = await client.get_chat(actual_channel_id)
                channel_name = chat.title
                channel_username = f"@{chat.username}" if chat.username else "No username"
                channel_info = f"{channel_name}"
            except Exception as e:
                print(f"Error fetching channel {actual_channel_id}: {e}")
                channel_info = "Unknown Channel"
                
            # Add to message
            line = f"**{counter}. {channel_info}**\n🆔 : `{actual_channel_id}`\n"
            
            if len(current_message) + len(line) + 1 > 4096:
                messages.append(current_message)
                current_message = ""
            current_message += line + "\n"
            
            counter += 1
            
            # Small delay to avoid flood limits
            #await asyncio.sleep(0.1)
            
        except Exception as e:
            print(f"Error processing channel: {e}")
            # Fallback to stored data if available
            if 'name' in channel_data:
                line = f"**{counter}. {channel_data['name']}** (Fetch failed)\n   `{channel_data['_id']}`\n"
                if len(current_message) + len(line) + 1 > 4096:
                    messages.append(current_message)
                    current_message = ""
                current_message += line + "\n"
                counter += 1

    if current_message and current_message.strip():
        messages.append(current_message)

    # Send all messages
    if not messages:
        await message.reply(f"**No valid channels found in group {group}.**")
        return
        
    for part in messages:
        await message.reply(part)
        await asyncio.sleep(0.5)  # Small delay between messages
