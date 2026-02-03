# report.py
import asyncio
import logging
from pyrogram import Client
from pyrogram.raw import functions, types
from pyrogram.errors import RPCError, FloodWait, PeerIdInvalid, ChannelInvalid

logger = logging.getLogger(__name__)

async def send_single_report(client: Client, chat_id: int | str, msg_id: int | None, reason_code: str, description: str):
    """
    ULTIMATE REPORT ENGINE: 
    Executes raw MTProto calls for mass reporting with intelligent throttling.
    """
    try:
        # 1. PEER RESOLUTION (With fail-safe)
        try:
            peer = await client.resolve_peer(chat_id)
        except (PeerIdInvalid, ChannelInvalid):
            # In case the session hasn't seen the chat, try fetching it first
            try:
                chat = await client.get_chat(chat_id)
                peer = await client.resolve_peer(chat.id)
            except Exception as e:
                logger.error(f"Failed to resolve peer on {client.name}: {e}")
                return False

        # 2. REASON MAPPING
        reasons = {
            '1': types.InputReportReasonSpam(),
            '2': types.InputReportReasonViolence(),
            '3': types.InputReportReasonChildAbuse(),
            '4': types.InputReportReasonPornography(),
            '5': types.InputReportReasonFake(),
            '6': types.InputReportReasonIllegalDrugs(),
            '7': types.InputReportReasonPersonalDetails(),
            '8': types.InputReportReasonOther()
        }
        
        selected_reason = reasons.get(str(reason_code), types.InputReportReasonOther())

        # 3. EXECUTION LOGIC
        if msg_id:
            # Report a specific Message (Targeted Reporting)
            await client.invoke(
                functions.messages.Report(
                    peer=peer,
                    id=[int(msg_id)],
                    reason=selected_reason,
                    message=description
                )
            )
        else:
            # Report Peer/Entity (Channel, User, or Bot)
            await client.invoke(
                functions.account.ReportPeer(
                    peer=peer,
                    reason=selected_reason,
                    message=description
                )
            )
        
        logger.info(f"Report sent successfully using session: {client.name}")
        return True

    except FloodWait as e:
        # CRITICAL: Prevent bot from hanging on 24h+ bans
        if e.value > 600: # If wait is > 10 minutes, skip this worker for now
            logger.warning(f"Session {client.name} huge FloodWait ({e.value}s). Skipping.")
            return False
            
        logger.warning(f"Throttling session {client.name}: Sleeping {e.value}s")
        await asyncio.sleep(e.value)
        return await send_single_report(client, chat_id, msg_id, reason_code, description)

    except RPCError as e:
        # Handles Internal API errors safely
        logger.debug(f"RPC Error on {client.name}: {e.message}")
        return False

    except Exception as e:
        logger.error(f"Report Engine Error: {e}")
        return False
