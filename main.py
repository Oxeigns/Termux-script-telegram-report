# main.py
import asyncio
import os
import sys
from pyrogram import Client, filters, types
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import UserNotParticipant, FloodWait

from config import Config
from database.mongo import (
    add_session, get_sessions, delete_all_sessions, 
    is_sudo, get_bot_settings, update_bot_settings, 
    add_sudo, remove_sudo, get_all_sudos
)
from utils.helpers import parse_target, auto_join, get_progress_card
from utils.user_guide import GUIDE_TEXT
from report import send_single_report

app = Client("UltimateReportBot", api_id=Config.API_ID, api_hash=Config.API_HASH, bot_token=Config.BOT_TOKEN)

# In-Memory State for Conversation Flow
U_STATE = {}

# --- MIDDLEWARE: Verification ---
async def verify_user(uid):
    settings = await get_bot_settings()
    sudo = await is_sudo(uid)
    
    # 1. Force Sub
    if settings.get("force_sub") and not sudo:
        try:
            await app.get_chat_member(settings["force_sub"], uid)
        except UserNotParticipant:
            return "JOIN_REQUIRED", f"https://t.me/{settings['force_sub']}"
        except: pass
        
    # 2. Min Session Check
    if not sudo:
        sessions = await get_sessions(uid)
        if len(sessions) < settings["min_sessions"]:
            return "MIN_SESS", settings["min_sessions"]
            
    return "OK", None

@app.on_message(filters.command("start", Config.PREFIX) & filters.private)
async def start_handler(client, message: Message):
    uid = message.from_user.id
    status, data = await verify_user(uid)
    
    if status == "JOIN_REQUIRED":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Channel", url=data)]])
        return await message.reply_text("🚫 **Access Denied!**\n\nPlease join our update channel to use this bot.", reply_markup=kb)
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Launch Reporter", callback_data="open_reporter")],
        [InlineKeyboardButton("📂 Manage Sessions", callback_data="manage_sessions"), InlineKeyboardButton("📖 User Guide", callback_data="open_guide")],
        [InlineKeyboardButton("⚙️ Owner Panel", callback_data="owner_panel")] if uid == Config.OWNER_ID else []
    ])
    await message.reply_text(
        f"💎 **Ultimate OxyReport Pro v3.0**\n\nThe most advanced Telegram reporting system. Multi-session, live panel, and raw API power.\n\n"
        f"**Welcome, {message.from_user.first_name}!**",
        reply_markup=kb
    )

@app.on_callback_query()
async def cb_handler(client, cb):
    uid = cb.from_user.id
    cmd = cb.data
    
    if cmd == "open_guide":
        await cb.edit_message_text(GUIDE_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="start_back")]]))
    
    elif cmd == "start_back":
        # Simply re-run start logic (better to edit)
        await cb.edit_message_text("🔙 Main Menu", 
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Launch Reporter", callback_data="open_reporter")],
                [InlineKeyboardButton("📂 Manage Sessions", callback_data="manage_sessions"), InlineKeyboardButton("📖 User Guide", callback_data="open_guide")],
                [InlineKeyboardButton("⚙️ Owner Panel", callback_data="owner_panel")] if uid == Config.OWNER_ID else []
            ])
        )

    # --- SESSION MANAGEMENT ---
    elif cmd == "manage_sessions":
        sessions = await get_sessions(uid)
        kb = [
            [InlineKeyboardButton("➕ Add New Sessions", callback_data="add_sess_prompt")],
            [InlineKeyboardButton("🗑️ Clear Sessions", callback_data="clear_sess_confirm")],
            [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
        ]
        await cb.edit_message_text(f"📂 **Session Manager**\n\nYou have **{len(sessions)}** active sessions saved.", reply_markup=InlineKeyboardMarkup(kb))

    elif cmd == "add_sess_prompt":
        U_STATE[uid] = {"step": "WAIT_SESS"}
        await cb.edit_message_text("📝 **Send your Pyrogram Session Strings:**\n\n(Multiple sessions separate karein `,` se)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="manage_sessions")]]))

    # --- OWNER PANEL ---
    elif cmd == "owner_panel" and uid == Config.OWNER_ID:
        setts = await get_bot_settings()
        kb = [
            [InlineKeyboardButton(f"Min Sessions: {setts['min_sessions']}", callback_data="set_min_prompt")],
            [InlineKeyboardButton(f"Force Sub: {setts['force_sub'] or 'None'}", callback_data="set_fsub_prompt")],
            [InlineKeyboardButton("🔄 Restart Bot", callback_data="restart_force")],
            [InlineKeyboardButton("🔙 Back", callback_data="start_back")]
        ]
        await cb.edit_message_text("⚙️ **Owner Control Unit**", reply_markup=InlineKeyboardMarkup(kb))

    elif cmd == "restart_force" and uid == Config.OWNER_ID:
        await cb.answer("Restarting Bot...", show_alert=True)
        os.execl(sys.executable, sys.executable, *sys.argv)

    # --- REPORT FLOW ---
    elif cmd == "open_reporter":
        # Re-verify permissions
        status, data = await verify_user(uid)
        if status == "MIN_SESS":
            return await cb.answer(f"⚠️ You need at least {data} sessions to proceed!", show_alert=True)
        
        U_STATE[uid] = {"step": "WAIT_JOIN_LINK"}
        await cb.edit_message_text("🔗 **Step 1: Invite Link**\n\nSend the **Invite Link** of the group/channel (If private). \n\nSend `/skip` if target is public.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="start_back")]]))

    elif cmd.startswith("r_code_"):
        code = cmd.split("_")[-1]
        U_STATE[uid]["code"] = code
        U_STATE[uid]["step"] = "WAIT_DESC"
        await cb.edit_message_text("✏️ **Step 4: description**\n\nEnter the customized report text:")

@app.on_message(filters.private)
async def msg_router(client, message: Message):
    uid = message.from_user.id
    if uid not in U_STATE: return
    
    state = U_STATE[uid]
    txt = message.text

    if state["step"] == "WAIT_SESS":
        sess_list = txt.split(",")
        for s in sess_list:
            if len(s.strip()) > 50: # Simple validation
                await add_session(uid, s.strip())
        await message.reply_text(f"✅ Sessions saved! You can now launch the reporter.")
        del U_STATE[uid]

    elif state["step"] == "WAIT_JOIN_LINK":
        state["join_link"] = txt if txt != "/skip" else None
        state["step"] = "WAIT_TARGET"
        await message.reply_text("🎯 **Step 2: Target Link**\n\nSend the link (t.me/...) of the message or channel you want to report.")

    elif state["step"] == "WAIT_TARGET":
        try:
            state["chat_id"], state["msg_id"] = parse_target(txt)
            state["target_url"] = txt
            state["step"] = "WAIT_REASON"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Spam", callback_data="r_code_1"), InlineKeyboardButton("Violence", callback_data="r_code_2")],
                [InlineKeyboardButton("Child Abuse", callback_data="r_code_3"), InlineKeyboardButton("Pornography", callback_data="r_code_4")],
                [InlineKeyboardButton("Other", callback_data="r_code_8")]
            ])
            await message.reply_text("⚖️ **Step 3: Reason**\n\nSelect the report type:", reply_markup=kb)
        except Exception as e:
            await message.reply_text(f"❌ {e}")

    elif state["step"] == "WAIT_DESC":
        state["desc"] = txt
        state["step"] = "WAIT_COUNT"
        await message.reply_text("🔢 **Step 5: Count**\n\nHow many reports in total?")

    elif state["step"] == "WAIT_COUNT":
        if txt.isdigit():
            state["count"] = int(txt)
            asyncio.create_task(run_reporting(message, state))
            del U_STATE[uid]
        else: await message.reply_text("Please enter a number.")

async def run_reporting(msg, config):
    uid = msg.from_user.id
    panel = await msg.reply_text("🛠️ **Initializing Advanced Panel...**")
    
    sessions = await get_sessions(uid)
    active_clients = []
    
    # 1. Start Clients & Auto-Join
    for i, s in enumerate(sessions):
        c = Client(name=f"u{uid}_{i}", api_id=Config.API_ID, api_hash=Config.API_HASH, session_string=s, in_memory=True, no_updates=True)
        try:
            await c.start()
            if config["join_link"]: await auto_join(c, config["join_link"])
            active_clients.append(c)
        except: continue
    
    if not active_clients:
        return await panel.edit_text("❌ All sessions failed. Please re-add active sessions.")

    # 2. Main Loop
    success, failed = 0, 0
    total = config["count"]
    
    for i in range(total):
        curr_c = active_clients[i % len(active_clients)]
        res = await send_single_report(curr_c, config["chat_id"], config["msg_id"], config["code"], config["desc"])
        if res: success += 1
        else: failed += 1
        
        # Live Update UI
        if i % 5 == 0 or i == total - 1:
            try:
                await panel.edit_text(get_progress_card(config["target_url"], success, failed, total, len(active_clients)))
            except: pass
        await asyncio.sleep(0.3)

    for c in active_clients: await c.stop()
    await msg.reply_text("✅ **Reporting Completed.** Check stats above.")

if __name__ == "__main__":
    print("Bot Booting...")
    app.run()
