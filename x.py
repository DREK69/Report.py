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

bot = TelegramClient('report_bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

@bot.on(events.NewMessage(pattern='/start'))
async def start_cmd(event):
    user_id = event.sender_id
    sessions = get_user_sessions(user_id)
    
    text = "⚡ **ADVANCED MULTI-REPORT BOT v8.0**\n\n"
    text += "🔥 **FULLY ADVANCED - ALL FEATURES**\n\n"
    text += "**✅ Report Methods:**\n"
    text += "• User/Channel Reports\n"
    text += "• Message/Post Reports\n"
    text += "• Group Reports\n"
    text += "• Bulk Multi-Target Reports\n\n"
    text += "**📱 Session Features:**\n"
    text += "• Phone Number Login\n"
    text += "• Upload .session Files\n"
    text += "• Bulk ZIP Upload\n"
    text += "• Select Specific Sessions\n"
    text += "• Use All or Choose Few\n\n"
    text += f"**📊 Your Stats:**\n"
    text += f"• Sessions: {len(sessions)}\n"
    text += f"• Total Reports: {report_stats.get(str(user_id), {}).get('total', 0)}\n"
    text += f"• Success Rate: {calculate_success_rate(user_id)}%"
    
    buttons = [
        [Button.inline("📱 Sessions", b"session_menu"), Button.inline("🎯 Report", b"report_menu")],
        [Button.inline("⚙️ Settings", b"settings_menu"), Button.inline("📊 Stats", b"stats_menu")],
        [Button.inline("❓ Help", b"help_menu")]
    ]
    await event.respond(text, buttons=buttons)

@bot.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    
    if data == "session_menu":
        sessions = get_user_sessions(user_id)
        text = f"📱 **SESSION MANAGEMENT**\n\n"
        text += f"**Active Sessions:** {len(sessions)}\n"
        text += f"**Verified:** {sum(1 for s in sessions if s.get('verified'))}\n\n"
        text += "**Choose Action:**"
        
        buttons = [
            [Button.inline("➕ Add Session", b"add_session"), Button.inline("📋 View All", b"view_sessions")],
            [Button.inline("📤 Upload File", b"upload_help"), Button.inline("📦 Bulk ZIP", b"bulk_help")],
            [Button.inline("🗑️ Remove", b"remove_session"), Button.inline("🏠 Menu", b"start")]
        ]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_menu":
        sessions = get_user_sessions(user_id)
        if not sessions:
            await event.answer("❌ Add sessions first!", alert=True)
            return
        
        text = "🎯 **REPORTING CENTER**\n\n"
        text += "**Select Report Type:**\n\n"
        text += f"**Available Sessions:** {len(sessions)}\n\n"
        text += "Choose what to report:"
        
        buttons = [
            [Button.inline("👤 User/Channel", b"report_user"), Button.inline("💬 Message", b"report_message")],
            [Button.inline("👥 Group", b"report_group"), Button.inline("📋 Bulk", b"report_bulk")],
            [Button.inline("🏠 Main Menu", b"start")]
        ]
        await event.edit(text, buttons=buttons)
    
    elif data == "settings_menu":
        limit = get_user_setting(user_id, 'reports_per_session', 10)
        delay = get_user_setting(user_id, 'report_delay', 1)
        retry = get_user_setting(user_id, 'auto_retry', True)
        randomize = get_user_setting(user_id, 'randomize_sessions', False)
        
        text = "⚙️ **SETTINGS**\n\n"
        text += f"**Current Config:**\n"
        text += f"• Reports/Session: {limit}\n"
        text += f"• Delay: {delay}s\n"
        text += f"• Auto-Retry: {'✅' if retry else '❌'}\n"
        text += f"• Randomize: {'✅' if randomize else '❌'}"
        
        buttons = [
            [Button.inline(f"📊 Limit: {limit}", b"set_limit"), Button.inline(f"⏱️ Delay: {delay}s", b"set_delay")],
            [Button.inline(f"{'✅' if retry else '❌'} Retry", b"toggle_retry"), Button.inline(f"{'✅' if randomize else '❌'} Random", b"toggle_random")],
            [Button.inline("🔄 Reset", b"reset_settings"), Button.inline("🏠 Menu", b"start")]
        ]
        await event.edit(text, buttons=buttons)
    
    elif data == "stats_menu":
        uid = str(user_id)
        stats = report_stats.get(uid, {'success': 0, 'failed': 0, 'total': 0})
        sessions = get_user_sessions(user_id)
        
        text = "📊 **STATISTICS**\n\n"
        text += f"**Sessions:**\n"
        text += f"• Total: {len(sessions)}\n"
        text += f"• Active: {sum(1 for s in sessions if s.get('verified'))}\n\n"
        text += f"**Reports:**\n"
        text += f"• Total: {stats['total']}\n"
        text += f"• Success: {stats['success']} ✅\n"
        text += f"• Failed: {stats['failed']} ❌\n"
        text += f"• Rate: {calculate_success_rate(user_id)}%"
        
        buttons = [
            [Button.inline("🗑️ Clear", b"clear_stats"), Button.inline("🏠 Menu", b"start")]
        ]
        await event.edit(text, buttons=buttons)
    
    elif data == "help_menu":
        text = "📚 **HELP GUIDE**\n\n"
        text += "**🎯 HOW TO USE:**\n\n"
        text += "**Step 1: Add Sessions**\n"
        text += "• /add_session + phone\n"
        text += "• Upload .session file\n"
        text += "• Upload .zip with sessions\n\n"
        text += "**Step 2: Report**\n"
        text += "• Choose report type\n"
        text += "• Select ALL or SPECIFIC sessions\n"
        text += "• Enter target\n"
        text += "• Choose category (1-10)\n\n"
        text += "**Categories:**\n"
        for key, (name, _) in REPORT_REASONS.items():
            text += f"{key}. {name}\n"
        
        buttons = [[Button.inline("🏠 Menu", b"start")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "add_session":
        user_states[user_id] = {'state': 'waiting_phone'}
        text = "📱 **ADD SESSION**\n\n"
        text += "**Send phone number:**\n"
        text += "Examples:\n"
        text += "• +919876543210\n"
        text += "• +12025551234\n"
        text += "• +447911123456"
        
        buttons = [[Button.inline("❌ Cancel", b"session_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "view_sessions":
        sessions = get_user_sessions(user_id)
        if not sessions:
            await event.answer("❌ No sessions!", alert=True)
            return
        
        text = f"📱 **SESSIONS ({len(sessions)})**\n\n"
        for i, s in enumerate(sessions, 1):
            status = "✅" if s.get('verified') else "⏳"
            text += f"{i}. {status} {s['phone']}\n"
            text += f"   {s.get('name', 'Unknown')}\n\n"
        
        buttons = [[Button.inline("➕ Add", b"add_session"), Button.inline("🏠 Menu", b"start")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "upload_help":
        text = "📤 **UPLOAD .SESSION FILE**\n\n"
        text += "**Instructions:**\n"
        text += "1. Send .session file\n"
        text += "2. Auto-validation\n"
        text += "3. Instant activation\n\n"
        text += "Send file now!"
        
        buttons = [[Button.inline("❌ Cancel", b"session_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "bulk_help":
        text = "📦 **BULK ZIP UPLOAD**\n\n"
        text += "**Instructions:**\n"
        text += "1. Create ZIP file\n"
        text += "2. Add .session files\n"
        text += "3. Upload ZIP\n"
        text += "4. Auto-processing\n\n"
        text += "Send ZIP now!"
        
        buttons = [[Button.inline("❌ Cancel", b"session_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "remove_session":
        sessions = get_user_sessions(user_id)
        if not sessions:
            await event.answer("❌ No sessions!", alert=True)
            return
        
        text = "🗑️ **REMOVE SESSION**\n\n"
        text += "**Send phone to remove:**\n\n"
        for s in sessions:
            text += f"• {s['phone']}\n"
        
        user_states[user_id] = {'state': 'removing_session'}
        buttons = [[Button.inline("❌ Cancel", b"session_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_user":
        sessions = get_user_sessions(user_id)
        text = "👤 **USER/CHANNEL REPORT**\n\n"
        text += f"**Sessions: {len(sessions)}**\n\n"
        text += "**Choose:**"
        
        buttons = [
            [Button.inline("🎯 All Sessions", b"report_user_all")],
            [Button.inline("📱 Select Sessions", b"report_user_select")],
            [Button.inline("❌ Cancel", b"report_menu")]
        ]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_user_all":
        user_states[user_id] = {'state': 'report_user_target', 'type': 'user', 'session_mode': 'all'}
        text = "👤 **USER REPORT (ALL)**\n\n"
        text += "**Send target:**\n"
        text += "• @username\n"
        text += "• User ID\n"
        text += "• t.me/username"
        
        buttons = [[Button.inline("❌ Cancel", b"report_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_user_select":
        sessions = get_user_sessions(user_id)
        if not sessions:
            await event.answer("❌ No sessions!", alert=True)
            return
        
        text = "📱 **SELECT SESSIONS**\n\n"
        for i, s in enumerate(sessions, 1):
            status = "✅" if s.get('verified') else "⏳"
            text += f"{i}. {status} {s['phone']}\n"
        
        text += "\n**Send numbers:**\n"
        text += "Examples:\n"
        text += "• 1\n"
        text += "• 1,2,3\n"
        text += "• 1-5\n"
        text += "• all"
        
        user_states[user_id] = {'state': 'selecting_sessions', 'type': 'user'}
        buttons = [[Button.inline("❌ Cancel", b"report_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_message":
        sessions = get_user_sessions(user_id)
        text = "💬 **MESSAGE REPORT**\n\n"
        text += f"**Sessions: {len(sessions)}**\n\n"
        text += "**Choose:**"
        
        buttons = [
            [Button.inline("🎯 All Sessions", b"report_message_all")],
            [Button.inline("📱 Select Sessions", b"report_message_select")],
            [Button.inline("❌ Cancel", b"report_menu")]
        ]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_message_all":
        user_states[user_id] = {'state': 'report_message_link', 'type': 'message', 'session_mode': 'all'}
        text = "💬 **MESSAGE REPORT (ALL)**\n\n"
        text += "**Send message link:**\n"
        text += "Examples:\n"
        text += "• t.me/channel/123\n"
        text += "• t.me/c/123/456"
        
        buttons = [[Button.inline("❌ Cancel", b"report_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_message_select":
        sessions = get_user_sessions(user_id)
        if not sessions:
            await event.answer("❌ No sessions!", alert=True)
            return
        
        text = "📱 **SELECT SESSIONS**\n\n"
        for i, s in enumerate(sessions, 1):
            status = "✅" if s.get('verified') else "⏳"
            text += f"{i}. {status} {s['phone']}\n"
        
        text += "\n**Send numbers:**\n"
        text += "• 1,2,3 or 1-5 or all"
        
        user_states[user_id] = {'state': 'selecting_sessions', 'type': 'message'}
        buttons = [[Button.inline("❌ Cancel", b"report_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_group":
        sessions = get_user_sessions(user_id)
        text = "👥 **GROUP REPORT**\n\n"
        text += f"**Sessions: {len(sessions)}**\n\n"
        text += "**Choose:**"
        
        buttons = [
            [Button.inline("🎯 All Sessions", b"report_group_all")],
            [Button.inline("📱 Select Sessions", b"report_group_select")],
            [Button.inline("❌ Cancel", b"report_menu")]
        ]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_group_all":
        user_states[user_id] = {'state': 'report_group_target', 'type': 'group', 'session_mode': 'all'}
        text = "👥 **GROUP REPORT (ALL)**\n\n"
        text += "**Send group:**\n"
        text += "• @groupname\n"
        text += "• t.me/groupname"
        
        buttons = [[Button.inline("❌ Cancel", b"report_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_group_select":
        sessions = get_user_sessions(user_id)
        if not sessions:
            await event.answer("❌ No sessions!", alert=True)
            return
        
        text = "📱 **SELECT SESSIONS**\n\n"
        for i, s in enumerate(sessions, 1):
            status = "✅" if s.get('verified') else "⏳"
            text += f"{i}. {status} {s['phone']}\n"
        
        text += "\n**Send numbers:**\n"
        text += "• 1,2,3 or 1-5 or all"
        
        user_states[user_id] = {'state': 'selecting_sessions', 'type': 'group'}
        buttons = [[Button.inline("❌ Cancel", b"report_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_bulk":
        sessions = get_user_sessions(user_id)
        text = "📋 **BULK REPORT**\n\n"
        text += f"**Sessions: {len(sessions)}**\n\n"
        text += "**Choose:**"
        
        buttons = [
            [Button.inline("🎯 All Sessions", b"report_bulk_all")],
            [Button.inline("📱 Select Sessions", b"report_bulk_select")],
            [Button.inline("❌ Cancel", b"report_menu")]
        ]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_bulk_all":
        user_states[user_id] = {'state': 'report_bulk_targets', 'type': 'bulk', 'session_mode': 'all'}
        text = "📋 **BULK REPORT (ALL)**\n\n"
        text += "**Send targets (one per line):**\n"
        text += "@user1\n@user2\n@user3\n\n"
        text += "**Max: 50 targets**"
        
        buttons = [[Button.inline("❌ Cancel", b"report_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "report_bulk_select":
        sessions = get_user_sessions(user_id)
        if not sessions:
            await event.answer("❌ No sessions!", alert=True)
            return
        
        text = "📱 **SELECT SESSIONS**\n\n"
        for i, s in enumerate(sessions, 1):
            status = "✅" if s.get('verified') else "⏳"
            text += f"{i}. {status} {s['phone']}\n"
        
        text += "\n**Send numbers:**\n"
        text += "• 1,2,3 or 1-5 or all"
        
        user_states[user_id] = {'state': 'selecting_sessions', 'type': 'bulk'}
        buttons = [[Button.inline("❌ Cancel", b"report_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "set_limit":
        user_states[user_id] = {'state': 'setting_limit'}
        text = f"📊 **SET LIMIT**\n\n"
        text += f"**Current:** {get_user_setting(user_id, 'reports_per_session', 10)}\n\n"
        text += "**Send new limit (1-100):**"
        
        buttons = [[Button.inline("❌ Cancel", b"settings_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "set_delay":
        user_states[user_id] = {'state': 'setting_delay'}
        text = f"⏱️ **SET DELAY**\n\n"
        text += f"**Current:** {get_user_setting(user_id, 'report_delay', 1)}s\n\n"
        text += "**Send new delay (0-10s):**"
        
        buttons = [[Button.inline("❌ Cancel", b"settings_menu")]]
        await event.edit(text, buttons=buttons)
    
    elif data == "toggle_retry":
        current = get_user_setting(user_id, 'auto_retry', True)
        set_user_setting(user_id, 'auto_retry', not current)
        await event.answer(f"✅ Auto-Retry: {'ON' if not current else 'OFF'}")
    
    elif data == "toggle_random":
        current = get_user_setting(user_id, 'randomize_sessions', False)
        set_user_setting(user_id, 'randomize_sessions', not current)
        await event.answer(f"✅ Randomize: {'ON' if not current else 'OFF'}")
    
    elif data == "reset_settings":
        set_user_setting(user_id, 'reports_per_session', 10)
        set_user_setting(user_id, 'report_delay', 1)
        set_user_setting(user_id, 'auto_retry', True)
        set_user_setting(user_id, 'randomize_sessions', False)
        await event.answer("✅ Settings reset!")
    
    elif data == "clear_stats":
        uid = str(user_id)
        if uid in report_stats:
            report_stats[uid] = {'success': 0, 'failed': 0, 'total': 0}
            save_data(os.path.join(DATA_DIR, 'report_stats.json'), report_stats)
        await event.answer("✅ Stats cleared!")
    
    elif data == "start":
        await start_cmd(event)

@bot.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith('/')))
async def message_handler(event):
    user_id = event.sender_id
    state = user_states.get(user_id, {})
    
    if state.get('state') == 'waiting_phone':
        phone = event.text.strip()
        if not phone.startswith('+'):
            await event.respond("❌ Add + and country code!\nExample: +919876543210")
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
                f"Send: /verify CODE\n"
                f"For 2FA: /verify CODE PASSWORD\n"
                f"Cancel: /cancel"
            )
        except PhoneNumberInvalidError:
            await msg.edit("❌ Invalid phone!")
            user_states.pop(user_id, None)
        except Exception as e:
            await msg.edit(f"❌ Error: {str(e)}")
            user_states.pop(user_id, None)
    
    elif state.get('state') == 'selecting_sessions':
        sessions = get_user_sessions(user_id)
        selected_indices = parse_session_selection(event.text, len(sessions))
        
        if not selected_indices:
            await event.respond("❌ Invalid! Try again or send 'all'")
            return
        
        selected_sessions = [sessions[i] for i in selected_indices]
        user_states[user_id]['selected_sessions'] = selected_sessions
        
        report_type = state.get('type', 'user')
        if report_type == 'user':
            user_states[user_id]['state'] = 'report_user_target'
            text = f"✅ **{len(selected_sessions)} sessions selected**\n\n**Send target:**"
        elif report_type == 'message':
            user_states[user_id]['state'] = 'report_message_link'
            text = f"✅ **{len(selected_sessions)} sessions selected**\n\n**Send message link:**"
        elif report_type == 'group':
            user_states[user_id]['state'] = 'report_group_target'
            text = f"✅ **{len(selected_sessions)} sessions selected**\n\n**Send group:**"
        elif report_type == 'bulk':
            user_states[user_id]['state'] = 'report_bulk_targets'
            text = f"✅ **{len(selected_sessions)} sessions selected**\n\n**Send targets (one per line):**"
        
        await event.respond(text)
    
    elif state.get('state') == 'report_user_target':
        target = event.text.strip()
        user_states[user_id]['state'] = 'report_category'
        user_states[user_id]['target'] = target
        
        sessions = state.get('selected_sessions', get_user_sessions(user_id))
        if state.get('session_mode') == 'all':
            sessions = get_user_sessions(user_id)
        
        user_states[user_id]['sessions'] = sessions
        
        text = f"🎯 **Target:** {target}\n"
        text += f"📱 **Sessions:** {len(sessions)}\n\n"
        text += "**Category (1-10):**\n"
        for key, (name, _) in REPORT_REASONS.items():
            text += f"{key}. {name}\n"
        
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
            await event.respond("❌ Invalid link!")
            return
        
        user_states[user_id]['state'] = 'report_category'
        user_states[user_id]['target'] = link
        user_states[user_id]['message_id'] = message_id
        user_states[user_id]['channel_id'] = channel_id
        
        sessions = state.get('selected_sessions', get_user_sessions(user_id))
        if state.get('session_mode') == 'all':
            sessions = get_user_sessions(user_id)
        
        user_states[user_id]['sessions'] = sessions
        
        text = f"💬 **Message:** {link}\n"
        text += f"📱 **Sessions:** {len(sessions)}\n\n"
        text += "**Category (1-10):**\n"
        for key, (name, _) in REPORT_REASONS.items():
            text += f"{key}. {name}\n"
        
        await event.respond(text)
    
    elif state.get('state') == 'report_group_target':
        target = event.text.strip()
        user_states[user_id]['state'] = 'report_category'
        user_states[user_id]['target'] = target
        
        sessions = state.get('selected_sessions', get_user_sessions(user_id))
        if state.get('session_mode') == 'all':
            sessions = get_user_sessions(user_id)
        
        user_states[user_id]['sessions'] = sessions
        
        text = f"👥 **Group:** {target}\n"
        text += f"📱 **Sessions:** {len(sessions)}\n\n"
        text += "**Category (1-10):**\n"
        for key, (name, _) in REPORT_REASONS.items():
            text += f"{key}. {name}\n"
        
        await event.respond(text)
    
    elif state.get('state') == 'report_bulk_targets':
        targets = [t.strip() for t in event.text.split('\n') if t.strip()]
        
        if len(targets) > 50:
            await event.respond("❌ Max 50 targets!")
            return
        
        if not targets:
            await event.respond("❌ No valid targets!")
            return
        
        user_states[user_id]['state'] = 'report_category'
        user_states[user_id]['targets'] = targets
        
        sessions = state.get('selected_sessions', get_user_sessions(user_id))
        if state.get('session_mode') == 'all':
            sessions = get_user_sessions(user_id)
        
        user_states[user_id]['sessions'] = sessions
        
        text = f"📋 **Targets:** {len(targets)}\n"
        text += f"📱 **Sessions:** {len(sessions)}\n\n"
        for i, t in enumerate(targets[:10], 1):
            text += f"{i}. {t}\n"
        if len(targets) > 10:
            text += f"... +{len(targets)-10} more\n"
        
        text += "\n**Category (1-10):**\n"
        for key, (name, _) in REPORT_REASONS.items():
            text += f"{key}. {name}\n"
        
        await event.respond(text)
    
    elif state.get('state') == 'report_category':
        category = event.text.strip()
        if category not in REPORT_REASONS:
            await event.respond("❌ Invalid! Send 1-10")
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
                f"🎯 **Bulk Reporting...**\n\n"
                f"Targets: {len(targets)}\n"
                f"Reason: {reason_name}\n"
                f"Progress: 0/{len(targets)*len(sessions)}"
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
                            f"🎯 **Reporting...**\n\n"
                            f"Progress: {completed}/{total}\n"
                            f"✅ Success: {total_success}\n"
                            f"❌ Failed: {total_failed}"
                        )
                    
                    await asyncio.sleep(delay)
            
            update_report_stats(user_id, total_success, total_failed)
            user_states.pop(user_id, None)
            
            await msg.edit(
                f"✅ **COMPLETE!**\n\n"
                f"Targets: {len(targets)}\n"
                f"Reason: {reason_name}\n"
                f"Sessions: {min(len(sessions), limit)}\n"
                f"✅ Success: {total_success}\n"
                f"❌ Failed: {total_failed}\n"
                f"📊 Rate: {int(total_success/(total_success+total_failed)*100) if total_success+total_failed > 0 else 0}%",
                buttons=[[Button.inline("🎯 Report", b"report_menu"), Button.inline("🏠 Menu", b"start")]]
            )
        
        elif 'message_id' in state:
            link = state['target']
            message_id = state['message_id']
            channel_id = state['channel_id']
            
            msg = await event.respond(
                f"💬 **Reporting...**\n\n"
                f"Reason: {reason_name}\n"
                f"Progress: 0/{len(sessions)}"
            )
            
            success = 0
            failed = 0
            
            for i, session in enumerate(sessions[:limit]):
                session_path = os.path.join(SESSIONS_DIR, session['session'])
                
                try:
                    result, error = await do_report_message(session_path, channel_id, [message_id], reason_obj)
                except:
                    result, error = False, "Error"
                
                if result:
                    success += 1
                else:
                    failed += 1
                
                if (i + 1) % 3 == 0 or i == min(len(sessions), limit) - 1:
                    await msg.edit(
                        f"💬 **Reporting...**\n\n"
                        f"Progress: {i+1}/{min(len(sessions), limit)}\n"
                        f"✅ Success: {success}\n"
                        f"❌ Failed: {failed}"
                    )
                
                await asyncio.sleep(delay)
            
            update_report_stats(user_id, success, failed)
            user_states.pop(user_id, None)
            
            await msg.edit(
                f"✅ **COMPLETE!**\n\n"
                f"Reason: {reason_name}\n"
                f"Sessions: {min(len(sessions), limit)}\n"
                f"✅ Success: {success}\n"
                f"❌ Failed: {failed}\n"
                f"📊 Rate: {int(success/(success+failed)*100) if success+failed > 0 else 0}%",
                buttons=[[Button.inline("🎯 Report", b"report_menu"), Button.inline("🏠 Menu", b"start")]]
            )
        
        else:
            target = state['target']
            msg = await event.respond(
                f"🎯 **Reporting...**\n\n"
                f"Target: {target}\n"
                f"Reason: {reason_name}\n"
                f"Progress: 0/{len(sessions)}"
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
                        f"Progress: {i+1}/{min(len(sessions), limit)}\n"
                        f"✅ Success: {success}\n"
                        f"❌ Failed: {failed}"
                    )
                
                await asyncio.sleep(delay)
            
            update_report_stats(user_id, success, failed)
            user_states.pop(user_id, None)
            
            await msg.edit(
                f"✅ **COMPLETE!**\n\n"
                f"Target: {target}\n"
                f"Reason: {reason_name}\n"
                f"Sessions: {min(len(sessions), limit)}\n"
                f"✅ Success: {success}\n"
                f"❌ Failed: {failed}\n"
                f"📊 Rate: {int(success/(success+failed)*100) if success+failed > 0 else 0}%",
                buttons=[[Button.inline("🎯 Report", b"report_menu"), Button.inline("🏠 Menu", b"start")]]
            )
    
    elif state.get('state') == 'setting_limit':
        try:
            limit = int(event.text.strip())
            if 1 <= limit <= 100:
                set_user_setting(user_id, 'reports_per_session', limit)
                await event.respond(f"✅ Limit set: {limit}")
                user_states.pop(user_id, None)
            else:
                await event.respond("❌ Send 1-100")
        except:
            await event.respond("❌ Invalid!")
    
    elif state.get('state') == 'setting_delay':
        try:
            delay = int(event.text.strip())
            if 0 <= delay <= 10:
                set_user_setting(user_id, 'report_delay', delay)
                await event.respond(f"✅ Delay set: {delay}s")
                user_states.pop(user_id, None)
            else:
                await event.respond("❌ Send 0-10")
        except:
            await event.respond("❌ Invalid!")
    
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
            await event.respond(f"✅ Removed: {phone}")
        else:
            await event.respond("❌ Not found!")
        
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
                await event.respond("❌ 2FA! Send:\n/verify CODE PASSWORD")
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
            f"✅ **VERIFIED!**\n\n"
            f"📱 {phone}\n"
            f"👤 {me.first_name}\n"
            f"🆔 {me.id}\n\n"
            f"**Ready to report!**",
            buttons=[[Button.inline("🎯 Report", b"report_menu")]]
        )
        
    except PhoneCodeInvalidError:
        await event.respond("❌ Invalid code!")
    except Exception as e:
        await event.respond(f"❌ Error: {str(e)}")
        user_states.pop(user_id, None)

@bot.on(events.NewMessage(pattern='/cancel'))
async def cancel_cmd(event):
    user_id = event.sender_id
    state = user_states.get(user_id, {})
    
    if 'client' in state:
        try:
            await state['client'].disconnect()
        except:
            pass
    
    user_states.pop(user_id, None)
    await event.respond("✅ Cancelled!")

@bot.on(events.NewMessage(func=lambda e: e.document and e.is_private))
async def file_handler(event):
    user_id = event.sender_id
    file = event.document
    
    if not file.attributes:
        return
    
    filename = file.attributes[0].file_name
    
    if filename.endswith('.session'):
        msg = await event.respond("📥 Processing...")
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
            
            await msg.edit(f"✅ **ADDED!**\n\n📱 {phone}\n👤 {name}")
        else:
            try:
                os.remove(path)
            except:
                pass
            await msg.edit("❌ Invalid session!")
    
    elif filename.endswith('.zip'):
        msg = await event.respond("📦 Extracting...")
        zip_path = os.path.join(TEMP_DIR, filename)
        await event.download_media(file=zip_path)
        
        added = 0
        failed = 0
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                files = [f for f in zip_ref.namelist() if f.endswith('.session')]
                
                await msg.edit(f"📦 Processing {len(files)} files...")
                
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
                                await msg.edit(f"📦 Processing...\n\n✅ Added: {added}\n❌ Failed: {failed}")
                        else:
                            try:
                                os.remove(temp_path)
                            except:
                                pass
                            failed += 1
                    except Exception as e:
                        logger.error(f"Error: {e}")
                        failed += 1
                        continue
        except Exception as e:
            await msg.edit(f"❌ Error: {str(e)}")
            return
        finally:
            try:
                os.remove(zip_path)
            except:
                pass
        
        await msg.edit(
            f"✅ **COMPLETE!**\n\n"
            f"📦 Total: {added + failed}\n"
            f"✅ Added: {added}\n"
            f"❌ Failed: {failed}"
        )

print("╔════════════════════════════════════╗")
print("║  🚀 ADVANCED REPORT BOT v8.0     ║")
print("╚════════════════════════════════════╝")
print(f"📊 Users: {len(user_sessions)}")
print(f"📈 Reports: {sum(stats.get('total', 0) for stats in report_stats.values())}")
print(f"✅ Running...")

bot.run_until_disconnected()
