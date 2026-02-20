import re
from pyrogram import Client, filters

def get_video_id(url):
    pattern = (
        r"(?:https?://)?(?:www\.|m\.)?"                # optional protocol and subdomain
        r"(?:youtu\.be/|youtube\.com/"                 # youtu.be OR youtube.com/
        r"(?:embed/|shorts/|live/|v/|watch.*[?&]v=))"  # path-based OR watch with v param
        r"([^/?&]+)"                                   # capture video ID (stop at / ? &)
    )
    match = re.search(pattern, url, re.IGNORECASE)
    if match:
        video_id = match.group(1)
        # YouTube video IDs are exactly 11 characters and consist of [A-Za-z0-9_-]
        if re.match(r"^[\w-]{11}$", video_id):
            return video_id
    return None

@Client.on_message(filters.command(["t", "thumb"]))
async def get_thumbnail(client, message):
    if len(message.command) < 2:
        await message.reply_text("❌ Send like this:\n/t YouTube_link")
        return

    video_id = get_video_id(message.command[1])

    if not video_id:
        await message.reply_text("❌ Invalid or unsupported YouTube URL")
        return

    qualities = [
        "maxresdefault.jpg",   # Highest quality (if available)
        "sddefault.jpg",
        "hqdefault.jpg",
        "default.jpg"
    ]

    for quality in qualities:
        thumb_url = f"https://img.youtube.com/vi/{video_id}/{quality}"
        try:
            await message.reply_photo(thumb_url)
            return
        except Exception:
            continue

    await message.reply_text("❌ Could not fetch thumbnail")
