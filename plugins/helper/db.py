import motor.motor_asyncio
import time
from datetime import datetime
from config import *
from typing import List, Dict, Optional, Union
import math
import os
import shutil
import subprocess
import json


class Database:
    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col = self.db.user
        self.channels = self.db.channels
        self.formatting = self.db.formatting
        self.admins = self.db.admins
        self.posts = self.db.posts
        self.settings = self.db.settings
        self.logs = self.db.logs

    # ============ Logging System ============ #
    async def log_error(self, error_msg: str):
        """Log errors to database"""
        try:
            await self.logs.insert_one({
                "type": "error",
                "message": error_msg,
                "timestamp": datetime.now()
            })
        except Exception as e:
            print(f"Failed to log error: {e}")

    async def log_action(self, action_type: str, user_id: int, details: Dict):
        """Log actions to database"""
        try:
            await self.logs.insert_one({
                "type": action_type,
                "user_id": user_id,
                "details": details,
                "timestamp": datetime.now()
            })
        except Exception as e:
            print(f"Failed to log action: {e}")

    # ============ User System ============ #
    def new_user(self, id):
        return dict(
            _id=int(id),
            file_id=None,
            caption=None,
            prefix=None,
            suffix=None,
            metadata=False,
            metadata_code="By :- @xDzoddd",
            join_date=datetime.now(),
            last_active=datetime.now()
        )

    async def add_user(self, id):
        if not await self.is_user_exist(id):
            user = self.new_user(id)
            await self.col.insert_one(user)

    async def is_user_exist(self, id):
        user = await self.col.find_one({'_id': int(id)})
        return bool(user)

    async def total_users_count(self):
        return await self.col.count_documents({})

    async def get_all_users(self):
        return [user async for user in self.col.find({})]

    async def delete_user(self, user_id):
        await self.col.delete_many({'_id': int(user_id)})

    # ============ Admin System ============ #
    async def add_admin(self, user_id: int, admin_data: Optional[Dict] = None):
        """Add or update an admin with additional metadata"""
        admin_data = admin_data or {}
        admin_data.update({
            "_id": user_id,
            "is_admin": True,
            "added_at": datetime.now(),
            "last_active": datetime.now()
        })
        await self.admins.update_one(
            {"_id": user_id},
            {"$set": admin_data},
            upsert=True
        )

    async def remove_admin(self, user_id: int):
        """Remove admin privileges"""
        await self.admins.delete_one({"_id": user_id})

    async def is_admin(self, user_id: int) -> bool:
        """Check if user is admin with proper error handling"""
        try:
            admin = await self.admins.find_one({"_id": user_id})
            return admin is not None and admin.get("is_admin", False)
        except Exception as e:
            await self.log_error(f"Admin check error for {user_id}: {e}")
            return False

    async def get_admin(self, user_id: int) -> Optional[Dict]:
        """Get full admin data"""
        return await self.admins.find_one({"_id": user_id})

    async def get_all_admins(self) -> List[Dict]:
        """List all admins with their details"""
        return [admin async for admin in self.admins.find({"is_admin": True})]

    async def update_admin_activity(self, user_id: int):
        """Update admin's last active time"""
        await self.admins.update_one(
            {"_id": user_id},
            {"$set": {"last_active": datetime.now()}}
        )

    # ============ Post System ============ #
    async def save_post(self, post_data):
        post_data["timestamp"] = datetime.now()
        try:
            await self.posts.update_one(
                {"post_id": post_data["post_id"]},
                {"$set": post_data},
                upsert=True
            )
            await self.log_action("post_saved", post_data.get("user_id"), {
                "post_id": post_data["post_id"],
                "channels_count": len(post_data.get("channels", [])),
                "group": post_data.get("group", "0")
            })
            return True
        except Exception as e:
            await self.log_error(f"Error saving post: {e}")
            return False

    async def get_post(self, post_id):
        try:
            return await self.posts.find_one({"post_id": post_id})
        except Exception as e:
            await self.log_error(f"Error retrieving post: {e}")
            return None

    async def delete_post(self, post_id):
        try:
            result = await self.posts.delete_one({"post_id": post_id})
            await self.log_action("post_deleted", 0, {"post_id": post_id})
            return result.deleted_count > 0
        except Exception as e:
            await self.log_error(f"Error deleting post: {e}")
            return False

    async def get_pending_deletions(self):
        try:
            return await self.posts.find({
                "delete_after": {"$gt": time.time()}
            }).to_list(None)
        except Exception as e:
            await self.log_error(f"Error getting pending deletions: {e}")
            return []

    async def remove_channel_post(self, post_id, channel_id):
        try:
            result = await self.posts.update_one(
                {"post_id": post_id},
                {"$pull": {"channels": {"channel_id": channel_id}}}
            )
            return result.modified_count > 0
        except Exception as e:
            await self.log_error(f"Error removing channel post: {e}")
            return False

    async def get_post_channels(self, post_id):
        try:
            post = await self.posts.find_one({"post_id": post_id})
            return post.get("channels", []) if post else []
        except Exception as e:
            await self.log_error(f"Error getting post channels: {e}")
            return []

    async def get_all_posts(self, limit: int = 0, skip: int = 0):
        try:
            return [post async for post in self.posts.find({}).skip(skip).limit(limit)]
        except Exception as e:
            await self.log_error(f"Error retrieving posts: {e}")
            return []

    # ============ Channel System with Group Support ============ #
    async def add_channel(self, channel_id, channel_name=None, group="0"):
        channel_id = int(channel_id)
        # Check if this channel already exists in this specific group
        if not await self.is_channel_in_group(channel_id, group):
            await self.channels.insert_one({
                "_id": f"{channel_id}_{group}",  # Composite key to allow same channel in multiple groups
                "channel_id": channel_id,  # Actual channel ID
                "name": channel_name,
                "group": group,
                "added_date": datetime.now(),
                "post_count": 0,
                "last_post": None,
                "is_active": True
            })
            await self.log_action("channel_added", 0, {
                "channel_id": channel_id,
                "channel_name": channel_name,
                "group": group
            })
            return True
        return False

    async def delete_channel(self, channel_id, group="0"):
        """Delete specific channel from specific group"""
        try:
            result = await self.channels.delete_one({
                "channel_id": int(channel_id),
                "group": group
            })
            await self.log_action("channel_deleted", 0, {
                "channel_id": channel_id,
                "group": group
            })
            return result.deleted_count > 0
        except Exception as e:
            await self.log_error(f"Error deleting channel: {e}")
            return False

    async def remove_restricted_channels(self, channel_ids, group="0"):
        """Remove multiple restricted channels from database"""
        try:
            if not isinstance(channel_ids, list):
                channel_ids = [channel_ids]
            
            # Convert all to int
            channel_ids = [int(cid) for cid in channel_ids]
            
            result = await self.channels.delete_many({
                "channel_id": {"$in": channel_ids},
                "group": group
            })
            
            await self.log_action("restricted_channels_removed", 0, {
                "channel_ids": channel_ids,
                "group": group,
                "count": result.deleted_count
            })
            
            return result.deleted_count
        except Exception as e:
            await self.log_error(f"Error removing restricted channels: {e}")
            return 0

    async def is_channel_exist(self, channel_id):
        """Check if channel exists in any group"""
        return await self.channels.find_one({"channel_id": int(channel_id)}) is not None

    async def is_channel_in_group(self, channel_id, group="0"):
        """Check if channel exists in specific group"""
        return await self.channels.find_one({
            "channel_id": int(channel_id),
            "group": group
        }) is not None

    async def get_channel_info(self, channel_id, group="0"):
        """Get channel information from specific group"""
        try:
            return await self.channels.find_one({
                "channel_id": int(channel_id),
                "group": group
            })
        except Exception as e:
            await self.log_error(f"Error getting channel info: {e}")
            return None

    async def get_all_channels(self):
        """Get all channels across all groups"""
        return [channel async for channel in self.channels.find({})]

    async def get_channels_by_group(self, group="0"):
        """Get channels only from specific group"""
        return [channel async for channel in self.channels.find({"group": group})]

    async def get_channel_groups(self, channel_id):
        """Get all groups a channel belongs to"""
        return [doc["group"] async for doc in self.channels.find(
            {"channel_id": int(channel_id)},
            {"group": 1}
        )]

    async def increment_channel_post(self, channel_id):
        """Increment post count for all instances of this channel (across all groups)"""
        await self.channels.update_many(
            {"channel_id": int(channel_id)},
            {
                "$inc": {"post_count": 1},
                "$set": {"last_post": datetime.now()}
            }
        )

    async def update_channel_status(self, channel_id, group="0", is_active=True):
        """Update channel active status"""
        try:
            await self.channels.update_one(
                {"channel_id": int(channel_id), "group": group},
                {"$set": {"is_active": is_active}}
            )
            return True
        except Exception as e:
            await self.log_error(f"Error updating channel status: {e}")
            return False

    async def get_total_channel_count(self):
        """Get total number of channels across all groups"""
        try:
            return await self.channels.count_documents({})
        except Exception as e:
            await self.log_error(f"Error counting channels: {e}")
            return 0

    async def get_channel_count_by_group(self, group="0"):
        """Get number of channels in specific group"""
        try:
            return await self.channels.count_documents({"group": group})
        except Exception as e:
            await self.log_error(f"Error counting channels in group: {e}")
            return 0

    # ============ Settings System ============ #
    async def save_setting(self, key: str, value):
        """Save a setting to database"""
        try:
            await self.settings.update_one(
                {"key": key},
                {"$set": {"value": value, "updated_at": datetime.now()}},
                upsert=True
            )
            return True
        except Exception as e:
            await self.log_error(f"Error saving setting: {e}")
            return False

    async def get_setting(self, key: str, default=None):
        """Get a setting from database"""
        try:
            setting = await self.settings.find_one({"key": key})
            return setting.get("value", default) if setting else default
        except Exception as e:
            await self.log_error(f"Error getting setting: {e}")
            return default

    async def delete_setting(self, key: str):
        """Delete a setting"""
        try:
            await self.settings.delete_one({"key": key})
            return True
        except Exception as e:
            await self.log_error(f"Error deleting setting: {e}")
            return False

    # ============ Statistics System ============ #
    async def get_statistics(self):
        """Get overall statistics"""
        try:
            stats = {
                "total_users": await self.total_users_count(),
                "total_admins": await self.admins.count_documents({"is_admin": True}),
                "total_channels": await self.get_total_channel_count(),
                "total_posts": await self.posts.count_documents({}),
                "pending_deletions": len(await self.get_pending_deletions()),
                "groups": {}
            }
            
            # Get channel counts per group
            for group in ["0", "1", "2", "3"]:
                stats["groups"][group] = await self.get_channel_count_by_group(group)
            
            return stats
        except Exception as e:
            await self.log_error(f"Error getting statistics: {e}")
            return {}

    # ============ Cleanup System ============ #
    async def cleanup_old_logs(self, days: int = 30):
        """Clean up logs older than specified days"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            result = await self.logs.delete_many({
                "timestamp": {"$lt": cutoff_date}
            })
            return result.deleted_count
        except Exception as e:
            await self.log_error(f"Error cleaning up old logs: {e}")
            return 0

    async def cleanup_old_posts(self, days: int = 90):
        """Clean up posts older than specified days"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            result = await self.posts.delete_many({
                "timestamp": {"$lt": cutoff_date}
            })
            return result.deleted_count
        except Exception as e:
            await self.log_error(f"Error cleaning up old posts: {e}")
            return 0

# Initialize the database
db = Database(DB_URL, DB_NAME)
