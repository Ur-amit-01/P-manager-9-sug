from plugins.helper.db import db

async def sync_channel_names(client):
    """Fetch current names for all channels and update DB if changed. Run once at startup."""
    channels = await db.get_all_channels()
    updated = 0
    for ch in channels:
        try:
            chat = await client.get_chat(ch["channel_id"])
            if chat.title and chat.title != ch.get("name"):
                await db.update_channel_name(ch["channel_id"], ch["group"], chat.title)
                updated += 1
        except Exception as e:
            print(f"Could not refresh name for {ch['channel_id']}: {e}")
    print(f"[sync_channel_names] Checked {len(channels)} channels, updated {updated}.")
