import re
from pyrogram import Client, filters

def get_video_id(url):
    match = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", url)
    return match.group(1) if match else None

@Client.on_message(filters.command(["t", "thumb"]))
async def get_thumbnail(client, message):
    
    if len(message.command) < 2:
        await message.reply_text("❌ Send like this:\n/t YouTube_link")
        return

    video_id = get_video_id(message.command[1])

    if not video_id:
        await message.reply_text("❌ Invalid YouTube URL")
        return

    qualities = [
        "maxresdefault.jpg",   # Highest priority
        "sddefault.jpg",
        "hqdefault.jpg",
        "default.jpg"
    ]

    for quality in qualities:
        thumb_url = f"https://img.youtube.com/vi/{video_id}/{quality}"
        try:
            await message.reply_photo(thumb_url)
            return
        except:
            continue

    await message.reply_text("❌ Could not fetch thumbnail")
