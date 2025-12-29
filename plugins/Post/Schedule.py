# plugins/Post/schedule.py
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import ChatAdminRequired, ChatWriteForbidden, ChatRestricted, ChannelPrivate, UserNotParticipant
from plugins.helper.db import db
import time
import random
from plugins.helper.time_parser import parse_time, format_time
import asyncio
from datetime import datetime, timedelta
from config import *
from plugins.Post.admin_panel import admin_filter
from plugins.Post.posting import schedule_deletion, handle_deletion_results, is_restricted_error

# Import necessary functions from posting.py
# Make sure these functions exist in posting.py or define them here

async def parse_schedule_time(time_input: str):
    """Parse schedule time string like '09:00,14:30,18:45' or '9am,2pm,6:30pm'"""
    times = []
    for t in time_input.split(','):
        t = t.strip().lower()
        
        # Handle formats like "9am", "2pm"
        if 'am' in t or 'pm' in t:
            try:
                # Remove am/pm and any spaces
                t_clean = t.replace('am', '').replace('pm', '').strip()
                if ':' in t_clean:
                    hour, minute = t_clean.split(':')
                    hour = int(hour)
                    minute = int(minute)
                else:
                    hour = int(t_clean)
                    minute = 0
                
                # Adjust for pm
                if 'pm' in t and hour != 12:
                    hour += 12
                # Adjust for 12am
                elif 'am' in t and hour == 12:
                    hour = 0
                
                times.append(f"{hour:02d}:{minute:02d}")
            except:
                raise ValueError(f"Invalid time format: {t}")
        
        # Handle 24-hour format like "09:00", "14:30"
        elif ':' in t:
            try:
                hour, minute = t.split(':')
                hour = int(hour)
                minute = int(minute)
                
                if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                    raise ValueError(f"Invalid time: {t}")
                
                times.append(f"{hour:02d}:{minute:02d}")
            except:
                raise ValueError(f"Invalid time format: {t}")
        else:
            raise ValueError(f"Invalid time format: {t}")
    
    return times

async def get_next_run_time(schedule_times):
    """Get the next scheduled time from now"""
    now = datetime.now()
    current_time_str = now.strftime("%H:%M")
    
    # Sort times
    sorted_times = sorted(schedule_times)
    
    # Find next time today
    for schedule_time in sorted_times:
        if schedule_time > current_time_str:
            return schedule_time
    
    # If no more times today, use first time tomorrow
    return sorted_times[0]

async def calculate_delay_until(schedule_time_str):
    """Calculate seconds until scheduled time"""
    now = datetime.now()
    
    # Parse scheduled time
    hour, minute = map(int, schedule_time_str.split(':'))
    scheduled_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    # If scheduled time is in the past today, schedule for tomorrow
    if scheduled_time < now:
        scheduled_time += timedelta(days=1)
    
    # Calculate delay in seconds
    delay = (scheduled_time - now).total_seconds()
    return max(1, delay)  # Ensure at least 1 second

async def execute_scheduled_post(client, schedule_id):
    """Execute a scheduled post"""
    try:
        schedule = await db.get_schedule(schedule_id)
        if not schedule:
            return
        
        post_content = schedule.get("message_data")
        group = schedule.get("group", "0")
        is_forward = schedule.get("is_forward", False)
        user_id = schedule.get("user_id")
        delete_after = schedule.get("delete_after")
        schedule_times = schedule.get("schedule_times", [])
        
        if not post_content:
            return
        
        # Get channels for the group
        channels = await db.get_channels_by_group(group)
        if not channels:
            # Update schedule status
            await db.update_schedule(schedule_id, {"last_error": "No channels in group"})
            return
        
        post_id = int(time.time())
        sent_messages = []
        success_count = 0
        total_channels = len(channels)
        failed_channels = []
        restricted_channels = []
        
        deletion_tasks = []
        
        for channel in channels:
            try:
                if is_forward:
                    sent_message = await client.forward_messages(
                        chat_id=channel["channel_id"],
                        from_chat_id=user_id,
                        message_ids=post_content.get("message_id")
                    )
                else:
                    sent_message = await client.copy_message(
                        chat_id=channel["channel_id"],
                        from_chat_id=post_content.get("from_chat_id", user_id),
                        message_id=post_content.get("message_id")
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
                            user_id,
                            post_id,
                            channel.get("name", str(channel["channel_id"])),
                            None  # No confirmation message for scheduled posts
                        )
                    )
                    
            except Exception as e:
                error_msg = str(e)
                channel_name = channel.get("name", str(channel["channel_id"]))
                
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
                        "error": "Restricted/Bot not admin"
                    })
                
                failed_channels.append(channel_data)
        
        # Save post data
        post_data = {
            "post_id": post_id,
            "channels": sent_messages,
            "user_id": user_id,
            "created_at": time.time(),
            "is_forward": is_forward,
            "group": group,
            "failed_channels": failed_channels,
            "restricted_channels": restricted_channels,
            "is_scheduled": True,
            "schedule_id": schedule_id
        }
        
        if delete_after:
            post_data["delete_after"] = time.time() + delete_after
            post_data["delete_original"] = True
        
        await db.save_post(post_data)
        
        # Update schedule with last run info
        await db.update_schedule(schedule_id, {
            "last_run": time.time(),
            "last_success": success_count,
            "last_failed": len(failed_channels),
            "last_post_id": post_id
        })
        
        # Log the scheduled post execution
        try:
            log_msg = (
                f"⏰ <blockquote><b>#ScheduledPost Executed | Group {group}</b></blockquote>\n\n"
                f"📌 <b>Schedule ID:</b> <code>{schedule_id}</code>\n"
                f"📌 <b>Post ID:</b> <code>{post_id}</code>\n"
                f"📡 <b>Sent to:</b> {success_count}/{total_channels} channels\n"
                f"🕐 <b>Scheduled Times:</b> {', '.join(schedule_times)}\n"
            )
            
            if failed_channels:
                log_msg += f"\n❌ <b>Failed Channels ({len(failed_channels)}):</b>\n"
                for channel in failed_channels[:10]:
                    error_type = "RESTRICTED" if channel.get("is_restricted") else "ERROR"
                    log_msg += f"  - {channel['channel_name']}: {error_type}\n"
            
            await client.send_message(
                chat_id=LOG_CHANNEL,
                text=log_msg
            )
        except:
            pass
        
        # Handle deletions if needed
        if delete_after and deletion_tasks:
            asyncio.create_task(
                handle_deletion_results(
                    client=client,
                    deletion_tasks=deletion_tasks,
                    post_id=post_id,
                    delay_seconds=delete_after
                )
            )
        
        # Schedule next execution
        next_time = await get_next_run_time(schedule_times)
        delay_seconds = await calculate_delay_until(next_time)
        
        asyncio.create_task(
            schedule_next_post(client, schedule_id, delay_seconds)
        )
        
    except Exception as e:
        print(f"Error executing scheduled post {schedule_id}: {e}")
        await db.update_schedule(schedule_id, {"last_error": str(e)[:200]})

async def schedule_next_post(client, schedule_id, delay_seconds):
    """Schedule the next execution of a post"""
    await asyncio.sleep(delay_seconds)
    await execute_scheduled_post(client, schedule_id)

async def restore_scheduled_posts(client):
    """Restore scheduled posts when bot starts"""
    try:
        schedules = await db.get_all_schedules()
        now = datetime.now()
        
        for schedule in schedules:
            if schedule.get("status") != "active":
                continue
            
            schedule_times = schedule.get("schedule_times", [])
            if not schedule_times:
                continue
            
            # Calculate delay until next scheduled time
            next_time = await get_next_run_time(schedule_times)
            delay_seconds = await calculate_delay_until(next_time)
            
            # Schedule next execution
            asyncio.create_task(
                schedule_next_post(client, schedule["schedule_id"], delay_seconds)
            )
            
    except Exception as e:
        print(f"Error restoring scheduled posts: {e}")

# Add schedule command handler
@Client.on_message(filters.command(["schedule", "schedule0", "schedule1", "schedule2", "schedule3"]) & filters.private & admin_filter)
async def schedule_post(client, message: Message):
    try:
        await message.react(emoji=random.choice(REACTIONS), big=True)
    except:
        pass
    
    if not await db.is_admin(message.from_user.id):
        await message.reply("**❌ You are not authorized to use this command!**")
        return
    
    if not message.reply_to_message:
        await message.reply("**Reply to a message to schedule it.**")
        return
    
    # Determine which group to post to
    cmd = message.command[0]
    group = "0"  # Default group
    if len(cmd) > 8:  # For schedule1, schedule2, schedule3
        group = cmd[-1]
    
    # Parse schedule times (required)
    if len(message.command) < 2:
        await message.reply(
            "**❌ Please specify schedule times!**\n\n"
            "**Format:** `/schedule 09:00,14:30,18:45`\n"
            "**Or:** `/schedule 9am,2pm,6:30pm`\n\n"
            "**Example:** `/schedule1 09:00,21:00`\n"
            "**Example:** `/schedule2 8am,12pm,4pm,8pm`"
        )
        return
    
    time_input = ' '.join(message.command[1:])
    
    # Parse schedule times
    try:
        schedule_times = await parse_schedule_time(time_input)
    except ValueError as e:
        await message.reply(
            f"**❌ Invalid time format!**\n\n"
            f"Error: {str(e)}\n\n"
            "**Valid formats:**\n"
            "• `09:00,14:30,18:45` (24-hour)\n"
            "• `9am,2pm,6:30pm` (12-hour)\n"
            "• `08:00,12:00,16:00,20:00`\n\n"
            "**Example:** `/schedule 9am,6pm`"
        )
        return
    
    # Parse auto-delete time (optional)
    delete_after = None
    if len(message.command) > 2:
        try:
            delete_input = ' '.join(message.command[2:])
            delete_after = parse_time(delete_input)
            if delete_after <= 0:
                await message.reply("❌ Auto-delete time must be greater than 0")
                return
        except ValueError as e:
            await message.reply(f"❌ Invalid auto-delete time: {str(e)}")
            return
    
    # Check if forward or copy
    is_forward = message.text.startswith("/fschedule") or "forward" in message.text.lower()
    
    # Store message data for scheduling
    post_content = message.reply_to_message
    message_data = {
        "message_id": post_content.id,
        "from_chat_id": post_content.chat.id,
        "date": post_content.date,
        "media": bool(post_content.media),
        "text": post_content.text.html if post_content.text else "",
        "caption": post_content.caption.html if post_content.caption else ""
    }
    
    # Create schedule
    schedule_id = int(time.time())
    schedule_data = {
        "schedule_id": schedule_id,
        "user_id": message.from_user.id,
        "group": group,
        "schedule_times": schedule_times,
        "message_data": message_data,
        "is_forward": is_forward,
        "status": "active",
        "created_at": time.time(),
        "delete_after": delete_after
    }
    
    # Save schedule to database
    await db.save_schedule(schedule_data)
    
    # Calculate next run time
    next_time = await get_next_run_time(schedule_times)
    delay_seconds = await calculate_delay_until(next_time)
    next_run_str = (datetime.now() + timedelta(seconds=delay_seconds)).strftime("%Y-%m-%d %H:%M")
    
    # Schedule the first post
    asyncio.create_task(
        schedule_next_post(client, schedule_id, delay_seconds)
    )
    
    # Send confirmation
    result_msg = (
        f"<blockquote>⏰ <b>Post Scheduled!</b></blockquote>\n\n"
        f"• <b>Schedule ID:</b> <code>{schedule_id}</code>\n"
        f"• <b>Group:</b> {group}\n"
        f"• <b>Type:</b> {'Forward' if is_forward else 'Copy'}\n"
        f"• <b>Schedule Times:</b> {', '.join(schedule_times)}\n"
        f"• <b>Next Run:</b> {next_run_str}\n"
    )
    
    if delete_after:
        time_str = format_time(delete_after)
        result_msg += f"• <b>Auto-delete after:</b> {time_str}\n"
    
    # Add management buttons
    buttons = [
        [InlineKeyboardButton("⏸ Pause Schedule", callback_data=f"pause_schedule_{schedule_id}"),
         InlineKeyboardButton("❌ Delete Schedule", callback_data=f"delete_schedule_{schedule_id}")],
        [InlineKeyboardButton("📋 List Schedules", callback_data="list_schedules")]
    ]
    
    reply_markup = InlineKeyboardMarkup(buttons)
    
    processing_msg = await message.reply(
        f"**⏰ Scheduling post for group {group}...**",
        reply_to_message_id=post_content.id
    )
    
    await processing_msg.edit_text(result_msg, reply_markup=reply_markup)
    
    # Log to log channel
    try:
        log_msg = (
            f"⏰ <blockquote><b>#ScheduleCreated | Group {group}</b></blockquote>\n\n"
            f"👤 <b>Scheduled By:</b> {message.from_user.mention}\n"
            f"📌 <b>Schedule ID:</b> <code>{schedule_id}</code>\n"
            f"📋 <b>Type:</b> {'Forward' if is_forward else 'Copy'}\n"
            f"🕐 <b>Times:</b> {', '.join(schedule_times)}\n"
            f"⏳ <b>Next Run:</b> {next_run_str}\n"
            f"🗑 <b>Auto-delete:</b> {format_time(delete_after) if delete_after else 'No'}\n"
        )
        
        await client.send_message(
            chat_id=LOG_CHANNEL,
            text=log_msg
        )
    except Exception as e:
        print(f"Error sending schedule log: {e}")

# Add forward schedule command
@Client.on_message(filters.command(["fschedule", "fschedule0", "fschedule1", "fschedule2", "fschedule3"]) & filters.private & admin_filter)
async def forward_schedule_post(client, message: Message):
    # Just modify the message text to indicate it's a forward and call schedule_post
    message.text = message.text.replace("/fschedule", "/schedule forward")
    await schedule_post(client, message)

# Add callback handlers for schedule management
@Client.on_callback_query(filters.regex(r"^pause_schedule_"))
async def pause_schedule_handler(client, callback_query: CallbackQuery):
    await callback_query.answer()
    
    schedule_id = int(callback_query.data.split("_")[2])
    
    # Update schedule status
    await db.update_schedule(schedule_id, {"status": "paused"})
    
    await callback_query.message.edit_text(
        f"✅ <b>Schedule Paused</b>\n\n"
        f"• <b>Schedule ID:</b> <code>{schedule_id}</code>\n\n"
        f"Use /listschedules to see all schedules.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("▶ Resume", callback_data=f"resume_schedule_{schedule_id}"),
             InlineKeyboardButton("❌ Delete", callback_data=f"delete_schedule_{schedule_id}")]
        ])
    )

@Client.on_callback_query(filters.regex(r"^resume_schedule_"))
async def resume_schedule_handler(client, callback_query: CallbackQuery):
    await callback_query.answer()
    
    schedule_id = int(callback_query.data.split("_")[2])
    schedule = await db.get_schedule(schedule_id)
    
    if not schedule:
        await callback_query.message.edit_text("❌ Schedule not found.")
        return
    
    # Update schedule status
    await db.update_schedule(schedule_id, {"status": "active"})
    
    # Calculate next run time and schedule
    schedule_times = schedule.get("schedule_times", [])
    next_time = await get_next_run_time(schedule_times)
    delay_seconds = await calculate_delay_until(next_time)
    next_run_str = (datetime.now() + timedelta(seconds=delay_seconds)).strftime("%Y-%m-%d %H:%M")
    
    asyncio.create_task(
        schedule_next_post(client, schedule_id, delay_seconds)
    )
    
    await callback_query.message.edit_text(
        f"✅ <b>Schedule Resumed</b>\n\n"
        f"• <b>Schedule ID:</b> <code>{schedule_id}</code>\n"
        f"• <b>Next Run:</b> {next_run_str}\n\n"
        f"Schedule times: {', '.join(schedule_times)}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏸ Pause", callback_data=f"pause_schedule_{schedule_id}"),
             InlineKeyboardButton("❌ Delete", callback_data=f"delete_schedule_{schedule_id}")]
        ])
    )

@Client.on_callback_query(filters.regex(r"^delete_schedule_"))
async def delete_schedule_handler(client, callback_query: CallbackQuery):
    await callback_query.answer()
    
    schedule_id = int(callback_query.data.split("_")[2])
    
    # Delete schedule from database
    await db.delete_schedule(schedule_id)
    
    await callback_query.message.edit_text(
        f"✅ <b>Schedule Deleted</b>\n\n"
        f"• <b>Schedule ID:</b> <code>{schedule_id}</code>\n\n"
        f"This schedule will no longer run."
    )
    
    # Log deletion
    try:
        log_msg = (
            f"🗑 <blockquote><b>#ScheduleDeleted</b></blockquote>\n\n"
            f"👤 <b>Deleted By:</b> {callback_query.from_user.mention}\n"
            f"📌 <b>Schedule ID:</b> <code>{schedule_id}</code>\n"
        )
        
        await client.send_message(
            chat_id=LOG_CHANNEL,
            text=log_msg
        )
    except:
        pass

@Client.on_callback_query(filters.regex(r"^list_schedules$"))
async def list_schedules_handler(client, callback_query: CallbackQuery):
    await callback_query.answer()
    
    # Get all schedules
    schedules = await db.get_all_schedules()
    
    if not schedules:
        await callback_query.message.edit_text("📋 <b>No active schedules found.</b>")
        return
    
    # Group schedules by status
    active_schedules = [s for s in schedules if s.get("status") == "active"]
    paused_schedules = [s for s in schedules if s.get("status") == "paused"]
    
    result_msg = "<blockquote>📋 <b>All Schedules</b></blockquote>\n\n"
    
    if active_schedules:
        result_msg += f"<b>▶ Active Schedules ({len(active_schedules)}):</b>\n"
        for schedule in active_schedules[:10]:  # Limit to 10 for readability
            schedule_id = schedule.get("schedule_id")
            group = schedule.get("group", "0")
            times = ', '.join(schedule.get("schedule_times", []))[:30]
            result_msg += f"  • <code>{schedule_id}</code> | Group {group} | {times}\n"
        if len(active_schedules) > 10:
            result_msg += f"  ...and {len(active_schedules)-10} more\n"
        result_msg += "\n"
    
    if paused_schedules:
        result_msg += f"<b>⏸ Paused Schedules ({len(paused_schedules)}):</b>\n"
        for schedule in paused_schedules[:10]:
            schedule_id = schedule.get("schedule_id")
            group = schedule.get("group", "0")
            times = ', '.join(schedule.get("schedule_times", []))[:30]
            result_msg += f"  • <code>{schedule_id}</code> | Group {group} | {times}\n"
        if len(paused_schedules) > 10:
            result_msg += f"  ...and {len(paused_schedules)-10} more\n"
    
    await callback_query.message.edit_text(
        result_msg,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="list_schedules")]
        ])
    )

# Add command to list schedules
@Client.on_message(filters.command(["listschedules", "schedules"]) & filters.private & admin_filter)
async def list_schedules_command(client, message: Message):
    # Create a callback query-like message to trigger the handler
    message.text = "/listschedules"
    await list_schedules_handler(client, message)


