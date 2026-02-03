# database/mongo.py
from motor.motor_asyncio import AsyncIOMotorClient
from config import Config
import logging

logger = logging.getLogger(__name__)

# --- Database Initialization ---
# Connecting to MongoDB Atlas using the URL from Config
client = AsyncIOMotorClient(Config.MONGO_URL)
db = client["startlove"]  # Fixed Database Name: startlove

# --- Collection Definitions ---
sessions_db = db["sessions"]
sudo_db = db["sudo_users"]
settings_db = db["settings"]

# --- Session Management Logic (Optimized) ---

async def add_session(user_id: int, session_str: str):
    """
    Saves a session string to the database.
    Uses 'update_one' with 'upsert' to prevent duplicates.
    Enforces user_id as Integer for new entries.
    """
    try:
        uid = int(user_id)
        await sessions_db.update_one(
            {"user_id": uid, "session": session_str},
            {"$set": {"user_id": uid, "session": session_str}},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Error in add_session: {e}")
        return False

async def get_sessions(user_id: int):
    """
    Retrieves ALL sessions for a specific ID from 'startlove'.
    FIX: Uses '$or' to scan both Integer and String User IDs.
    This ensures that sessions saved previously (even by old bot versions) 
    are correctly extracted.
    """
    try:
        uid = int(user_id)
        # Scan for both formats to ensure no sessions are missed
        cursor = sessions_db.find({
            "$or": [
                {"user_id": uid},
                {"user_id": str(uid)}
            ]
        })
        
        sessions = [s["session"] async for s in cursor if "session" in s]
        logger.info(f"Database Scan for {uid}: Found {len(sessions)} sessions in 'startlove'")
        return sessions
    except Exception as e:
        logger.error(f"Error in get_sessions: {e}")
        return []

async def delete_all_sessions(user_id: int):
    """Wipes all sessions for a user, checking both ID formats."""
    try:
        uid = int(user_id)
        await sessions_db.delete_many({
            "$or": [
                {"user_id": uid},
                {"user_id": str(uid)}
            ]
        })
        return True
    except Exception as e:
        logger.error(f"Error deleting sessions: {e}")
        return False

# --- Sudo/Permission Management ---

async def add_sudo(user_id: int):
    uid = int(user_id)
    await sudo_db.update_one({"user_id": uid}, {"$set": {"user_id": uid}}, upsert=True)

async def remove_sudo(user_id: int):
    uid = int(user_id)
    await sudo_db.delete_one({"user_id": uid})

async def is_sudo(user_id: int):
    """Checks if a user is Sudo or Owner."""
    if user_id == Config.OWNER_ID:
        return True
    uid = int(user_id)
    sudo = await sudo_db.find_one({"user_id": uid})
    return sudo is not None

async def get_all_sudos():
    cursor = sudo_db.find({})
    return [s["user_id"] async for s in cursor]

# --- Global Bot Configuration Management ---

async def get_bot_settings():
    """
    Fetches global settings with safety fallbacks.
    Prevents KeyError if 'force_sub' or 'min_sessions' is missing.
    """
    try:
        settings = await settings_db.find_one({"id": "bot_config"})
        if not settings:
            default = {
                "id": "bot_config",
                "min_sessions": Config.DEFAULT_MIN_SESSIONS,
                "force_sub": None
            }
            await settings_db.insert_one(default)
            return default
        
        # Reliability check for existing documents
        if "min_sessions" not in settings: 
            settings["min_sessions"] = Config.DEFAULT_MIN_SESSIONS
        if "force_sub" not in settings: 
            settings["force_sub"] = None
            
        return settings
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return {"min_sessions": Config.DEFAULT_MIN_SESSIONS, "force_sub": None}

async def update_bot_settings(updates: dict):
    """Updates global config such as Force Sub or Min Sessions."""
    await settings_db.update_one({"id": "bot_config"}, {"$set": updates}, upsert=True)
