import os, json, asyncio, zipfile, shutil, time, random, logging
from telethon import TelegramClient, events, Button
from telethon.errors import SessionPasswordNeededError, FloodWaitError, PhoneCodeInvalidError, PhoneNumberInvalidError, UserPrivacyRestrictedError, ChannelPrivateError
from telethon.tl.functions.account import ReportPeerRequest
from telethon.tl.functions.messages import ReportRequest
from telethon.tl.types import InputReportReasonSpam, InputReportReasonViolence, InputReportReasonPornography, InputReportReasonChildAbuse, InputReportReasonCopyright, InputReportReasonFake, InputReportReasonIllegalDrugs, InputReportReasonPersonalDetails, InputReportReasonOther, InputReportReasonGeoIrrelevant
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

API_ID = 25723056
API_HASH = "cbda56fac135e92b755e1243aefe9697"
BOT_TOKEN = "8528337956:AAGU7PX6JooceLLL7HkH_LJ27v-QaKyrZVw"
SESSIONS_DIR = "sessions_db"
TEMP_DIR = "temp_files"
DATA_DIR = "data"
os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

def load_data(file, default=None):
    try:
        with open(file, 'r') as f:
            return json.load(f)
    except:
        return default or {}

def save_data(file, data):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2)

user_sessions = load_data(os.path.join(DATA_DIR, 'user_sessions.json'), {})
user_states = {}
report_stats = load_data(os.path.join(DATA_DIR, 'report_stats.json'), {})
user_settings = load_data(os.path.join(DATA_DIR, 'user_settings.json'), {})
flood_control = {}

REPORT_REASONS = {
    "1": ("Spam", InputReportReasonSpam()),
    "2": ("Violence", InputReportReasonViolence()),
    "3": ("Pornography", InputReportReasonPornography()),
    "4": ("Child Abuse", InputReportReasonChildAbuse()),
    "5": ("Copyright", InputReportReasonCopyright()),
    "6": ("Fake Account", InputReportReasonFake()),
    "7": ("Illegal Drugs", InputReportReasonIllegalDrugs()),
    "8": ("Personal Details", InputReportReasonPersonalDetails()),
    "9": ("Geo Irrelevant", InputReportReasonGeoIrrelevant()),
    "10": ("Other", InputReportReasonOther())
}

def get_user_setting(user_id, key, default=None):
    uid = str(user_id)
    if uid not in user_settings:
        user_settings[uid] = {}
    return user_settings[uid].get(key, default)

def set_user_setting(user_id, key, value):
    uid = str(user_id)
    if uid not in user_settings:
        user_settings[uid] = {}
    user_settings[uid][key] = value
    save_data(os.path.join(DATA_DIR, 'user_settings.json'), user_settings)

def get_user_sessions(user_id):
    return user_sessions.get(str(user_id), [])

def add_user_session(user_id, session_data):
    uid = str(user_id)
    if uid not in user_sessions:
        user_sessions[uid] = []
    user_sessions[uid].append(session_data)
    save_data(os.path.join(DATA_DIR, 'user_sessions.json'), user_sessions)

def remove_user_session(user_id, phone):
    uid = str(user_id)
    if uid in user_sessions:
        user_sessions[uid] = [s for s in user_sessions[uid] if s['phone'] != phone]
        save_data(os.path.join(DATA_DIR, 'user_sessions.json'), user_sessions)

def update_report_stats(user_id, success=0, failed=0):
    uid = str(user_id)
    if uid not in report_stats:
        report_stats[uid] = {'success': 0, 'failed': 0, 'total': 0}
    report_stats[uid]['success'] += success
    report_stats[uid]['failed'] += failed
    report_stats[uid]['total'] += (success + failed)
    save_data(os.path.join(DATA_DIR, 'report_stats.json'), report_stats)

async def create_session(user_id, phone):
    session_name = f"{user_id}_{phone.replace('+', '')}"
    session_path = os.path.join(SESSIONS_DIR, session_name)
    client = TelegramClient(session_path, API_ID, API_HASH)
    await client.connect()
    return client, session_name

async def test_session_file(session_path):
    try:
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            await client.disconnect()
            return True, me.phone, me.first_name
        await client.disconnect()
        return False, None, None
    except Exception as e:
        logger.error(f"Session test error: {e}")
        return False, None, None

async def do_report_user(session_path, target, reason, message="Violating ToS"):
    try:
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return False, "Not authorized"
        entity = await client.get_entity(target)
        await client(ReportPeerRequest(peer=entity, reason=reason, message=message))
        await client.disconnect()
        return True, "Success"
    except FloodWaitError as e:
        return False, f"FloodWait {e.seconds}s"
    except UserPrivacyRestrictedError:
        return False, "Privacy restricted"
    except ChannelPrivateError:
        return False, "Private channel"
    except Exception as e:
        return False, str(e)[:50]

async def do_report_message(session_path, target, message_ids, reason):
    try:
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return False, "Not authorized"
        entity = await client.get_entity(target)
        await client(ReportRequest(peer=entity, id=message_ids, reason=reason, message="Violating ToS"))
        await client.disconnect()
        return True, "Success"
    except FloodWaitError as e:
        return False, f"FloodWait {e.seconds}s"
    except Exception as e:
        return False, str(e)[:50]

async def do_report_multiple(session_path, targets, reason, delay=1):
    results = {'success': 0, 'failed': 0, 'errors': []}
    client = None
    try:
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            return results
        for target in targets:
            try:
                entity = await client.get_entity(target)
                await client(ReportPeerRequest(peer=entity, reason=reason, message="Violating ToS"))
                results['success'] += 1
                await asyncio.sleep(delay)
            except FloodWaitError as e:
                results['failed'] += 1
                results['errors'].append(f"{target}: FloodWait {e.seconds}s")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                results['failed'] += 1
                results['errors'].append(f"{target}: {str(e)[:30]}")
    except Exception as e:
        logger.error(f"Report multiple error: {e}")
    finally:
        if client:
            await client.disconnect()
    return results

bot = TelegramClient('report_bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

@bot.on(events.NewMessage(pattern='/start'))
async def start_cmd(event):
    user_id = event.sender_id
    sessions = get_user_sessions(user_id)
    
    text = "⚡ **ADVANCED MULTI-REPORT BOT v7.0**\n\n"
    text += "🔥 **ALL FEATURES ACTIVATED**\n\n"
    text += "**✅ Report Methods:**\n"
    text += "• User/Channel Reports (Profile)\n"
    text += "• Message Reports (Posts)\n"
    text += "• Group Reports (Communities)\n"
    text += "• Bulk Reports (Multiple Targets)\n"
    text += "• Advanced Report Settings\n\n"
    text += "**📱 Session Management:**\n"
    text += "• Add via Phone Number\n"
    text += "• Upload .session Files\n"
    text += "• Bulk Upload ZIP Files\n"
    text += "• Auto-Validation System\n\n"
    text += f"**📊 Your Stats:**\n"
    text += f"• Sessions: {len(sessions)}\n"
    text += f"• Reports: {report_stats.get(str(user_id), {}).get('total', 0)}\n"
    text += f"• Success Rate: {calculate_success_rate(user_id)}%"
    
    buttons = [
        [Button.inline("📱 Sessions", b"session_menu"), Button.inline("🎯 Report", b"report_menu")],
        [Button.inline("⚙️ Settings", b"settings_menu"), Button.inline("📊 Statistics", b"stats_menu")],
        [Button.inline("❓ Help", b"help_menu"), Button.inline("📖 Guide", b"guide_menu")]
    ]
    await event.respond(text, buttons=buttons)

@bot.on(events.NewMessage(pattern='/help'))
async def help_cmd(event):
    text = "📚 **ADVANCED REPORT BOT - COMPLETE GUIDE**\n\n"
    text += "**🎯 REPORTING METHODS:**\n\n"
    text += "**1️⃣ User/Channel Report:**\n"
    text += "• Reports user profiles or channels\n"
    text += "• Use: Username, User ID, or Link\n"
    text += "• Example: @username or t.me/username\n\n"
    text += "**2️⃣ Message Report:**\n"
    text += "• Reports specific posts/messages\n"
    text += "• Use: Message link from Telegram\n"
    text += "• Example: t.me/channel/12345\n\n"
    text += "**3️⃣ Group Report:**\n"
    text += "• Reports entire groups/channels\n"
    text += "• Use: Group username or invite link\n\n"
    text += "**4️⃣ Bulk Report:**\n"
    text += "• Report multiple targets at once\n"
    text += "• Use: List of usernames/links\n\n"
    text += "**📱 SESSION MANAGEMENT:**\n"
    text += "• Add by Phone: /add_session\n"
    text += "• Upload .session: Send file directly\n"
    text += "• Bulk Upload: Send .zip with sessions\n"
    text += "• View All: /my_sessions\n\n"
    text += "**⚙️ ADVANCED SETTINGS:**\n"
    text += "• Reports Per Session Limit\n"
    text += "• Delay Between Reports\n"
    text += "• Auto-Retry on Failure\n"
    text += "• Random Session Selection\n\n"
    text += "**📊 CATEGORIES (1-10):**\n"
    for key, (name, _) in REPORT_REASONS.items():
        text += f"{key}. {name}\n"
    
    await event.respond(text)

def calculate_success_rate(user_id):
    uid = str(user_id)
    if uid not in report_stats:
        return 0
    stats = report_stats[uid]
    total = stats.get('total', 0)
    if total == 0:
        return 0
    success = stats.get('success', 0)
    return int((success / total) * 100)

@bot.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    
    if data == "session_menu":
        sessions = get_user_sessions(user_id)
        text = f"📱 **SESSION MANAGEMENT**\n\n"
        text += f"**Active Sessions:** {len(sessions)}\n"
        text += f"**Verified:** {sum(1 for s in sessions if s.get('verified'))}\n"
        text += f"**Pending:** {sum(1 for s in sessions if not s.get('verified'))}\n\n"
        text += "**Choose an action:**"
        
        buttons = [
            [Button.inline("➕ Add Session", b"add_session"), Button.inline("📋 View All", b"view_sessions")],
            [Button.inline("📤 Upload File", b"upload_session"), Button.inline("📦 Bulk Upload", b"bulk_upload")],
            [Button.inline("🗑️ Remove Session", b"remove_session"), Button.inline("🔄 Refresh", b"refresh_sessions")],
            [Button.inline("🏠 Main Menu", b"start")]
        ]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_menu":
        sessions = get_user_sessions(user_id)
        if not sessions:
            await event.answer("❌ Add sessions first!", alert=True)
            return
        
        text = "🎯 **REPORTING CENTER**\n\n"
        text += "**Select Report Type:**\n\n"
        text += "**1️⃣ User/Channel Report**\n"
        text += "• Report profiles and channels\n\n"
        text += "**2️⃣ Message Report**\n"
        text += "• Report specific posts\n\n"
        text += "**3️⃣ Group Report**\n"
        text += "• Report entire groups\n\n"
        text += "**4️⃣ Bulk Report**\n"
        text += "• Report multiple targets\n\n"
        text += f"**Available Sessions:** {len(sessions)}"
        
        buttons = [
            [Button.inline("👤 User/Channel", b"report_user"), Button.inline("💬 Message", b"report_message")],
            [Button.inline("👥 Group", b"report_group"), Button.inline("📋 Bulk", b"report_bulk")],
            [Button.inline("🎯 Quick Report", b"quick_report"), Button.inline("🔧 Advanced", b"advanced_report")],
            [Button.inline("🏠 Main Menu", b"start")]
        ]
        await event.edit(text, buttons=buttons)
    
    elif data == "settings_menu":
        limit = get_user_setting(user_id, 'reports_per_session', 10)
        delay = get_user_setting(user_id, 'report_delay', 1)
        retry = get_user_setting(user_id, 'auto_retry', True)
        randomize = get_user_setting(user_id, 'randomize_sessions', False)
        
        text = "⚙️ **ADVANCED SETTINGS**\n\n"
        text += f"**Current Configuration:**\n"
        text += f"• Reports Per Session: {limit}\n"
        text += f"• Delay Between Reports: {delay}s\n"
        text += f"• Auto-Retry Failed: {'✅' if retry else '❌'}\n"
        text += f"• Random Session Order: {'✅' if randomize else '❌'}\n\n"
        text += "**Modify Settings:**"
        
        buttons = [
            [Button.inline(f"📊 Limit: {limit}", b"set_limit"), Button.inline(f"⏱️ Delay: {delay}s", b"set_delay")],
            [Button.inline(f"{'✅' if retry else '❌'} Auto-Retry", b"toggle_retry"), Button.inline(f"{'✅' if randomize else '❌'} Randomize", b"toggle_random")],
            [Button.inline("🔄 Reset Defaults", b"reset_settings"), Button.inline("💾 Export Config", b"export_config")],
            [Button.inline("🏠 Main Menu", b"start")]
        ]
        await event.edit(text, buttons=buttons)
    
    elif data == "stats_menu":
        uid = str(user_id)
        stats = report_stats.get(uid, {'success': 0, 'failed': 0, 'total': 0})
        sessions = get_user_sessions(user_id)
        
        text = "📊 **YOUR STATISTICS**\n\n"
        text += f"**Sessions:**\n"
        text += f"• Total: {len(sessions)}\n"
        text += f"• Active: {sum(1 for s in sessions if s.get('verified'))}\n\n"
        text += f"**Reports:**\n"
        text += f"• Total Submitted: {stats['total']}\n"
        text += f"• Successful: {stats['success']} ✅\n"
        text += f"• Failed: {stats['failed']} ❌\n"
        text += f"• Success Rate: {calculate_success_rate(user_id)}%\n\n"
        text += f"**Performance:**\n"
        text += f"• Average per Session: {stats['total'] // len(sessions) if sessions else 0}\n"
        text += f"• Best Success Rate: {calculate_success_rate(user_id)}%"
        
        buttons = [
            [Button.inline("📈 Detailed Stats", b"detailed_stats"), Button.inline("🗑️ Clear Stats", b"clear_stats")],
            [Button.inline("📊 Export Report", b"export_stats"), Button.inline("🏠 Main Menu", b"start")]
        ]
        await event.edit(text, buttons=buttons)
    
    elif data == "add_session":
        user_states[user_id] = {'state': 'waiting_phone'}
        text = "📱 **ADD NEW SESSION**\n\n"
        text += "**Method 1: Phone Number**\n"
        text += "Send your phone with country code:\n"
        text += "Examples:\n"
        text += "• +919876543210\n"
        text += "• +12025551234\n"
        text += "• +447911123456\n\n"
        text += "**Method 2: Upload File**\n"
        text += "Send .session file directly\n\n"
        text += "**Method 3: Bulk Upload**\n"
        text += "Send .zip with multiple sessions"
        
        buttons = [[Button.inline("❌ Cancel", b"session_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "view_sessions":
        sessions = get_user_sessions(user_id)
        if not sessions:
            await event.answer("❌ No sessions found!", alert=True)
            return
        
        text = f"📱 **YOUR SESSIONS ({len(sessions)})**\n\n"
        for i, s in enumerate(sessions, 1):
            status = "✅" if s.get('verified') else "⏳"
            text += f"**{i}. {status} {s['phone']}**\n"
            text += f"   Name: {s.get('name', 'Unknown')}\n"
            text += f"   Added: {s.get('added', 'Unknown')}\n"
            if s.get('last_used'):
                text += f"   Last Used: {s['last_used']}\n"
            text += "\n"
        
        buttons = [
            [Button.inline("➕ Add More", b"add_session"), Button.inline("🗑️ Remove", b"remove_session")],
            [Button.inline("🏠 Main Menu", b"start")]
        ]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_user":
        sessions = get_user_sessions(user_id)
        text = "👤 **USER/CHANNEL REPORT**\n\n"
        text += f"**Available Sessions:** {len(sessions)}\n\n"
        text += "**Choose reporting method:**"
        
        buttons = [
            [Button.inline("🎯 Use All Sessions", b"report_user_all")],
            [Button.inline("📱 Select Specific Sessions", b"report_user_select")],
            [Button.inline("❌ Cancel", b"report_menu")]
        ]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_user_all":
        user_states[user_id] = {'state': 'report_user_target', 'type': 'user', 'session_mode': 'all'}
        text = "👤 **USER/CHANNEL REPORT (ALL SESSIONS)**\n\n"
        text += "**Send target information:**\n\n"
        text += "**Accepted Formats:**\n"
        text += "• Username: @username\n"
        text += "• User ID: 123456789\n"
        text += "• Profile Link: t.me/username\n"
        text += "• Full URL: https://t.me/username\n\n"
        text += "**Example:** @spammer"
        
        buttons = [[Button.inline("❌ Cancel", b"report_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_user_select":
        sessions = get_user_sessions(user_id)
        if not sessions:
            await event.answer("❌ No sessions available!", alert=True)
            return
        
        text = "📱 **SELECT SESSIONS FOR REPORTING**\n\n"
        text += "**Available Sessions:**\n\n"
        for i, s in enumerate(sessions, 1):
            status = "✅" if s.get('verified') else "⏳"
            text += f"{i}. {status} {s['phone']} - {s.get('name', 'Unknown')}\n"
        
        text += "\n**Send session numbers (comma separated):**\n"
        text += "Examples:\n"
        text += "• 1\n"
        text += "• 1,2,3\n"
        text += "• 1-5\n"
        text += "• all (for all sessions)"
        
        user_states[user_id] = {'state': 'selecting_sessions', 'type': 'user'}
        buttons = [[Button.inline("❌ Cancel", b"report_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_message":
        sessions = get_user_sessions(user_id)
        text = "💬 **MESSAGE REPORT**\n\n"
        text += f"**Available Sessions:** {len(sessions)}\n\n"
        text += "**Choose reporting method:**"
        
        buttons = [
            [Button.inline("🎯 Use All Sessions", b"report_message_all")],
            [Button.inline("📱 Select Specific Sessions", b"report_message_select")],
            [Button.inline("❌ Cancel", b"report_menu")]
        ]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_message_all":
        user_states[user_id] = {'state': 'report_message_link', 'type': 'message', 'session_mode': 'all'}
        text = "💬 **MESSAGE REPORT (ALL SESSIONS)**\n\n"
        text += "**Send message link:**\n\n"
        text += "**How to get message link:**\n"
        text += "1. Open Telegram message\n"
        text += "2. Click three dots (⋮)\n"
        text += "3. Select 'Copy Link'\n"
        text += "4. Send link here\n\n"
        text += "**Example:**\n"
        text += "t.me/channel/12345\n"
        text += "https://t.me/c/123456789/10"
        
        buttons = [[Button.inline("❌ Cancel", b"report_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_message_select":
        sessions = get_user_sessions(user_id)
        if not sessions:
            await event.answer("❌ No sessions available!", alert=True)
            return
        
        text = "📱 **SELECT SESSIONS FOR MESSAGE REPORT**\n\n"
        text += "**Available Sessions:**\n\n"
        for i, s in enumerate(sessions, 1):
            status = "✅" if s.get('verified') else "⏳"
            text += f"{i}. {status} {s['phone']} - {s.get('name', 'Unknown')}\n"
        
        text += "\n**Send session numbers (comma separated):**\n"
        text += "Examples:\n"
        text += "• 1\n"
        text += "• 1,2,3\n"
        text += "• 1-5\n"
        text += "• all (for all sessions)"
        
        user_states[user_id] = {'state': 'selecting_sessions', 'type': 'message'}
        buttons = [[Button.inline("❌ Cancel", b"report_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_group":
        sessions = get_user_sessions(user_id)
        text = "👥 **GROUP REPORT**\n\n"
        text += f"**Available Sessions:** {len(sessions)}\n\n"
        text += "**Choose reporting method:**"
        
        buttons = [
            [Button.inline("🎯 Use All Sessions", b"report_group_all")],
            [Button.inline("📱 Select Specific Sessions", b"report_group_select")],
            [Button.inline("❌ Cancel", b"report_menu")]
        ]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_group_all":
        user_states[user_id] = {'state': 'report_group_target', 'type': 'group', 'session_mode': 'all'}
        text = "👥 **GROUP REPORT (ALL SESSIONS)**\n\n"
        text += "**Send group information:**\n\n"
        text += "**Accepted Formats:**\n"
        text += "• Username: @groupname\n"
        text += "• Invite Link: t.me/joinchat/xxx\n"
        text += "• Public Link: t.me/groupname\n\n"
        text += "**Example:** @spamgroup"
        
        buttons = [[Button.inline("❌ Cancel", b"report_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_group_select":
        sessions = get_user_sessions(user_id)
        if not sessions:
            await event.answer("❌ No sessions available!", alert=True)
            return
        
        text = "📱 **SELECT SESSIONS FOR GROUP REPORT**\n\n"
        text += "**Available Sessions:**\n\n"
        for i, s in enumerate(sessions, 1):
            status = "✅" if s.get('verified') else "⏳"
            text += f"{i}. {status} {s['phone']} - {s.get('name', 'Unknown')}\n"
        
        text += "\n**Send session numbers (comma separated):**\n"
        text += "Examples:\n"
        text += "• 1\n"
        text += "• 1,2,3\n"
        text += "• 1-5\n"
        text += "• all (for all sessions)"
        
        user_states[user_id] = {'state': 'selecting_sessions', 'type': 'group'}
        buttons = [[Button.inline("❌ Cancel", b"report_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_bulk":
        sessions = get_user_sessions(user_id)
        text = "📋 **BULK REPORT**\n\n"
        text += f"**Available Sessions:** {len(sessions)}\n\n"
        text += "**Choose reporting method:**"
        
        buttons = [
            [Button.inline("🎯 Use All Sessions", b"report_bulk_all")],
            [Button.inline("📱 Select Specific Sessions", b"report_bulk_select")],
            [Button.inline("❌ Cancel", b"report_menu")]
        ]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_bulk_all":
        user_states[user_id] = {'state': 'report_bulk_targets', 'type': 'bulk', 'session_mode': 'all'}
        text = "📋 **BULK REPORT (ALL SESSIONS)**\n\n"
        text += "**Send multiple targets:**\n\n"
        text += "**Format:** One target per line\n"
        text += "**Example:**\n"
        text += "@spammer1\n"
        text += "@spammer2\n"
        text += "t.me/spammer3\n"
        text += "123456789\n\n"
        text += "**Maximum:** 50 targets per bulk"
        
        buttons = [[Button.inline("❌ Cancel", b"report_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_bulk_select":
        sessions = get_user_sessions(user_id)
        if not sessions:
            await event.answer("❌ No sessions available!", alert=True)
            return
        
        text = "📱 **SELECT SESSIONS FOR BULK REPORT**\n\n"
        text += "**Available Sessions:**\n\n"
        for i, s in enumerate(sessions, 1):
            status = "✅" if s.get('verified') else "⏳"
            text += f"{i}. {status} {s['phone']} - {s.get('name', 'Unknown')}\n"
        
        text += "\n**Send session numbers (comma separated):**\n"
        text += "Examples:\n"
        text += "• 1\n"
        text += "• 1,2,3\n"
        text += "• 1-5\n"
        text += "• all (for all sessions)"
        
        user_states[user_id] = {'state': 'selecting_sessions', 'type': 'bulk'}
        buttons = [[Button.inline("❌ Cancel", b"report_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "set_limit":
        user_states[user_id] = {'state': 'setting_limit'}
        text = "📊 **SET REPORTS PER SESSION LIMIT**\n\n"
        text += "**Current:** " + str(get_user_setting(user_id, 'reports_per_session', 10)) + "\n\n"
        text += "**Send new limit (1-100):**\n"
        text += "• Low: 1-10 (Safe)\n"
        text += "• Medium: 11-30 (Balanced)\n"
        text += "• High: 31-50 (Aggressive)\n"
        text += "• Maximum: 51-100 (Risk)\n\n"
        text += "**Recommended:** 10"
        
        buttons = [[Button.inline("❌ Cancel", b"settings_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "set_delay":
        user_states[user_id] = {'state': 'setting_delay'}
        text = "⏱️ **SET DELAY BETWEEN REPORTS**\n\n"
        text += "**Current:** " + str(get_user_setting(user_id, 'report_delay', 1)) + "s\n\n"
        text += "**Send new delay (0-10 seconds):**\n"
        text += "• 0s: No delay (Fast)\n"
        text += "• 1s: Minimal delay (Default)\n"
        text += "• 2-3s: Safe delay\n"
        text += "• 5-10s: Very safe\n\n"
        text += "**Recommended:** 1-2s"
        
        buttons = [[Button.inline("❌ Cancel", b"settings_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "toggle_retry":
        current = get_user_setting(user_id, 'auto_retry', True)
        set_user_setting(user_id, 'auto_retry', not current)
        await event.answer(f"✅ Auto-Retry: {'ON' if not current else 'OFF'}")
        buttons = event.message.buttons
        await event.edit(event.message.text, buttons=buttons)
    
    elif data == "toggle_random":
        current = get_user_setting(user_id, 'randomize_sessions', False)
        set_user_setting(user_id, 'randomize_sessions', not current)
        await event.answer(f"✅ Randomize: {'ON' if not current else 'OFF'}")
        buttons = event.message.buttons
        await event.edit(event.message.text, buttons=buttons)
    
    elif data == "reset_settings":
        set_user_setting(user_id, 'reports_per_session', 10)
        set_user_setting(user_id, 'report_delay', 1)
        set_user_setting(user_id, 'auto_retry', True)
        set_user_setting(user_id, 'randomize_sessions', False)
        await event.answer("✅ Settings reset to defaults!")
        buttons = event.message.buttons
        await event.edit(event.message.text, buttons=buttons)
    
    elif data == "upload_session":
        text = "📤 **UPLOAD SESSION FILE**\n\n"
        text += "**Instructions:**\n"
        text += "1. Send .session file directly\n"
        text += "2. Bot will auto-validate\n"
        text += "3. Only valid sessions added\n\n"
        text += "**Supported:**\n"
        text += "• Single .session file\n"
        text += "• Auto phone detection\n"
        text += "• Instant activation"
        
        buttons = [[Button.inline("❌ Cancel", b"session_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "bulk_upload":
        text = "📦 **BULK SESSION UPLOAD**\n\n"
        text += "**Instructions:**\n"
        text += "1. Create ZIP file\n"
        text += "2. Add all .session files\n"
        text += "3. Upload ZIP to bot\n"
        text += "4. Auto-validation starts\n\n"
        text += "**Features:**\n"
        text += "• Upload 100+ sessions\n"
        text += "• Automatic testing\n"
        text += "• Detailed report\n"
        text += "• Invalid sessions skipped"
        
        buttons = [[Button.inline("❌ Cancel", b"session_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "remove_session":
        sessions = get_user_sessions(user_id)
        if not sessions:
            await event.answer("❌ No sessions to remove!", alert=True)
            return
        
        text = "🗑️ **REMOVE SESSION**\n\n"
        text += "**Send phone number to remove:**\n\n"
        for s in sessions:
            text += f"• {s['phone']}\n"
        
        user_states[user_id] = {'state': 'removing_session'}
        buttons = [[Button.inline("❌ Cancel", b"session_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "help_menu":
        await help_cmd(event)
    
    elif data == "guide_menu":
        text = "📖 **COMPLETE USER GUIDE**\n\n"
        text += "**🎯 HOW TO REPORT:**\n\n"
        text += "**Step 1: Add Sessions**\n"
        text += "• Add via phone number\n"
        text += "• Upload .session files• Upload .zip files
• Get verification codes

Step 2: Choose Report Type
• User/Channel Report
• Message Report
• Group Report
• Bulk Report

Step 3: Select Sessions
• Use all sessions
• Or select specific ones

Step 4: Choose Category
• 10 different categories
• Custom messages

Step 5: Execute
• Auto-retry on failures
• Real-time progress
• Detailed statistics"
        
        buttons = [[Button.inline("🏠 Main Menu", b"start")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "clear_stats":
        uid = str(user_id)
        if uid in report_stats:
            report_stats[uid] = {'success': 0, 'failed': 0, 'total': 0}
            save_data(os.path.join(DATA_DIR, 'report_stats.json'), report_stats)
        await event.answer("✅ Statistics cleared!")
    
    elif data == "start":
        await start_cmd(event)

def parse_session_selection(text, total_sessions):
    selected = set()
    if text.lower() == 'all':
        return list(range(total_sessions))
    parts = text.replace(' ', '').split(',')
    for part in parts:
        try:
            if '-' in part:
                start, end = part.split('-')
                start, end = int(start) - 1, int(end) - 1
                if 0 <= start < total_sessions and 0 <= end < total_sessions:
                    selected.update(range(start, end + 1))
            else:
                num = int(part) - 1
                if 0 <= num < total_sessions:
                    selected.add(num)
        except:
            continue
    return sorted(list(selected))

@bot.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith('/')))
async def message_handler(event):
    user_id = event.sender_id
    state = user_states.get(user_id, {})
    
    if state.get('state') == 'waiting_phone':
        phone = event.text.strip()
        if not phone.startswith('+'):
            await event.respond("❌ Include + and country code!\nExample: +919876543210")
            return
        
        msg = await event.respond("⏳ Connecting...")
        
        try:
            client, session_name = await create_session(user_id, phone)
            await client.send_code_request(phone)
            
            user_states[user_id] = {
                'state': 'waiting_code',
                'phone': phone,
                'client': client,
                'session_name': session_name
            }
            
            await msg.edit(
                f"📱 **Code sent to {phone}**\n\n"
                f"Check your Telegram and send:\n"
                f"/verify CODE\n\n"
                f"**For 2FA accounts:**\n"
                f"/verify CODE PASSWORD\n\n"
                f"Cancel: /cancel_verification"
            )
        except PhoneNumberInvalidError:
            await msg.edit("❌ Invalid phone number!")
            user_states.pop(user_id, None)
        except Exception as e:
            await msg.edit(f"❌ Error: {str(e)}")
            user_states.pop(user_id, None)
    
    elif state.get('state') == 'selecting_sessions':
        sessions = get_user_sessions(user_id)
        selected_indices = parse_session_selection(event.text, len(sessions))
        
        if not selected_indices:
            await event.respond("❌ Invalid selection! Try again or send 'all'")
            return
        
        selected_sessions = [sessions[i] for i in selected_indices]
        user_states[user_id]['selected_sessions'] = selected_sessions
        
        report_type = state.get('type', 'user')
        if report_type == 'user':
            user_states[user_id]['state'] = 'report_user_target'
            text = f"✅ **{len(selected_sessions)} sessions selected**\n\n"
            text += "**Send target:**\n"
            text += "• Username: @username\n"
            text += "• User ID: 123456789\n"
            text += "• Link: t.me/username"
        elif report_type == 'message':
            user_states[user_id]['state'] = 'report_message_link'
            text = f"✅ **{len(selected_sessions)} sessions selected**\n\n"
            text += "**Send message link:**\n"
            text += "Example: t.me/channel/12345"
        elif report_type == 'group':
            user_states[user_id]['state'] = 'report_group_target'
            text = f"✅ **{len(selected_sessions)} sessions selected**\n\n"
            text += "**Send group:**\n"
            text += "• Username: @groupname\n"
            text += "• Link: t.me/groupname"
        elif report_type == 'bulk':
            user_states[user_id]['state'] = 'report_bulk_targets'
            text = f"✅ **{len(selected_sessions)} sessions selected**\n\n"
            text += "**Send targets (one per line):**\n"
            text += "@target1\n@target2\n@target3"
        
        await event.respond(text)
    
    elif state.get('state') == 'report_user_target':
        target = event.text.strip()
        user_states[user_id]['state'] = 'report_category'
        user_states[user_id]['target'] = target
        
        sessions = state.get('selected_sessions', get_user_sessions(user_id))
        if state.get('session_mode') == 'all':
            sessions = get_user_sessions(user_id)
        
        user_states[user_id]['sessions'] = sessions
        
        text = f"🎯 **Target Set:** {target}\n"
        text += f"📱 **Sessions:** {len(sessions)}\n\n"
        text += "**Select Category:**\n\n"
        for key, (name, _) in REPORT_REASONS.items():
            text += f"{key}. {name}\n"
        text += "\n**Send category number (1-10):**"
        
        await event.respond(text)
    
    elif state.get('state') == 'report_message_link':
        link = event.text.strip()
        
        try:
            if '/c/' in link:
                parts = link.split('/')
                channel_id = int(parts[-2])
                message_id = int(parts[-1])
            else:
                parts = link.split('/')
                channel = parts[-2]
                message_id = int(parts[-1])
                channel_id = channel
        except:
            await event.respond("❌ Invalid message link! Send a valid Telegram message link.")
            return
        
        user_states[user_id]['state'] = 'report_category'
        user_states[user_id]['target'] = link
        user_states[user_id]['message_id'] = message_id
        user_states[user_id]['channel_id'] = channel_id
        
        sessions = state.get('selected_sessions', get_user_sessions(user_id))
        if state.get('session_mode') == 'all':
            sessions = get_user_sessions(user_id)
        
        user_states[user_id]['sessions'] = sessions
        
        text = f"💬 **Message Link Set**\n"
        text += f"📱 **Sessions:** {len(sessions)}\n\n"
        text += "**Select Category:**\n\n"
        for key, (name, _) in REPORT_REASONS.items():
            text += f"{key}. {name}\n"
        text += "\n**Send category number (1-10):**"
        
        await event.respond(text)
    
    elif state.get('state') == 'report_group_target':
        target = event.text.strip()
        user_states[user_id]['state'] = 'report_category'
        user_states[user_id]['target'] = target
        
        sessions = state.get('selected_sessions', get_user_sessions(user_id))
        if state.get('session_mode') == 'all':
            sessions = get_user_sessions(user_id)
        
        user_states[user_id]['sessions'] = sessions
        
        text = f"👥 **Group Set:** {target}\n"
        text += f"📱 **Sessions:** {len(sessions)}\n\n"
        text += "**Select Category:**\n\n"
        for key, (name, _) in REPORT_REASONS.items():
            text += f"{key}. {name}\n"
        text += "\n**Send category number (1-10):**"
        
        await event.respond(text)
    
    elif state.get('state') == 'report_bulk_targets':
        targets = [t.strip() for t in event.text.split('\n') if t.strip()]
        
        if len(targets) > 50:
            await event.respond("❌ Maximum 50 targets allowed! Please send fewer targets.")
            return
        
        if not targets:
            await event.respond("❌ No valid targets found! Send targets one per line.")
            return
        
        user_states[user_id]['state'] = 'report_category'
        user_states[user_id]['targets'] = targets
        
        sessions = state.get('selected_sessions', get_user_sessions(user_id))
        if state.get('session_mode') == 'all':
            sessions = get_user_sessions(user_id)
        
        user_states[user_id]['sessions'] = sessions
        
        text = f"📋 **Bulk Targets Set:** {len(targets)}\n"
        text += f"📱 **Sessions:** {len(sessions)}\n\n"
        text += "**Targets:**\n"
        for i, t in enumerate(targets[:10], 1):
            text += f"{i}. {t}\n"
        if len(targets) > 10:
            text += f"... and {len(targets) - 10} more\n"
        
        text += "\n**Select Category:**\n\n"
        for key, (name, _) in REPORT_REASONS.items():
            text += f"{key}. {name}\n"
        text += "\n**Send category number (1-10):**"
        
        await event.respond(text)
    
    elif state.get('state') == 'report_category':
        category = event.text.strip()
        if category not in REPORT_REASONS:
            await event.respond("❌ Invalid! Send number 1-10")
            return
        
        reason_name, reason_obj = REPORT_REASONS[category]
        sessions = state.get('sessions', [])
        
        limit = get_user_setting(user_id, 'reports_per_session', 10)
        delay = get_user_setting(user_id, 'report_delay', 1)
        randomize = get_user_setting(user_id, 'randomize_sessions', False)
        
        if randomize:
            random.shuffle(sessions)
        
        if 'targets' in state:
            targets = state['targets']
            msg = await event.respond(
                f"🎯 **Starting Bulk Reports...**\n\n"
                f"Targets: {len(targets)}\n"
                f"Reason: {reason_name}\n"
                f"Sessions: {len(sessions)}\n"
                f"Progress: 0/{len(targets) * len(sessions)}"
            )
            
            total_success = 0
            total_failed = 0
            
            for target in targets:
                for i, session in enumerate(sessions[:limit]):
                    session_path = os.path.join(SESSIONS_DIR, session['session'])
                    result, error = await do_report_user(session_path, target, reason_obj)
                    
                    if result:
                        total_success += 1
                    else:
                        total_failed += 1
                    
                    completed = (targets.index(target) * len(sessions)) + i + 1
                    total = len(targets) * min(len(sessions), limit)
                    
                    if completed % 5 == 0 or completed == total:
                        await msg.edit(
                            f"🎯 **Bulk Reporting...**\n\n"
                            f"Targets: {len(targets)}\n"
                            f"Reason: {reason_name}\n"
                            f"Progress: {completed}/{total}\n"
                            f"✅ Success: {total_success}\n"
                            f"❌ Failed: {total_failed}"
                        )
                    
                    await asyncio.sleep(delay)
            
            update_report_stats(user_id, total_success, total_failed)
            user_states.pop(user_id, None)
            
            await msg.edit(
                f"✅ **Bulk Report Complete!**\n\n"
                f"Targets: {len(targets)}\n"
                f"Reason: {reason_name}\n"
                f"Sessions Used: {min(len(sessions), limit)}\n"
                f"✅ Success: {total_success}\n"
                f"❌ Failed: {total_failed}\n"
                f"📊 Rate: {int(total_success/(total_success+total_failed)*100) if total_success+total_failed > 0 else 0}%",
                buttons=[[Button.inline("🎯 Report Again", b"report_menu"), Button.inline("🏠 Menu", b"start")]]
            )
        
        elif 'message_id' in state:
            link = state['target']
            message_id = state['message_id']
            channel_id = state['channel_id']
            
            msg = await event.respond(
                f"💬 **Starting Message Reports...**\n\n"
                f"Link: {link}\n"
                f"Reason: {reason_name}\n"
                f"Sessions: 0/{len(sessions)}"
            )
            
            success = 0
            failed = 0
            
            for i, session in enumerate(sessions[:limit]):
                session_path = os.path.join(SESSIONS_DIR, session['session'])
                
                try:
                    if isinstance(channel_id, int):
                        result, error = await do_report_message(session_path, channel_id, [message_id], reason_obj)
                    else:
                        result, error = await do_report_message(session_path, channel_id, [message_id], reason_obj)
                except:
                    result, error = False, "Error"
                
                if result:
                    success += 1
                else:
                    failed += 1
                
                if (i + 1) % 3 == 0 or i == min(len(sessions), limit) - 1:
                    await msg.edit(
                        f"💬 **Reporting Message...**\n\n"
                        f"Link: {link}\n"
                        f"Reason: {reason_name}\n"
                        f"Progress: {i+1}/{min(len(sessions), limit)}\n"
                        f"✅ Success: {success}\n"
                        f"❌ Failed: {failed}"
                    )
                
                await asyncio.sleep(delay)
            
            update_report_stats(user_id, success, failed)
            user_states.pop(user_id, None)
            
            await msg.edit(
                f"✅ **Message Report Complete!**\n\n"
                f"Link: {link}\n"
                f"Reason: {reason_name}\n"
                f"Sessions Used: {min(len(sessions), limit)}\n"
                f"✅ Success: {success}\n"
                f"❌ Failed: {failed}\n"
                f"📊 Rate: {int(success/(success+failed)*100) if success+failed > 0 else 0}%",
                buttons=[[Button.inline("🎯 Report Again", b"report_menu"), Button.inline("🏠 Menu", b"start")]]
            )
        
        else:
            target = state['target']
            msg = await event.respond(
                f"🎯 **Starting Reports...**\n\n"
                f"Target: {target}\n"
                f"Reason: {reason_name}\n"
                f"Sessions: 0/{len(sessions)}"
            )
            
            success = 0
            failed = 0
            
            for i, session in enumerate(sessions[:limit]):
                session_path = os.path.join(SESSIONS_DIR, session['session'])
                result, error = await do_report_user(session_path, target, reason_obj)
                
                if result:
                    success += 1
                else:
                    failed += 1
                
                if (i + 1) % 3 == 0 or i == min(len(sessions), limit) - 1:
                    await msg.edit(
                        f"🎯 **Reporting...**\n\n"
                        f"Target: {target}\n"
                        f"Reason: {reason_name}\n"
                        f"Progress: {i+1}/{min(len(sessions), limit)}\n"
                        f"✅ Success: {success}\n"
                        f"❌ Failed: {failed}"
                    )
                
                await asyncio.sleep(delay)
            
            update_report_stats(user_id, success, failed)
            user_states.pop(user_id, None)
            
            await msg.edit(
                f"✅ **Report Complete!**\n\n"
                f"Target: {target}\n"
                f"Reason: {reason_name}\n"
                f"Sessions Used: {min(len(sessions), limit)}\n"
                f"✅ Success: {success}\n"
                f"❌ Failed: {failed}\n"
                f"📊 Rate: {int(success/(success+failed)*100) if success+failed > 0 else 0}%",
                buttons=[[Button.inline("🎯 Report Again", b"report_menu"), Button.inline("🏠 Menu", b"start")]]
            )
    
    elif state.get('state') == 'setting_limit':
        try:
            limit = int(event.text.strip())
            if 1 <= limit <= 100:
                set_user_setting(user_id, 'reports_per_session', limit)
                await event.respond(f"✅ Reports per session set to: {limit}")
                user_states.pop(user_id, None)
            else:
                await event.respond("❌ Send a number between 1-100")
        except:
            await event.respond("❌ Invalid number! Send 1-100")
    
    elif state.get('state') == 'setting_delay':
        try:
            delay = int(event.text.strip())
            if 0 <= delay <= 10:
                set_user_setting(user_id, 'report_delay', delay)
                await event.respond(f"✅ Delay set to: {delay} seconds")
                user_states.pop(user_id, None)
            else:
                await event.respond("❌ Send a number between 0-10")
        except:
            await event.respond("❌ Invalid number! Send 0-10")
    
    elif state.get('state') == 'removing_session':
        phone = event.text.strip()
        sessions = get_user_sessions(user_id)
        
        found = False
        for s in sessions:
            if s['phone'] == phone:
                remove_user_session(user_id, phone)
                session_path = os.path.join(SESSIONS_DIR, s['session'])
                try:
                    if os.path.exists(session_path + '.session'):
                        os.remove(session_path + '.session')
                except:
                    pass
                found = True
                break
        
        if found:
            await event.respond(f"✅ Session removed: {phone}")
        else:
            await event.respond("❌ Session not found! Check phone number")
        
        user_states.pop(user_id, None)

@bot.on(events.NewMessage(pattern='/verify (.+)'))
async def verify_cmd(event):
    user_id = event.sender_id
    args = event.pattern_match.group(1).split()
    
    state = user_states.get(user_id, {})
    if state.get('state') != 'waiting_code':
        await event.respond("❌ No pending verification!\nUse /add_session first")
        return
    
    code = args[0]
    password = args[1] if len(args) > 1 else None
    
    try:
        client = state['client']
        phone = state['phone']
        
        try:
            await client.sign_in(phone, code)
        except SessionPasswordNeededError:
            if password:
                await client.sign_in(password=password)
            else:
                await event.respond("❌ 2FA enabled! Send:\n/verify CODE PASSWORD")
                return
        
        me = await client.get_me()
        await client.disconnect()
        
        add_user_session(user_id, {
            'phone': phone,
            'name': me.first_name,
            'session': state['session_name'],
            'verified': True,
            'added': time.strftime("%Y-%m-%d %H:%M:%S")
        })
        
        user_states.pop(user_id, None)
        
        await event.respond(
            f"✅ **Session Verified!**\n\n"
            f"📱 Phone: {phone}\n"
            f"👤 Name: {me.first_name}\n"
            f"🆔 ID: {me.id}\n\n"
            f"**Ready to report!**\n"
            f"Use: /report",
            buttons=[[Button.inline("🎯 Start Reporting", b"report_menu")]]
        )
        
    except PhoneCodeInvalidError:
        await event.respond("❌ Invalid code! Try again:\n/verify CODE")
    except Exception as e:
        await event.respond(f"❌ Error: {str(e)}")
        user_states.pop(user_id, None)

@bot.on(events.NewMessage(pattern='/cancel_verification'))
async def cancel_verification(event):
    user_id = event.sender_id
    state = user_states.get(user_id, {})
    
    if 'client' in state:
        try:
            await state['client'].disconnect()
        except:
            pass
    
    user_states.pop(user_id, None)
    await event.respond("✅ Verification cancelled!")

@bot.on(events.NewMessage(pattern='/my_sessions'))
async def my_sessions_cmd(event):
    user_id = event.sender_id
    sessions = get_user_sessions(user_id)
    
    if not sessions:
        text = "❌ **No sessions found!**\n\nAdd session: /add_session"
    else:
        text = f"📱 **YOUR SESSIONS ({len(sessions)})**\n\n"
        for i, s in enumerate(sessions, 1):
            status = "✅" if s.get('verified') else "⏳"
            text += f"**{i}. {status} {s['phone']}**\n"
            text += f"   Name: {s.get('name', 'Unknown')}\n"
            text += f"   Added: {s.get('added', 'Unknown')}\n"
            if s.get('last_used'):
                text += f"   Last Used: {s['last_used']}\n"
            text += "\n"
    
    buttons = [[Button.inline("➕ Add Session", b"add_session"), Button.inline("🏠 Menu", b"start")]]
    await event.respond(text, buttons=buttons)

@bot.on(events.NewMessage(pattern='/stats'))
async def stats_cmd(event):
    user_id = event.sender_id
    uid = str(user_id)
    stats = report_stats.get(uid, {'success': 0, 'failed': 0, 'total': 0})
    sessions = get_user_sessions(user_id)
    
    text = "📊 **YOUR STATISTICS**\n\n"
    text += f"**Sessions:**\n"
    text += f"• Total: {len(sessions)}\n"
    text += f"• Active: {sum(1 for s in sessions if s.get('verified'))}\n\n"
    text += f"**Reports:**\n"
    text += f"• Total: {stats['total']}\n"
    text += f"• Success: {stats['success']} ✅\n"
    text += f"• Failed: {stats['failed']} ❌\n"
    text += f"• Rate: {calculate_success_rate(user_id)}%"
    
    await event.respond(text)

@bot.on(events.NewMessage(func=lambda e: e.document and e.is_private))
async def file_handler(event):
    user_id = event.sender_id
    file = event.document
    
    if not file.attributes:
        return
    
    filename = file.attributes[0].file_name
    
    if filename.endswith('.session'):
        msg = await event.respond("📥 **Processing session file...**")
        path = os.path.join(TEMP_DIR, filename)
        await event.download_media(file=path)
        
        status, phone, name = await test_session_file(path.replace('.session', ''))
        
        if status:
            session_name = f"{user_id}_{phone.replace('+', '')}"
            new_path = os.path.join(SESSIONS_DIR, session_name + '.session')
            shutil.move(path, new_path)
            
            add_user_session(user_id, {
                'phone': phone,
                'name': name,
                'session': session_name,
                'verified': True,
                'added': time.strftime("%Y-%m-%d %H:%M:%S")
            })
            
            await msg.edit(f"✅ **Session Added Successfully!**\n\n📱 {phone}\n👤 {name}\n\n**Ready to report!**")
        else:
            try:
                os.remove(path)
            except:
                pass
            await msg.edit("❌ **Invalid or Expired Session!**\n\nPlease upload a valid .session file.")
    
    elif filename.endswith('.zip'):
        msg = await event.respond("📦 **Extracting ZIP file...**")
        zip_path = os.path.join(TEMP_DIR, filename)
        await event.download_media(file=zip_path)
        
        added = 0
        failed = 0
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                files = [f for f in zip_ref.namelist() if f.endswith('.session')]
                
                await msg.edit(f"📦 **Processing {len(files)} session files...**")
                
                for file in files:
                    try:
                        zip_ref.extract(file, TEMP_DIR)
                        temp_path = os.path.join(TEMP_DIR, file)
                        
                        status, phone, name = await test_session_file(temp_path.replace('.session', ''))
                        
                        if status:
                            session_name = f"{user_id}_{phone.replace('+', '')}"
                            new_path = os.path.join(SESSIONS_DIR, session_name + '.session')
                            shutil.move(temp_path, new_path)
                            
                            add_user_session(user_id, {
                                'phone': phone,
                                'name': name,
                                'session': session_name,
                                'verified': True,
                                'added': time.strftime("%Y-%m-%d %H:%M:%S")
                            })
                            added += 1
                            
                            if added % 10 == 0:
                                await msg.edit(f"📦 **Processing...**\n\n✅ Added: {added}\n❌ Failed: {failed}")
                        else:
                            try:
                                os.remove(temp_path)
                            except:
                                pass
                            failed += 1
                    except Exception as e:
                        logger.error(f"Error processing {file}: {e}")
                        failed += 1
                        continue
        except Exception as e:
            await msg.edit(f"❌ **Error extracting ZIP:**\n{str(e)}")
            return
        finally:
            try:
                os.remove(zip_path)
            except:
                pass
        
        await msg.edit(
            f"✅ **ZIP Processing Complete!**\n\n"
            f"📦 Total Files: {added + failed}\n"
            f"✅ Added: {added}\n"
            f"❌ Failed: {failed}\n\n"
            f"**All valid sessions are ready to use!**"
        )

print("╔════════════════════════════════════╗")
print("║  🚀 ADVANCED REPORT BOT v7.0     ║")
print("╚════════════════════════════════════╝")
print(f"📊 Users: {len(user_sessions)}")
print(f"📈 Total Reports: {sum(stats.get('total', 0) for stats in report_stats.values())}")
print(f"✅ Bot is running...")
print(f"⚡ All features activated!")

bot.run_until_disconnected()
