from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import ChatAdminRequired, ChatWriteForbidden, ChatRestricted, ChannelPrivate, UserNotParticipant
from plugins.helper.db import db
import time
import random
from plugins.helper.time_parser import *
import asyncio
from config import *
from plugins.Post.admin_panel import admin_filter

async def restore_pending_deletions(client):
    """Restore pending deletions when bot starts"""
    try:
        pending_posts = await db.get_pending_deletions()
        now = time.time()
        
        for post in pending_posts:
            post_id = post["post_id"]
            delete_after = post["delete_after"] - now
            
            if delete_after > 0:  # Only if deletion is in future
                channels = post.get("channels", [])
                deletion_tasks = []
                
                for channel in channels:
                    deletion_tasks.append(
                        schedule_deletion(
                            client,
                            channel["channel_id"],
                            channel["message_id"],
                            delete_after,
                            post["user_id"],
                            post_id,
                            channel.get("channel_name", str(channel["channel_id"])),
                            post.get("confirmation_msg_id")
                        )
                    )
                
                if deletion_tasks:
                    asyncio.create_task(
                        handle_deletion_results(
                            client=client,
                            deletion_tasks=deletion_tasks,
                            post_id=post_id,
                            delay_seconds=delete_after
                        )
                    )
    except Exception as e:
        print(f"Error restoring pending deletions: {e}")

async def schedule_deletion(client, channel_id, message_id, delay_seconds, user_id, post_id, channel_name, confirmation_msg_id):
    """Schedule a message for deletion after a delay"""
    await asyncio.sleep(delay_seconds)
    
    try:
        await client.delete_messages(
            chat_id=channel_id,
            message_ids=message_id
        )
        
        await db.remove_channel_post(post_id, channel_id)
        
        return {
            "status": "success",
            "channel_name": channel_name,
            "post_id": post_id,
            "user_id": user_id,
            "confirmation_msg_id": confirmation_msg_id
        }
        
    except Exception as e:
        return {
            "status": "failed",
            "channel_name": channel_name,
            "post_id": post_id,
            "error": str(e),
            "user_id": user_id,
            "confirmation_msg_id": confirmation_msg_id
        }

async def handle_deletion_results(client, deletion_tasks, post_id, delay_seconds):
    """Handle the results of all deletion tasks"""
    try:
        results = await asyncio.gather(*deletion_tasks, return_exceptions=True)
        
        success_count = 0
        failed_count = 0
        user_id = None
        confirmation_msg_id = None
        failed_deletions = []
        
        for result in results:
            if isinstance(result, Exception):
                failed_count += 1
                continue
                
            if user_id is None and result.get("user_id"):
                user_id = result["user_id"]
                confirmation_msg_id = result.get("confirmation_msg_id")
            
            if result.get("status") == "success":
                success_count += 1
            else:
                failed_count += 1
                failed_deletions.append(result)
        
        if user_id:
            if success_count > 0 and confirmation_msg_id:
                try:
                    await client.delete_messages(
                        chat_id=user_id,
                        message_ids=confirmation_msg_id
                    )
                except:
                    pass
            
            message_text = (
                f"<blockquote>🗑 <b>Post Auto-Deleted</b></blockquote>\n\n"
                f"• <b>Post ID:</b> <code>{post_id}</code>\n"
                f"• <b>Deleted from:</b> {success_count} channel(s)\n"
            )
            
            if failed_deletions:
                message_text += f"• <b>Failed to delete from:</b> {failed_count} channel(s)\n"
                if len(failed_deletions) <= 5:
                    message_text += "\n<b>Failed Channels:</b>\n"
                    for idx, fail in enumerate(failed_deletions, 1):
                        message_text += f"{idx}. {fail['channel_name']} - {fail.get('error', 'Unknown error')}\n"
            
            try:
                await client.send_message(user_id, message_text)
            except:
                pass

        if success_count > 0:
            remaining_channels = await db.get_post_channels(post_id)
            if not remaining_channels:
                await db.delete_post(post_id)
                
    except Exception as e:
        print(f"Error in handle_deletion_results: {e}")

def is_restricted_error(error_msg):
    """Check if error indicates a restricted channel"""
    if not error_msg:
        return False
    
    error_msg_lower = str(error_msg).lower()
    
    # Check for various error patterns that indicate restricted access
    restricted_patterns = [
        "chat_restricted",
        "chat_write_forbidden",
        "chat_admin_required",
        "channel_private",
        "user_not_participant",
        "forbidden",
        "restricted",
        "not allowed",
        "no rights",
        "no access",
        "bot was blocked",
        "bot kicked",
        "bot is not a member",
        "need administrator rights",
        "admin rights",
        "400",  # HTTP bad request often means permission issues
        "403",   # HTTP forbidden
        "message_",  # Pyrogram message errors often indicate permission issues
        "peermigrated",  # Channel migrated
        "channel_invalid",  # Invalid channel
        "username_not_occupied",  # Channel doesn't exist
        "username_invalid",  # Invalid username
        "channels_admin_required"  # Admin required in channels
    ]
    
    return any(pattern in error_msg_lower for pattern in restricted_patterns)

@Client.on_message(filters.command(["post", "post0", "post1", "post2", "post3"]) & filters.private & admin_filter)
async def send_post(client, message: Message):
    try:
        await message.react(emoji=random.choice(REACTIONS), big=True)
    except:
        pass
    
    if not await db.is_admin(message.from_user.id):
        await message.reply("**❌ You are not authorized to use this command!**")
        return
    
    if not message.reply_to_message:
        await message.reply("**Reply to a message to post it.**")
        return

    # Determine which group to post to (default 0)
    cmd = message.command[0]
    group = "0"  # Default group
    if len(cmd) > 4:  # For post1, post2, post3
        group = cmd[-1]  # Get the last character

    delete_after = None
    time_input = None
    if len(message.command) > 1:
        try:
            time_input = ' '.join(message.command[1:]).lower()
            delete_after = parse_time(time_input)
            if delete_after <= 0:
                await message.reply("❌ Time must be greater than 0")
                return
        except ValueError as e:
            await message.reply(f"❌ {str(e)}\nExample: /post 1h 30min or /post 2 hours 15 minutes")
            return

    post_content = message.reply_to_message
    channels = await db.get_channels_by_group(group)  # Get channels from specific group

    if not channels:
        await message.reply(f"**No channels connected in group {group} yet.**")
        return

    post_id = int(time.time())
    sent_messages = []
    success_count = 0
    total_channels = len(channels)
    failed_channels = []
    restricted_channels = []  # Track restricted channels separately

    processing_msg = await message.reply(
        f"**📢 Posting to {total_channels} channels in group {group}...**",
        reply_to_message_id=post_content.id
    )

    deletion_tasks = []
    
    for channel in channels:
        try:
            sent_message = await client.copy_message(
                chat_id=channel["channel_id"],
                from_chat_id=message.chat.id,
                message_id=post_content.id
            )

            sent_messages.append({
                "channel_id": channel["channel_id"],
                "message_id": sent_message.id,
                "channel_name": channel.get("name", str(channel["channel_id"]))
            })
            success_count += 1

            if delete_after:
                deletion_tasks.append(
                    schedule_deletion(
                        client,
                        channel["channel_id"],
                        sent_message.id,
                        delete_after,
                        message.from_user.id,
                        post_id,
                        channel.get("name", str(channel["channel_id"])),
                        processing_msg.id
                    )
                )
                
        except Exception as e:
            error_msg = str(e)
            channel_name = channel.get("name", str(channel["channel_id"]))
            
            # Check if error is due to restricted channel
            is_restricted = is_restricted_error(error_msg)
            
            channel_data = {
                "channel_id": channel["channel_id"],
                "channel_name": channel_name,
                "error": error_msg[:200],
                "is_restricted": is_restricted,
                "full_error": error_msg
            }
            
            if is_restricted:
                restricted_channels.append({
                    "channel_id": channel["channel_id"],
                    "channel_name": channel_name,
                    "error": "Restricted/Bot not admin",
                    "group": group
                })
            
            failed_channels.append(channel_data)

    # Save post with deletion info if needed
    post_data = {
        "post_id": post_id,
        "channels": sent_messages,
        "user_id": message.from_user.id,
        "confirmation_msg_id": processing_msg.id,
        "created_at": time.time(),
        "group": group,
        "failed_channels": failed_channels,  # Store failed channels
        "restricted_channels": restricted_channels  # Store restricted channels separately
    }
    
    if delete_after:
        post_data["delete_after"] = time.time() + delete_after
        post_data["delete_original"] = True
    
    await db.save_post(post_data)

    result_msg = (
        f"<blockquote>📣 <b>Posting Completed!</b></blockquote>\n\n"
        f"• <b>Group:</b> {group}\n"
        f"• <b>Post ID:</b> <code>{post_id}</code>\n"
        f"• <b>Success:</b> {success_count}/{total_channels} channels\n"
    )
    
    if delete_after:
        time_str = format_time(delete_after)
        result_msg += f"• <b>Auto-delete in:</b> {time_str}\n"

    if failed_channels:
        result_msg += f"• <b>Failed:</b> {len(failed_channels)} channels\n"
        
        # Count restricted channels
        restricted_count = sum(1 for c in failed_channels if c.get("is_restricted"))
        if restricted_count > 0:
            result_msg += f"• <b>Restricted:</b> {restricted_count} channel(s) (Bot not admin)\n\n"
        else:
            result_msg += "\n"
        
        if len(failed_channels) <= 10:
            result_msg += "<b>Failed Channels:</b>\n"
            for idx, channel in enumerate(failed_channels, 1):
                error_type = "🔒 RESTRICTED" if channel.get("is_restricted") else "❌ Error"
                error_text = channel.get("error", "Unknown error")
                result_msg += f"{idx}. {channel['channel_name']} - {error_type}: {error_text}\n"
        else:
            result_msg += "<i>Too many failed channels to display (see logs for details)</i>\n"

    # Create buttons - ALWAYS show remove failed channels button if there are failed channels
    buttons = []
    
    # Delete post button
    buttons.append([InlineKeyboardButton("🗑 Delete This Post", callback_data=f"delete_{post_id}")])
    
    # ALWAYS show remove failed channels button if there are ANY failed channels
    if failed_channels:
        # Show "Remove Failed Channels" button
        buttons.append([InlineKeyboardButton("🔧 Remove Failed Channels", 
                                           callback_data=f"remove_failed_{post_id}_{group}")])

    reply_markup = InlineKeyboardMarkup(buttons)

    await processing_msg.edit_text(result_msg, reply_markup=reply_markup)

    try:
        log_msg = (
            f"📢 <blockquote><b>#Post | Group {group} | @Interferons_bot</b></blockquote>\n\n"
            f"👤 <b>Posted By:</b> {message.from_user.mention}\n"
            f"📌 <b>Post ID:</b> <code>{post_id}</code>\n"
            f"📡 <b>Sent to:</b> {success_count}/{total_channels} channels\n"
            f"⏳ <b>Auto-delete:</b> {time_str if delete_after else 'No'}\n"
        )
        
        if failed_channels:
            log_msg += f"\n❌ <b>Failed Channels ({len(failed_channels)}):</b>\n"
            for channel in failed_channels[:15]:
                error_type = "RESTRICTED" if channel.get("is_restricted") else "ERROR"
                log_msg += f"  - {channel['channel_name']}: {error_type} - {channel.get('error', 'Unknown')}\n"
            if len(failed_channels) > 15:
                log_msg += f"  ...and {len(failed_channels)-15} more"
        
        await client.send_message(
            chat_id=LOG_CHANNEL,
            text=log_msg
        )    
    except Exception as e:
        print(f"Error sending confirmation to log channel: {e}")

    if delete_after and deletion_tasks:
        asyncio.create_task(
            handle_deletion_results(
                client=client,
                deletion_tasks=deletion_tasks,
                post_id=post_id,
                delay_seconds=delete_after
            )
        )

@Client.on_message(filters.command(["fpost", "fpost0", "fpost1", "fpost2", "fpost3"]) & filters.private & admin_filter)
async def forward_post(client, message: Message):
    try:
        await message.react(emoji=random.choice(REACTIONS), big=True)
    except:
        pass
    
    if not message.reply_to_message:
        await message.reply("**Reply to a message to forward it.**")
        return

    # Determine which group to post to (default 0)
    cmd = message.command[0]
    group = "0"  # Default group
    if len(cmd) > 5:  # For fpost1, fpost2, fpost3
        group = cmd[-1]  # Get the last character

    delete_after = None
    time_input = None
    if len(message.command) > 1:
        try:
            time_input = ' '.join(message.command[1:]).lower()
            delete_after = parse_time(time_input)
            if delete_after <= 0:
                await message.reply("❌ Time must be greater than 0")
                return
        except ValueError as e:
            await message.reply(f"❌ {str(e)}\nExample: /fpost 1h 30min or /fpost 2 hours 15 minutes")
            return

    post_content = message.reply_to_message
    channels = await db.get_channels_by_group(group)  # Get channels from specific group

    if not channels:
        await message.reply(f"**No channels connected in group {group} yet.**")
        return

    post_id = int(time.time())
    sent_messages = []
    success_count = 0
    total_channels = len(channels)
    failed_channels = []
    restricted_channels = []  # Track restricted channels separately

    processing_msg = await message.reply(
        f"**📢 Forwarding to {total_channels} channels in group {group}...**",
        reply_to_message_id=post_content.id
    )

    deletion_tasks = []
    
    for channel in channels:
        try:
            sent_message = await client.forward_messages(
                chat_id=channel["channel_id"],
                from_chat_id=message.chat.id,
                message_ids=post_content.id
            )

            sent_messages.append({
                "channel_id": channel["channel_id"],
                "message_id": sent_message.id,
                "channel_name": channel.get("name", str(channel["channel_id"]))
            })
            success_count += 1

            if delete_after:
                deletion_tasks.append(
                    schedule_deletion(
                        client,
                        channel["channel_id"],
                        sent_message.id,
                        delete_after,
                        message.from_user.id,
                        post_id,
                        channel.get("name", str(channel["channel_id"])),
                        processing_msg.id
                    )
                )
                
        except Exception as e:
            error_msg = str(e)
            channel_name = channel.get("name", str(channel["channel_id"]))
            
            # Check if error is due to restricted channel
            is_restricted = is_restricted_error(error_msg)
            
            channel_data = {
                "channel_id": channel["channel_id"],
                "channel_name": channel_name,
                "error": error_msg[:200],
                "is_restricted": is_restricted,
                "full_error": error_msg
            }
            
            if is_restricted:
                restricted_channels.append({
                    "channel_id": channel["channel_id"],
                    "channel_name": channel_name,
                    "error": "Restricted/Bot not admin",
                    "group": group
                })
            
            failed_channels.append(channel_data)

    post_data = {
        "post_id": post_id,
        "channels": sent_messages,
        "user_id": message.from_user.id,
        "confirmation_msg_id": processing_msg.id,
        "created_at": time.time(),
        "is_forward": True,
        "group": group,
        "failed_channels": failed_channels,  # Store failed channels
        "restricted_channels": restricted_channels  # Store restricted channels separately
    }
    
    if delete_after:
        post_data["delete_after"] = time.time() + delete_after
        post_data["delete_original"] = True
    
    await db.save_post(post_data)

    result_msg = (
        f"<blockquote>📣 <b>Forwarding Completed!</b></blockquote>\n\n"
        f"• <b>Group:</b> {group}\n"
        f"• <b>Post ID:</b> <code>{post_id}</code>\n"
        f"• <b>Success:</b> {success_count}/{total_channels} channels\n"
    )
    
    if delete_after:
        time_str = format_time(delete_after)
        result_msg += f"• <b>Auto-delete in:</b> {time_str}\n"

    if failed_channels:
        result_msg += f"• <b>Failed:</b> {len(failed_channels)} channels\n"
        
        # Count restricted channels
        restricted_count = sum(1 for c in failed_channels if c.get("is_restricted"))
        if restricted_count > 0:
            result_msg += f"• <b>Restricted:</b> {restricted_count} channel(s) (Bot not admin)\n\n"
        else:
            result_msg += "\n"
        
        if len(failed_channels) <= 10:
            result_msg += "<b>Failed Channels:</b>\n"
            for idx, channel in enumerate(failed_channels, 1):
                error_type = "🔒 RESTRICTED" if channel.get("is_restricted") else "❌ Error"
                error_text = channel.get("error", "Unknown error")
                result_msg += f"{idx}. {channel['channel_name']} - {error_type}: {error_text}\n"
        else:
            result_msg += "<i>Too many failed channels to display (see logs for details)</i>\n"

    # Create buttons
    buttons = []
    
    # Delete post button
    buttons.append([InlineKeyboardButton("🗑 Delete This Post", callback_data=f"delete_{post_id}")])
    
    # ALWAYS show remove failed channels button if there are ANY failed channels
    if failed_channels:
        # Show "Remove Failed Channels" button
        buttons.append([InlineKeyboardButton("🔧 Remove Failed Channels", 
                                           callback_data=f"remove_failed_{post_id}_{group}")])

    reply_markup = InlineKeyboardMarkup(buttons)

    await processing_msg.edit_text(result_msg, reply_markup=reply_markup)

    try:
        log_msg = (
            f"📢 <blockquote><b>#FPost | Group {group} | @Interferons_bot</b></blockquote>\n\n"
            f"👤 <b>Forwarded By:</b> {message.from_user.mention}\n"
            f"📌 <b>Post ID:</b> <code>{post_id}</code>\n"
            f"📡 <b>Sent to:</b> {success_count}/{total_channels} channels\n"
            f"⏳ <b>Auto-delete:</b> {time_str if delete_after else 'No'}\n"
        )
        
        if failed_channels:
            log_msg += f"\n❌ <b>Failed Channels ({len(failed_channels)}):</b>\n"
            for channel in failed_channels[:15]:
                error_type = "RESTRICTED" if channel.get("is_restricted") else "ERROR"
                log_msg += f"  - {channel['channel_name']}: {error_type} - {channel.get('error', 'Unknown')}\n"
            if len(failed_channels) > 15:
                log_msg += f"  ...and {len(failed_channels)-15} more"
        
        await client.send_message(
            chat_id=LOG_CHANNEL,
            text=log_msg
        )    
    except Exception as e:
        print(f"Error sending confirmation to log channel: {e}")

    if delete_after and deletion_tasks:
        asyncio.create_task(
            handle_deletion_results(
                client=client,
                deletion_tasks=deletion_tasks,
                post_id=post_id,
                delay_seconds=delete_after
            )
        )

# Callback handler for removing failed channels
@Client.on_callback_query(filters.regex(r"^remove_failed_"))
async def remove_failed_channels_handler(client, callback_query: CallbackQuery):
    await callback_query.answer("Removing failed channels...")
    
    try:
        # Parse callback data
        data = callback_query.data.split("_")
        if len(data) != 4:
            await callback_query.message.edit_text("❌ Invalid callback data.")
            return
        
        post_id = int(data[2])
        group = data[3]
        
        # Get the post to find failed channels
        post = await db.get_post(post_id)
        if not post:
            await callback_query.message.edit_text("❌ Post not found.")
            return
        
        # Get failed channels from the post
        failed_channels = post.get("failed_channels", [])
        if not failed_channels:
            await callback_query.message.edit_text("❌ No failed channels found for this post.")
            return
        
        # Remove failed channels from database
        removed_channels = []
        failed_removals = []
        
        for channel in failed_channels:
            try:
                # Remove channel from specific group
                await db.delete_channel(channel["channel_id"], group)
                removed_channels.append(channel["channel_name"])
            except Exception as e:
                failed_removals.append({
                    "channel_name": channel["channel_name"],
                    "error": str(e)[:100]
                })
        
        # Update confirmation message
        result_msg = (
            f"<blockquote>🔧 <b>Failed Channels Removed</b></blockquote>\n\n"
            f"• <b>Group:</b> {group}\n"
            f"• <b>Post ID:</b> <code>{post_id}</code>\n"
            f"• <b>Removed:</b> {len(removed_channels)} channel(s)\n"
        )
        
        if removed_channels:
            result_msg += "\n<b>Removed Channels:</b>\n"
            for idx, channel_name in enumerate(removed_channels, 1):
                result_msg += f"{idx}. {channel_name}\n"
        
        if failed_removals:
            result_msg += f"\n<b>Failed to remove:</b> {len(failed_removals)} channel(s)\n"
            for idx, fail in enumerate(failed_removals[:5], 1):
                result_msg += f"{idx}. {fail['channel_name']} - {fail['error']}\n"
        
        # Remove the button after action
        buttons = [
            [InlineKeyboardButton("🗑 Delete This Post", callback_data=f"delete_{post_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        await callback_query.message.edit_text(result_msg, reply_markup=reply_markup)
        
        # Log the action
        try:
            log_msg = (
                f"🔧 <blockquote><b>Failed Channels Removed</b></blockquote>\n\n"
                f"👤 <b>Action By:</b> {callback_query.from_user.mention}\n"
                f"📌 <b>Post ID:</b> <code>{post_id}</code>\n"
                f"📌 <b>Group:</b> {group}\n"
                f"🗑 <b>Removed:</b> {len(removed_channels)} channel(s)\n"
            )
            
            if removed_channels:
                log_msg += "\n<b>Removed Channels:</b>\n"
                for channel_name in removed_channels[:10]:
                    log_msg += f"  - {channel_name}\n"
            
            await client.send_message(
                chat_id=LOG_CHANNEL,
                text=log_msg
            )
        except Exception as e:
            print(f"Error logging failed channels removal: {e}")
            
    except Exception as e:
        await callback_query.message.edit_text(f"❌ Error: {str(e)[:200]}")
        print(f"Error in remove_failed_channels_handler: {e}")

# Callback handler for deleting posts (existing functionality)
@Client.on_callback_query(filters.regex(r"^delete_"))
async def delete_post_callback(client, callback_query: CallbackQuery):
    await callback_query.answer()
    
    post_id = int(callback_query.data.split("_")[1])
    post = await db.get_post(post_id)
    
    if not post:
        await callback_query.message.edit_text("❌ Post not found.")
        return
    
    # Check if user is admin
    if not await db.is_admin(callback_query.from_user.id):
        await callback_query.message.edit_text("❌ You are not authorized to delete this post.")
        return
    
    # Delete messages from all channels
    channels = post.get("channels", [])
    deleted_count = 0
    failed_deletions = []
    
    for channel in channels:
        try:
            await client.delete_messages(
                chat_id=channel["channel_id"],
                message_ids=channel["message_id"]
            )
            deleted_count += 1
        except Exception as e:
            failed_deletions.append({
                "channel_name": channel.get("channel_name", str(channel["channel_id"])),
                "error": str(e)[:100]
            })
    
    # Delete post from database
    await db.delete_post(post_id)
    
    result_msg = (
        f"<blockquote>🗑 <b>Post Deleted</b></blockquote>\n\n"
        f"• <b>Post ID:</b> <code>{post_id}</code>\n"
        f"• <b>Deleted from:</b> {deleted_count}/{len(channels)} channel(s)\n"
    )
    
    if failed_deletions:
        result_msg += f"• <b>Failed to delete from:</b> {len(failed_deletions)} channel(s)\n"
        if len(failed_deletions) <= 5:
            result_msg += "\n<b>Failed Channels:</b>\n"
            for idx, fail in enumerate(failed_deletions, 1):
                result_msg += f"{idx}. {fail['channel_name']} - {fail['error']}\n"
    
    await callback_query.message.edit_text(result_msg)
