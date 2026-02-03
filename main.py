# main.py
import asyncio
import os
import sys
import logging

# Logging for Heroku stability
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from pyrogram.errors import UserNotParticipant, FloodWait, RPCError

from config import Config
from database.mongo import (
    add_session, get_sessions, delete_all_sessions, 
    is_sudo, get_bot_settings, update_bot_settings, 
    add_sudo, remove_sudo, get_all_sudos
)
from utils.helpers import parse_target, auto_join, get_progress_card
from utils.user_guide import GUIDE_TEXT
from report import send_single_report

app = Client(
    "UltimateReportBot", 
    api_id=Config.API_ID, 
    api_hash=Config.API_HASH, 
    bot_token=Config.BOT_TOKEN,
    in_memory=True
)

# User State Management
U_STATE = {}

async def verify_user(uid):
    """Checks for Force Sub and Minimum Session requirements."""
    settings = await get_bot_settings()
    sudo = await is_sudo(uid)
    
    # 1. Force Subscribe Check (Bypassed for Sudo/Owner)
    fsub = settings.get("force_sub")
    if fsub and not sudo:
        try:
            # Clean username for API call
            chat = fsub if fsub.startswith("-100") or fsub.isdigit() else f"@{fsub.replace('@', '')}"
            await app.get_chat_member(chat, uid)
        except UserNotParticipant:
            return "JOIN_REQUIRED", fsub.replace("@", "")
        except Exception as e:
            logger.error(f"F-Sub Check Error: {e}")
    
    # 2. Minimum Session Check (Bypassed for Sudo/Owner)
    if not sudo:
        sessions = await get_sessions(uid)
        min_s = settings.get("min_sessions", Config.DEFAULT_MIN_SESSIONS)
        if len(sessions) < min_s:
            return "MIN_SESS", min_s
            
    return "OK", None

@app.on_message(filters.command("start", Config.PREFIX) & filters.private)
async def start_handler(client, message: Message):
    uid = message.from_user.id
    status, data = await verify_user(uid)
    
    if status == "JOIN_REQUIRED":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{data}")]])
        return await message.reply_text(
            "🚫 **Access Denied!**\n\nYou must join our update channel to use this bot.\n\nAfter joining, click /start again.", 
            reply_markup=kb
        )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Launch Reporter", callback_data="launch_flow")],
        [InlineKeyboardButton("📂 Manage Sessions", callback_data="manage_sessions"), InlineKeyboardButton("📖 User Guide", callback_data="open_guide")],
        [InlineKeyboardButton("⚙️ Owner Panel", callback_data="owner_panel")] if uid == Config.OWNER_ID else []
    ])
    await message.reply_text(
        f"💎 **Ultimate OxyReport Pro v3.0**\n\nWelcome back, **{message.from_user.first_name}**!\nStatus: `Authorized ✅`", 
        reply_markup=kb
    )

@app.on_callback_query()
async def cb_handler(client, cb: CallbackQuery):
    uid = cb.from_user.id
    data = cb.data
    
    # Validation for buttons
    if data not in ["open_guide", "start_back"]:
        status, val = await verify_user(uid)
        if status == "JOIN_REQUIRED":
            return await cb.answer(f"🚫 Join @{val} first!", show_alert=True)

    if data == "owner_panel" and uid == Config.OWNER_ID:
        setts = await get_bot_settings()
        kb = [[InlineKeyboardButton(f"Min Sessions: {setts.get('min_sessions', 3)}", callback_data="set_min")],
              [InlineKeyboardButton(f"F-Sub: @{setts.get('force_sub') or 'None'}", callback_data="set_fsub")],
              [InlineKeyboardButton("👤 Sudo List", callback_data="list_sudo"), InlineKeyboardButton("🔄 Restart", callback_data="restart_bot")],
              [InlineKeyboardButton("🔙 Back", callback_data="start_back")]]
        await cb.edit_message_text("⚙️ **Owner Control Panel**\nManage global restrictions and permissions.", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "launch_flow":
        kb = [[InlineKeyboardButton("✅ Use Saved Sessions", callback_data="choose_saved")],
              [InlineKeyboardButton("➕ Add New Sessions", callback_data="choose_new")],
              [InlineKeyboardButton("🔙 Back", callback_data="start_back")]]
        await cb.edit_message_text("🚀 **Session Initialization**\n\nChoose session source for this task:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "choose_saved":
        sessions = await get_sessions(uid)
        sudo = await is_sudo(uid)
        setts = await get_bot_settings()
        min_s = setts.get("min_sessions", 3)
        
        if not sudo and len(sessions) < min_s:
            return await cb.answer(f"⚠️ Insufficient sessions! Found: {len(sessions)}, Need: {min_s}", show_alert=True)
        if not sessions:
            return await cb.answer("❌ Your DB is empty! Add sessions first.", show_alert=True)

        U_STATE[uid] = {"step": "WAIT_JOIN", "use_saved": True, "sessions": sessions}
        await cb.edit_message_text("🔗 **Step 1: Context Join**\n\nSend a private invite link if the target is in a private group, or send `/skip`.")

    elif data == "choose_new":
        U_STATE[uid] = {"step": "WAIT_SESS_FLOW"}
        await cb.edit_message_text("📝 **Step 1: Session Input**\n\nPaste your Pyrogram Session Strings (comma separated):")

    elif data == "manage_sessions":
        sessions = await get_sessions(uid)
        kb = [[InlineKeyboardButton("➕ Add New Sessions", callback_data="add_sess_p")],
              [InlineKeyboardButton("🗑️ Clear My Database", callback_data="clear_sess_p")],
              [InlineKeyboardButton("🔙 Back", callback_data="start_back")]]
        await cb.edit_message_text(f"📂 **Session Manager**\nSaved Sessions: **{len(sessions)}**", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "add_sess_p":
        U_STATE[uid] = {"step": "WAIT_SESS_ONLY"}
        await cb.edit_message_text("💾 **Database Upload**\n\nSend session strings to save permanently in MongoDB:")

    elif data == "clear_sess_p":
        await delete_all_sessions(uid)
        await cb.answer("✅ Database cleared!", show_alert=True)
        await cb.edit_message_text("📂 All sessions removed.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="manage_sessions")]]))

    elif data == "list_sudo" and uid == Config.OWNER_ID:
        sudos = await get_all_sudos()
        text = "👤 **Sudo Users:**\n\n" + "\n".join([f"• `{s}`" for s in sudos]) if sudos else "No Sudo Users."
        kb = [[InlineKeyboardButton("➕ Add Sudo", callback_data="add_sudo_p"), InlineKeyboardButton("➖ Rem Sudo", callback_data="rem_sudo_p")], [InlineKeyboardButton("🔙", callback_data="owner_panel")]]
        await cb.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "restart_bot" and uid == Config.OWNER_ID:
        await cb.answer("Bot Restarting...", show_alert=True)
        os.execl(sys.executable, sys.executable, *sys.argv)

    elif data == "set_min": U_STATE[uid] = {"step": "WAIT_MIN_SESS"}; await cb.edit_message_text("🔢 Enter new **Minimum Sessions** limit:")
    elif data == "set_fsub": U_STATE[uid] = {"step": "WAIT_FSUB"}; await cb.edit_message_text("📢 Enter **Channel Username** (without @):")
    elif data == "add_sudo_p": U_STATE[uid] = {"step": "WAIT_ADD_SUDO"}; await cb.edit_message_text("👤 Enter **User ID** to add:")
    elif data == "rem_sudo_p": U_STATE[uid] = {"step": "WAIT_REM_SUDO"}; await cb.edit_message_text("👤 Enter **User ID** to remove:")

    elif data.startswith("rc_"):
        U_STATE[uid]["code"] = data.split("_")[1]
        U_STATE[uid]["step"] = "WAIT_DESC"
        await cb.edit_message_text("✏️ **Step 4: Report Description**\n\nEnter custom text/reason for the report:")

    elif data == "open_guide":
        await cb.edit_message_text(GUIDE_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="start_back")]]))

    elif data == "start_back":
        U_STATE.pop(uid, None)
        kb = [[InlineKeyboardButton("🚀 Launch Reporter", callback_data="launch_flow")],
              [InlineKeyboardButton("📂 Sessions", callback_data="manage_sessions"), InlineKeyboardButton("📖 Guide", callback_data="open_guide")],
              [InlineKeyboardButton("⚙️ Owner", callback_data="owner_panel")] if uid == Config.OWNER_ID else []]
        await cb.edit_message_text("💎 **Ultimate OxyReport Pro v3.0**", reply_markup=InlineKeyboardMarkup(kb))

@app.on_message(filters.private & filters.text)
async def msg_handler(client, message: Message):
    uid = message.from_user.id
    if uid not in U_STATE: return
    state = U_STATE[uid]
    txt = message.text

    # Admin Operations
    if uid == Config.OWNER_ID:
        if state["step"] == "WAIT_MIN_SESS":
            if txt.isdigit():
                await update_bot_settings({"min_sessions": int(txt)})
                await message.reply_text(f"✅ Min sessions updated to {txt}")
                U_STATE.pop(uid)
            return
        elif state["step"] == "WAIT_FSUB":
            await update_bot_settings({"force_sub": txt.replace("@", "").strip()})
            await message.reply_text(f"✅ Force Sub updated to @{txt}")
            U_STATE.pop(uid)
            return
        elif state["step"] == "WAIT_ADD_SUDO" and txt.isdigit():
            await add_sudo(int(txt))
            await message.reply_text(f"✅ Sudo added: {txt}")
            U_STATE.pop(uid)
            return
        elif state["step"] == "WAIT_REM_SUDO" and txt.isdigit():
            await remove_sudo(int(txt))
            await message.reply_text(f"✅ Sudo removed: {txt}")
            U_STATE.pop(uid)
            return

    # User Operations
    if state["step"] == "WAIT_SESS_ONLY":
        sess = [s.strip() for s in txt.split(",") if len(s.strip()) > 50]
        for s in sess: await add_session(uid, s)
        await message.reply_text(f"✅ {len(sess)} sessions added to DB."); U_STATE.pop(uid)

    elif state["step"] == "WAIT_SESS_FLOW":
        valid = [s.strip() for s in txt.split(",") if len(s.strip()) > 50]
        st = await get_bot_settings()
        if not await is_sudo(uid) and len(valid) < st.get("min_sessions", 3):
            return await message.reply_text(f"❌ Need at least {st.get('min_sessions', 3)} sessions.")
        state["sessions"] = valid
        state["step"] = "WAIT_JOIN"
        await message.reply_text("✅ Sessions validated.\n\n🔗 **Step 2: Private Join**\nSend invite link or `/skip`.")

    elif state["step"] == "WAIT_JOIN":
        state["join"] = txt if txt != "/skip" else None
        state["step"] = "WAIT_TARGET"
        await message.reply_text("🎯 **Step 3: Target Link**\n\nSend the message/profile link:")

    elif state["step"] == "WAIT_TARGET":
        try:
            state["cid"], state["mid"] = parse_target(txt)
            state["url"] = txt
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Spam", callback_data="rc_1"), InlineKeyboardButton("Porn", callback_data="rc_4")],
                [InlineKeyboardButton("Violence", callback_data="rc_2"), InlineKeyboardButton("Other", callback_data="rc_8")]
            ])
            state["step"] = "WAIT_REASON"
            await message.reply_text("⚖️ **Step 4: Report Intelligence**\nSelect report category:", reply_markup=kb)
        except Exception as e: await message.reply_text(f"❌ Error: {e}")

    elif state["step"] == "WAIT_DESC":
        state["desc"] = txt; state["step"] = "WAIT_COUNT"
        await message.reply_text("🔢 **Step 5: Density**\n\nHow many reports needed?")

    elif state["step"] == "WAIT_COUNT" and txt.isdigit():
        state["count"] = int(txt)
        asyncio.create_task(process_reports(message, state))
        U_STATE.pop(uid)

async def start_client(session_str, uid, i, join_link):
    """Helper to start client and join chat in parallel."""
    c = Client(
        name=f"run_{uid}_{i}_{asyncio.get_event_loop().time()}", 
        api_id=Config.API_ID, 
        api_hash=Config.API_HASH, 
        session_string=session_str, 
        in_memory=True
    )
    try:
        await c.start()
        if join_link: await auto_join(c, join_link)
        return c
    except:
        return None

async def process_reports(msg, config):
    panel = await msg.reply_text("⏳ **Initializing Secure Tunnel...**")
    uid = msg.from_user.id
    sessions = config.get("sessions", [])
    
    # Start sessions in parallel (10x faster)
    tasks = [start_client(s, uid, i, config.get("join")) for i, s in enumerate(sessions)]
    results = await asyncio.gather(*tasks)
    clients = [c for c in results if c is not None]
    
    if not clients: return await panel.edit_text("❌ Connection failed. Check your session strings.")
    
    await panel.edit_text(f"🚀 **Flooding started with {len(clients)} threads...**")
    
    success, failed = 0, 0
    total = config["count"]
    
    for i in range(total):
        # SESSION ROTATION LOGIC
        active_client = clients[i % len(clients)]
        res = await send_single_report(active_client, config["cid"], config["mid"], config["code"], config["desc"])
        
        if res: success += 1
        else: failed += 1
        
        if i % 3 == 0 or i == total - 1:
            try:
                await panel.edit_text(get_progress_card(config["url"], success, failed, total, len(clients)))
            except FloodWait as e: await asyncio.sleep(e.x)
            except: pass
        await asyncio.sleep(0.3) # Avoid Telegram FloodWait
        
    for c in clients: 
        try: await c.stop()
        except: pass
        
    await msg.reply_text(f"🏁 **Execution Completed!**\nTarget: {config['url']}\nTotal Success: {success}")

async def run_bot():
    logger.info("Ultimate OxyReport Pro v3.0 starting...")
    await app.start()
    logger.info("Bot is Live!")
    await idle()
    await app.stop()

if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        pass
