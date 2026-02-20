import os
import re
import requests
from pyrogram import Client, filters
from config import *

def get_video_id(url):
    match = re.search(r'(?:v=|youtu\.be/|shorts/)([a-zA-Z0-9_-]{11})', url)
    return match.group(1) if match else None

@Client.on_message(filters.text)
async def get_thumbnail(client, message):
    url = message.text.strip()
    video_id = get_video_id(url)
    
    if not video_id:
        await message.reply_text("❌ Invalid YouTube URL")
        return
    
    # Try max resolution first, then fallback to others
    qualities = [
        ("maxresdefault.jpg", "Maximum (1920x1080)"),
        ("sddefault.jpg", "High (640x480)"),
        ("hqdefault.jpg", "Medium (480x360)"),
        ("default.jpg", "Low (120x90)")
    ]
    
    for quality_file, quality_name in qualities:
        thumb_url = f"https://img.youtube.com/vi/{video_id}/{quality_file}"
        
        try:
            # Check if thumbnail exists
            response = requests.head(thumb_url, timeout=3)
            if response.status_code == 200:
                # Download and send
                img_response = requests.get(thumb_url, timeout=5)
                if img_response.status_code == 200:
                    filename = f"{video_id}.jpg"
                    with open(filename, 'wb') as f:
                        f.write(img_response.content)
                    
                    await message.send_photo(
                        filename
                    )
                    
                    os.remove(filename)
                    return
        except:
            continue
    
    await message.reply_text("❌ Could not fetch thumbnail")
