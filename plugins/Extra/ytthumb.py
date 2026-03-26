import re
from pyrogram import Client, filters

def get_video_id(text):
    pattern = (
        r"(?:https?://)?(?:www.|m.)?"                # optional protocol & subdomain
        r"(?:youtu.be/|youtube.com/"                 # youtu.be OR youtube.com/
        r"(?:embed/|shorts/|live/|v/|watch.*[?&]v=))"  # path-based OR watch with v=
        r"([^/?&]+)"                                    # capture video ID
    )
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        video_id = match.group(1)
        # YouTube video IDs are exactly 11 characters and consist of [A-Za-z0-9_-]
        if re.match(r"^[\w-]{11}$", video_id):
            return video_id
    return None

# Filter: private text messages that contain a YouTube link but don't start with /
@Client.on_message(
    filters.text
    & filters.private
    & ~filters.command(["start", "admin", "settings", "thumbnail"])  # Ignore common commands
    & filters.regex(r"(https?://)?(www.|m.)?(youtube.com|youtu.be)/")
)
async def auto_thumbnail(client, message):
    # Additional check to ensure message doesn't start with / (command)
    if message.text and message.text.startswith('/'):
        return  # Ignore all command messages

    video_id = get_video_id(message.text)  
    if not video_id:  
        return  # ignore if no valid ID found  

    # Get the original YouTube link from the message
    youtube_link = None
    for word in message.text.split():
        if 'youtu.be' in word or 'youtube.com' in word:
            youtube_link = word
            break
    
    qualities = [  
        "maxresdefault.jpg",   # highest quality (if available)  
        "sddefault.jpg",  
        "hqdefault.jpg",  
        "default.jpg"  
    ]  

    for quality in qualities:  
        thumb_url = f"https://img.youtube.com/vi/{video_id}/{quality}"  
        try:
            caption = f"""<b><blockquote>Watch Now ♥️ </blockquote></b>
<b><blockquote>{youtube_link}
{youtube_link}</blockquote></b>"""
            
            await message.reply_photo(thumb_url, caption=caption)  
            return  # stop after first successful reply  
        except Exception:  
            continue  # try next quality  

    # Optionally, you can notify the user if all attempts fail:  
    await message.reply_text("**❌ Could not fetch thumbnail**")
