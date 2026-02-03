# main.py
import asyncio, os, sys, logging
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from pyrogram.errors import UserNotParticipant

from config import Config
from database.mongo import (
    add_session, get_sessions, is_sudo, get_bot_settings, 
    update_bot_settings, add_sudo, remove_sudo, get_all_sudos,
    cleanup_invalid_sessions, get_user_contribution_count
)
from utils.helpers import parse_target, auto_join, get_progress_card
from utils.user_guide import GUIDE_TEXT
from report import send_single_report

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Client("OxyBot", api_id=Config.API_ID, api_hash=Config.API_HASH, bot_token=Config.BOT_TOKEN, in_memory=True)
U_STATE = {}

async def verify_user(uid):
    """Checks Requirements: 1. Force Sub | 2. Contribution Count (min 3)"""
    try:
        settings = await get_bot_settings()
        sudo = await is_sudo(uid)
        
        # 1. Force Join Check
        fsub = settings.get("force_sub")
        if fsub and not sudo:
            try:
                f_str = str(fsub)
                chat = f_str if f_str.startswith("-100") or f_str.isdigit() else f"@{f_str.replace('@', '')}"
                await app.get_chat_member(chat, uid)
            except UserNotParticipant: 
                return "JOIN_REQUIRED", f_str.replace("@", "")
            except: pass
        
        # 2. Contribution Check (Min 3 sessions required from user)
        if not sudo:
            count = await get_user_contribution_count(uid)
            if count < 3:
                return "MIN_CONTRIBUTION", 3 - count
        
        return "OK", None
    except: return "OK", None

@app.on_message(filters.command("start", Config.PREFIX) & filters.private)
async def start_handler(client, message: Message):
    uid = message.from_user.id
    status, data = await verify_user(uid)
    
    if status == "JOIN_REQUIRED":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{data}")]])
        return await message.reply_text("🚫 **Access Denied!**\nJoin our channel and click /start again.", reply_markup=kb)
    
    pool = await get_sessions()
    kb = [[InlineKeyboardButton("🚀 Launch Reporter", callback_data="launch_flow")],
          [InlineKeyboardButton("📂 Global Pool", callback_data="manage_sessions"), InlineKeyboardButton("📖 Guide", callback_data="open_guide")]]
    
    if uid == Config.OWNER_ID:
        kb.append([InlineKeyboardButton("⚙️ Owner Panel", callback_data="owner_panel")])
    else:
        kb.append([InlineKeyboardButton("➕ Contribute Sessions", callback_data="add_sess_p")])

    welcome = f"💎 **Ultimate OxyReport Pro v3.0**\n\nWelcome back, **{message.from_user.first_name}**!\n"
    if status == "MIN_CONTRIBUTION":
        welcome += f"\n⚠️ **Locked:** You need `{data}` more contributions to unlock Reporting."
    else:
        welcome += f"Status: `Operational ✅` | Pool: `{len(pool)}` Accounts"

    await message.reply_text(welcome, reply_markup=InlineKeyboardMarkup(kb))

@app.on_callback_query()
async def cb_handler(client, cb: CallbackQuery):
    uid, data = cb.from_user.id, cb.data
    
    # Instant Buttons (No verification lag)
    if data == "open_guide":
        return await cb.edit_message_text(GUIDE_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="start_back")]]))
    
    if data == "start_back":
        U_STATE.pop(uid, None)
        return await start_handler(client, cb.message)

    # Security Verification
    status, val = await verify_user(uid)
    if status == "JOIN_REQUIRED": return await cb.answer(f"🚫 Join @{val} first!", True)
    if status == "MIN_CONTRIBUTION" and data not in ["add_sess_p", "manage_sessions"]:
        return await cb.answer(f"🚫 Contribute {val} more sessions to unlock!", True)

    # Functionality
    if data == "owner_panel" and uid == Config.OWNER_ID:
        s = await get_bot_settings()
        kb = [[InlineKeyboardButton(f"Min: {s.get('min_sessions', 3)}", callback_data="set_min"), InlineKeyboardButton(f"F-Sub: @{s.get('force_sub') or 'None'}", callback_data="set_fsub")],
              [InlineKeyboardButton("👤 Sudos", callback_data="list_sudo"), InlineKeyboardButton("🗑 Wipe (DISABLED)", callback_data="wipe_locked")],
              [InlineKeyboardButton("🔙 Back", callback_data="start_back")]]
        await cb.edit_message_text("⚙️ **Owner Panel**", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "wipe_locked":
        await cb.answer("🛡️ System Policy: Wipe is disabled to protect Global Pool.", True)

    elif data == "launch_flow":
        sudo = await is_sudo(uid)
        if not sudo: return await cb.answer("🚫 Only Sudos can use Global Pool!", True)
        
        all_s = await get_sessions()
        if not all_s: return await cb.answer("❌ Global Pool is empty!", True)
        
        U_STATE[uid] = {"step": "WAIT_JOIN", "sessions": all_s}
        await cb.edit_message_text(f"🚀 **Pool Ready:** `{len(all_s)}` Accounts\n\n🔗 Send Invite Link or `/skip`:")

    elif data == "manage_sessions":
        all_s = await get_sessions()
        contributed = await get_user_contribution_count(uid)
        kb = [[InlineKeyboardButton("➕ Add More", callback_data="add_sess_p")], [InlineKeyboardButton("🔙 Back", callback_data="start_back")]]
        await cb.edit_message_text(f"📂 **Pool Insight**\n━━━━━━━━━━━━\nTotal: **{len(all_s)}** sessions\nYour Work: **{contributed}/3**\n\nAdd sessions to unlock benefits!", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "add_sess_p":
        U_STATE[uid] = {"step": "WAIT_SESS_ONLY"}
        await cb.edit_message_text("💾 **Contribution Pad:**\nSend Pyrogram strings (comma separated):")

    elif data.startswith("rc_"): # Reason Code selection
        U_STATE[uid]["code"] = data.split("_")[1]
        U_STATE[uid]["step"] = "WAIT_DESC"
        await cb.edit_message_text("✏️ **Reason Details:** Enter short description for report:")

@app.on_message(filters.private & filters.text)
async def msg_handler(client, message: Message):
    uid, txt = message.from_user.id, message.text
    if uid not in U_STATE: return
    state = U_STATE[uid]

    if state["step"] == "WAIT_SESS_ONLY":
        sess = [s.strip() for s in txt.split(",") if len(s.strip()) > 100]
        count = 0
        for s in sess: 
            if await add_session(uid, s): count += 1
        await message.reply_text(f"✅ {count} sessions added!\nRequirement: 3 total sessions."); U_STATE.pop(uid)

    elif state["step"] == "WAIT_JOIN":
        state["join"] = txt if txt != "/skip" else None
        state["step"] = "WAIT_TARGET"
        await message.reply_text("🎯 **Send Target Link:**")

    elif state["step"] == "WAIT_TARGET":
        try:
            state["cid"], state["mid"] = parse_target(txt)
            state["url"] = txt
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Spam", callback_data="rc_1"), InlineKeyboardButton("Violence", callback_data="rc_2")], [InlineKeyboardButton("Porn", callback_data="rc_4"), InlineKeyboardButton("Other", callback_data="rc_8")]])
            state["step"] = "WAIT_REASON"
            await message.reply_text("⚖️ **Select Category:**", reply_markup=kb)
        except: await message.reply_text("❌ Invalid Link!")

    elif state["step"] == "WAIT_DESC":
        state["desc"] = txt; state["step"] = "WAIT_COUNT"
        await message.reply_text("🔢 **Report Count?**")

    elif state["step"] == "WAIT_COUNT" and txt.isdigit():
        state["count"] = int(txt)
        asyncio.create_task(process_reports(message, state))
        U_STATE.pop(uid)

async def start_instance(s, uid, i, join):
    cl = Client(name=f"c_{uid}_{i}_{int(asyncio.get_event_loop().time())}", api_id=Config.API_ID, api_hash=Config.API_HASH, session_string=s, in_memory=True)
    try:
        await cl.start()
        if join: await auto_join(cl, join)
        return cl
    except: return None

async def process_reports(msg, config):
    panel = await msg.reply_text("⏳ **Initializing Secure Global Pool...**")
    uid, sessions = msg.from_user.id, config.get("sessions", [])
    
    # Parallel thread startup
    tasks = [start_instance(s, uid, i, config.get("join")) for i, s in enumerate(sessions)]
    clients = [c for c in await asyncio.gather(*tasks) if c]
    
    if not clients: return await panel.edit_text("❌ All sessions in the pool failed to initialize.")
    
    suc, err, tot = 0, 0, config["count"]
    for i in range(tot):
        worker = clients[i % len(clients)]
        res = await send_single_report(worker, config["cid"], config["mid"], config["code"], config["desc"])
        if res: suc += 1
        else: err += 1
        if i % 3 == 0 or i == tot-1:
            try: await panel.edit_text(get_progress_card(config["url"], suc, err, tot, len(clients)))
            except: pass
        await asyncio.sleep(0.3)
    
    for c in clients: await c.stop()
    await msg.reply_text(f"🏁 **Execution Detailed:**\nTarget: {config['url']}\nTotal Reports Sent: **{suc}**")

async def run_bot():
    logger.info("Initializing Oxygen Deep Scan Audit...")
    await cleanup_invalid_sessions()
    logger.info("Deep Scan Complete. Project Powered UP!")
    await app.start(); await idle(); await app.stop()

if __name__ == "__main__":
    asyncio.run(run_bot())
