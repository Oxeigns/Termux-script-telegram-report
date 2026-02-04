# report.py
import asyncio
import logging
from pyrogram import Client
from pyrogram.raw import functions, types
from pyrogram.errors import RPCError, FloodWait, PeerIdInvalid, ChannelInvalid, ChannelPrivate

logger = logging.getLogger("OxyReport")

async def send_single_report(client: Client, chat_id: int | str, msg_id: int | None, reason_code: str, description: str):
    """
    ULTIMATE REPORT ENGINE v3.6:
    Syncs Peer ID and handles numeric ID resolution without access_hash.
    """
    try:
        # STEP 1: DEEP RESOLUTION
        # Agar numeric ID hai (-100...), toh worker ko member hona zaroori hai.
        try:
            peer = await client.resolve_peer(chat_id)
        except (PeerIdInvalid, ChannelInvalid, RPCError):
            try:
                # Force synchronization by fetching the chat directly
                # Note: This will FAIL if the worker is not a member of the private chat.
                chat = await client.get_chat(chat_id)
                peer = await client.resolve_peer(chat.id)
            except Exception as e:
                # Agar yaha fail hua, matlab worker chat ka member nahi hai.
                logger.error(f"Worker {client.name} - PeerIdInvalid: Ensure workers joined the chat first!")
                return False

        # STEP 2: REASON SELECTION
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

        # STEP 3: EXECUTION
        if msg_id:
            await client.invoke(
                functions.messages.Report(
                    peer=peer,
                    id=[int(msg_id)],
                    reason=selected_reason,
                    message=description
                )
            )
        else:
            await client.invoke(
                functions.account.ReportPeer(
                    peer=peer,
                    reason=selected_reason,
                    message=description
                )
            )
        logger.info(f"Worker {client.name} - Success ✅")
        return True

    except FloodWait as e:
        if e.value > 100: return False
        await asyncio.sleep(e.value)
        return await send_single_report(client, chat_id, msg_id, reason_code, description)
    except Exception:
        return False
