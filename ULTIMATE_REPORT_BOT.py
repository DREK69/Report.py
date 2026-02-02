import os, json, asyncio, zipfile, shutil, time, random, logging
from telethon import TelegramClient, events, Button
from telethon.errors import (SessionPasswordNeededError, FloodWaitError, PhoneCodeInvalidError, 
                            PhoneNumberInvalidError, UserPrivacyRestrictedError, ChannelPrivateError,
                            UserAlreadyParticipantError, InviteHashExpiredError)
from telethon.tl.functions.account import ReportPeerRequest
from telethon.tl.functions.messages import ReportRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import (InputReportReasonSpam, InputReportReasonViolence, InputReportReasonPornography, 
                              InputReportReasonChildAbuse, InputReportReasonCopyright, InputReportReasonFake, 
                              InputReportReasonIllegalDrugs, InputReportReasonPersonalDetails, InputReportReasonOther, 
                              InputReportReasonGeoIrrelevant)
from datetime import datetime

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

API_ID = 25723056
API_HASH = "cbda56fac135e92b755e1243aefe9697"
BOT_TOKEN = "8528337956:AAGU7PX6JooceLLL7HkH_LJ27v-QaKyrZVw"

DIRS = ['sessions_db', 'temp_files', 'data']
for d in DIRS:
    os.makedirs(d, exist_ok=True)

def load_json(file, default=None):
    try:
        with open(file, 'r') as f:
            return json.load(f)
    except:
        return default or {}

def save_json(file, data):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2)

user_sessions = load_json('data/sessions.json', {})
user_states = {}
report_stats = load_json('data/stats.json', {})
settings = load_json('data/settings.json', {})

REASONS = {
    "1": ("Spam", InputReportReasonSpam()),
    "2": ("Violence", InputReportReasonViolence()),
    "3": ("Pornography", InputReportReasonPornography()),
    "4": ("Child Abuse", InputReportReasonChildAbuse()),
    "5": ("Copyright", InputReportReasonCopyright()),
    "6": ("Fake Account", InputReportReasonFake()),
    "7": ("Illegal Drugs", InputReportReasonIllegalDrugs()),
    "8": ("Personal Details", InputReportReasonPersonalDetails()),
    "9": ("Geo Irrelevant", InputReportReasonGeoIrrelevant()),
    "10": ("Other Reason", InputReportReasonOther())
}

def get_setting(uid, key, default=None):
    uid = str(uid)
    return settings.get(uid, {}).get(key, default)

def set_setting(uid, key, val):
    uid = str(uid)
    if uid not in settings:
        settings[uid] = {}
    settings[uid][key] = val
    save_json('data/settings.json', settings)

def get_sessions(uid):
    return user_sessions.get(str(uid), [])

def add_session(uid, data):
    uid = str(uid)
    if uid not in user_sessions:
        user_sessions[uid] = []
    user_sessions[uid].append(data)
    save_json('data/sessions.json', user_sessions)

def remove_session(uid, phone):
    uid = str(uid)
    if uid in user_sessions:
        user_sessions[uid] = [s for s in user_sessions[uid] if s['phone'] != phone]
        save_json('data/sessions.json', user_sessions)

def update_stats(uid, success=0, failed=0):
    uid = str(uid)
    if uid not in report_stats:
        report_stats[uid] = {'success': 0, 'failed': 0, 'total': 0}
    report_stats[uid]['success'] += success
    report_stats[uid]['failed'] += failed
    report_stats[uid]['total'] += (success + failed)
    save_json('data/stats.json', report_stats)

def success_rate(uid):
    uid = str(uid)
    stats = report_stats.get(uid, {'total': 0, 'success': 0})
    if stats['total'] == 0:
        return 0
    return int((stats['success'] / stats['total']) * 100)

async def create_client(uid, phone):
    name = f"{uid}_{phone.replace('+', '')}"
    path = os.path.join('sessions_db', name)
    client = TelegramClient(path, API_ID, API_HASH)
    await client.connect()
    return client, name

async def test_session(path):
    try:
        client = TelegramClient(path, API_ID, API_HASH)
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            await client.disconnect()
            return True, me.phone, me.first_name
        await client.disconnect()
        return False, None, None
    except Exception as e:
        logger.error(f"Test session error: {e}")
        return False, None, None

async def report_user(path, target, reason):
    client = None
    try:
        client = TelegramClient(path, API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            return False, "Not authorized"
        entity = await client.get_entity(target)
        await client(ReportPeerRequest(peer=entity, reason=reason, message="Violation"))
        return True, "Success"
    except FloodWaitError as e:
        return False, f"Wait {e.seconds}s"
    except UserPrivacyRestrictedError:
        return False, "Privacy restricted"
    except ChannelPrivateError:
        return False, "Private"
    except Exception as e:
        return False, str(e)[:40]
    finally:
        if client:
            try:
                await client.disconnect()
            except:
                pass

async def report_message(path, target, msg_ids, reason):
    client = None
    try:
        client = TelegramClient(path, API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            return False, "Not authorized"
        entity = await client.get_entity(target)
        await client(ReportRequest(peer=entity, id=msg_ids, reason=reason, message="Violation"))
        return True, "Success"
    except FloodWaitError as e:
        return False, f"Wait {e.seconds}s"
    except Exception as e:
        return False, str(e)[:40]
    finally:
        if client:
            try:
                await client.disconnect()
            except:
                pass

def parse_selection(text, total):
    selected = set()
    if text.lower() == 'all':
        return list(range(total))
    for part in text.replace(' ', '').split(','):
        try:
            if '-' in part:
                s, e = part.split('-')
                s, e = int(s) - 1, int(e) - 1
                if 0 <= s < total and 0 <= e < total:
                    selected.update(range(s, e + 1))
            else:
                n = int(part) - 1
                if 0 <= n < total:
                    selected.add(n)
        except:
            continue
    return sorted(list(selected))

bot = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    uid = event.sender_id
    sessions = get_sessions(uid)
    stats = report_stats.get(str(uid), {'total': 0})
    
    text = "⚡ **ADVANCED TELEGRAM REPORTER v9.0**\n\n"
    text += "🔥 **FULLY FEATURED - MENU BASED**\n\n"
    text += "**📊 Your Stats:**\n"
    text += f"• Sessions: {len(sessions)}\n"
    text += f"• Reports: {stats['total']}\n"
    text += f"• Rate: {success_rate(uid)}%\n\n"
    text += "**Use menu buttons below:**"
    
    btns = [
        [Button.inline("📱 Sessions", b"menu_sessions"), Button.inline("🎯 Report", b"menu_report")],
        [Button.inline("⚙️ Settings", b"menu_settings"), Button.inline("📊 Stats", b"menu_stats")],
        [Button.inline("❓ Help", b"menu_help")]
    ]
    await event.respond(text, buttons=btns)

@bot.on(events.CallbackQuery)
async def callback(event):
    uid = event.sender_id
    data = event.data.decode()
    
    if data == "menu_sessions":
        sessions = get_sessions(uid)
        text = "📱 **SESSION MANAGER**\n\n"
        text += f"**Total:** {len(sessions)}\n"
        text += f"**Active:** {sum(1 for s in sessions if s.get('verified'))}\n\n"
        text += "**Choose action:**"
        
        btns = [
            [Button.inline("➕ Add Phone", b"add_phone"), Button.inline("📋 View All", b"view_all")],
            [Button.inline("📤 Upload .session", b"upload_info"), Button.inline("📦 Upload ZIP", b"zip_info")],
            [Button.inline("🗑️ Remove", b"remove_session"), Button.inline("🏠 Home", b"start")]
        ]
        await event.edit(text, buttons=btns)
    
    elif data == "menu_report":
        sessions = get_sessions(uid)
        if not sessions:
            await event.answer("❌ Add sessions first!", alert=True)
            return
        
        text = "🎯 **REPORT CENTER**\n\n"
        text += f"**Sessions:** {len(sessions)}\n\n"
        text += "**Select type:**"
        
        btns = [
            [Button.inline("👤 User/Channel", b"type_user"), Button.inline("💬 Message", b"type_message")],
            [Button.inline("👥 Group", b"type_group"), Button.inline("📋 Bulk", b"type_bulk")],
            [Button.inline("🏠 Home", b"start")]
        ]
        await event.edit(text, buttons=btns)
    
    elif data == "menu_settings":
        limit = get_setting(uid, 'limit', 10)
        delay = get_setting(uid, 'delay', 1)
        retry = get_setting(uid, 'retry', True)
        randomize = get_setting(uid, 'random', False)
        
        text = "⚙️ **SETTINGS**\n\n"
        text += f"• Reports/Session: {limit}\n"
        text += f"• Delay: {delay}s\n"
        text += f"• Auto-Retry: {'✅' if retry else '❌'}\n"
        text += f"• Randomize: {'✅' if randomize else '❌'}"
        
        btns = [
            [Button.inline(f"📊 Limit: {limit}", b"set_limit"), Button.inline(f"⏱ Delay: {delay}s", b"set_delay")],
            [Button.inline(f"{'✅' if retry else '❌'} Retry", b"tog_retry"), Button.inline(f"{'✅' if randomize else '❌'} Random", b"tog_random")],
            [Button.inline("🔄 Reset", b"reset_set"), Button.inline("🏠 Home", b"start")]
        ]
        await event.edit(text, buttons=btns)
    
    elif data == "menu_stats":
        stats = report_stats.get(str(uid), {'success': 0, 'failed': 0, 'total': 0})
        sessions = get_sessions(uid)
        
        text = "📊 **STATISTICS**\n\n"
        text += f"**Sessions:** {len(sessions)}\n"
        text += f"**Reports:** {stats['total']}\n"
        text += f"**Success:** {stats['success']} ✅\n"
        text += f"**Failed:** {stats['failed']} ❌\n"
        text += f"**Rate:** {success_rate(uid)}%"
        
        btns = [
            [Button.inline("🗑️ Clear", b"clear_stats"), Button.inline("🏠 Home", b"start")]
        ]
        await event.edit(text, buttons=btns)
    
    elif data == "menu_help":
        text = "📚 **HELP**\n\n"
        text += "**1. Add Sessions:**\n"
        text += "• Phone number\n"
        text += "• Upload .session\n"
        text += "• Upload .zip\n\n"
        text += "**2. Report:**\n"
        text += "• Choose type\n"
        text += "• Select sessions\n"
        text += "• Enter target\n"
        text += "• Pick category\n\n"
        text += "**Categories:**\n"
        for k, (n, _) in REASONS.items():
            text += f"{k}. {n}\n"
        
        btns = [[Button.inline("🏠 Home", b"start")]]
        await event.edit(text, buttons=btns)
    
    elif data == "add_phone":
        user_states[uid] = {'state': 'phone'}
        text = "📱 **ADD PHONE**\n\n"
        text += "Send number with +:\n"
        text += "Example: +919876543210"
        
        btns = [[Button.inline("❌ Cancel", b"menu_sessions")]]
        await event.edit(text, buttons=btns)
    
    elif data == "view_all":
        sessions = get_sessions(uid)
        if not sessions:
            await event.answer("❌ No sessions!", alert=True)
            return
        
        text = f"📱 **SESSIONS ({len(sessions)})**\n\n"
        for i, s in enumerate(sessions, 1):
            st = "✅" if s.get('verified') else "⏳"
            text += f"{i}. {st} {s['phone']}\n"
        
        btns = [[Button.inline("🏠 Home", b"start")]]
        await event.edit(text, buttons=btns)
    
    elif data == "upload_info":
        text = "📤 **UPLOAD .SESSION**\n\n"
        text += "Send .session file now\n"
        text += "Auto-validated & added"
        
        btns = [[Button.inline("❌ Cancel", b"menu_sessions")]]
        await event.edit(text, buttons=btns)
    
    elif data == "zip_info":
        text = "📦 **UPLOAD ZIP**\n\n"
        text += "Send .zip with sessions\n"
        text += "All auto-validated"
        
        btns = [[Button.inline("❌ Cancel", b"menu_sessions")]]
        await event.edit(text, buttons=btns)
    
    elif data == "remove_session":
        sessions = get_sessions(uid)
        if not sessions:
            await event.answer("❌ No sessions!", alert=True)
            return
        
        text = "🗑️ **REMOVE**\n\nSend phone:\n"
        for s in sessions:
            text += f"• {s['phone']}\n"
        
        user_states[uid] = {'state': 'remove'}
        btns = [[Button.inline("❌ Cancel", b"menu_sessions")]]
        await event.edit(text, buttons=btns)
    
    elif data == "type_user":
        text = "👤 **USER REPORT**\n\nChoose:"
        btns = [
            [Button.inline("🎯 All Sessions", b"user_all")],
            [Button.inline("📱 Select Sessions", b"user_select")],
            [Button.inline("❌ Cancel", b"menu_report")]
        ]
        await event.edit(text, buttons=btns)
    
    elif data == "user_all":
        user_states[uid] = {'state': 'target', 'type': 'user', 'mode': 'all'}
        text = "👤 **USER (ALL)**\n\n"
        text += "Send target:\n"
        text += "• @username\n"
        text += "• User ID\n"
        text += "• t.me/username"
        
        btns = [[Button.inline("❌ Cancel", b"menu_report")]]
        await event.edit(text, buttons=btns)
    
    elif data == "user_select":
        sessions = get_sessions(uid)
        text = "📱 **SELECT**\n\n"
        for i, s in enumerate(sessions, 1):
            text += f"{i}. {s['phone']}\n"
        text += "\nSend: 1,2,3 or 1-5 or all"
        
        user_states[uid] = {'state': 'select', 'type': 'user'}
        btns = [[Button.inline("❌ Cancel", b"menu_report")]]
        await event.edit(text, buttons=btns)
    
    elif data == "type_message":
        text = "💬 **MESSAGE**\n\nChoose:"
        btns = [
            [Button.inline("🎯 All Sessions", b"msg_all")],
            [Button.inline("📱 Select Sessions", b"msg_select")],
            [Button.inline("❌ Cancel", b"menu_report")]
        ]
        await event.edit(text, buttons=btns)
    
    elif data == "msg_all":
        user_states[uid] = {'state': 'msglink', 'type': 'message', 'mode': 'all'}
        text = "💬 **MESSAGE (ALL)**\n\n"
        text += "Send link:\n"
        text += "t.me/channel/123"
        
        btns = [[Button.inline("❌ Cancel", b"menu_report")]]
        await event.edit(text, buttons=btns)
    
    elif data == "msg_select":
        sessions = get_sessions(uid)
        text = "📱 **SELECT**\n\n"
        for i, s in enumerate(sessions, 1):
            text += f"{i}. {s['phone']}\n"
        text += "\nSend: 1,2,3 or all"
        
        user_states[uid] = {'state': 'select', 'type': 'message'}
        btns = [[Button.inline("❌ Cancel", b"menu_report")]]
        await event.edit(text, buttons=btns)
    
    elif data == "type_group":
        text = "👥 **GROUP**\n\nChoose:"
        btns = [
            [Button.inline("🎯 All Sessions", b"grp_all")],
            [Button.inline("📱 Select Sessions", b"grp_select")],
            [Button.inline("❌ Cancel", b"menu_report")]
        ]
        await event.edit(text, buttons=btns)
    
    elif data == "grp_all":
        user_states[uid] = {'state': 'target', 'type': 'group', 'mode': 'all'}
        text = "👥 **GROUP (ALL)**\n\n"
        text += "Send:\n"
        text += "• @groupname\n"
        text += "• t.me/groupname"
        
        btns = [[Button.inline("❌ Cancel", b"menu_report")]]
        await event.edit(text, buttons=btns)
    
    elif data == "grp_select":
        sessions = get_sessions(uid)
        text = "📱 **SELECT**\n\n"
        for i, s in enumerate(sessions, 1):
            text += f"{i}. {s['phone']}\n"
        text += "\nSend: 1,2,3 or all"
        
        user_states[uid] = {'state': 'select', 'type': 'group'}
        btns = [[Button.inline("❌ Cancel", b"menu_report")]]
        await event.edit(text, buttons=btns)
    
    elif data == "type_bulk":
        text = "📋 **BULK**\n\nChoose:"
        btns = [
            [Button.inline("🎯 All Sessions", b"bulk_all")],
            [Button.inline("📱 Select Sessions", b"bulk_select")],
            [Button.inline("❌ Cancel", b"menu_report")]
        ]
        await event.edit(text, buttons=btns)
    
    elif data == "bulk_all":
        user_states[uid] = {'state': 'bulklist', 'type': 'bulk', 'mode': 'all'}
        text = "📋 **BULK (ALL)**\n\n"
        text += "Send targets (one per line):\n"
        text += "@user1\n@user2\n\nMax: 50"
        
        btns = [[Button.inline("❌ Cancel", b"menu_report")]]
        await event.edit(text, buttons=btns)
    
    elif data == "bulk_select":
        sessions = get_sessions(uid)
        text = "📱 **SELECT**\n\n"
        for i, s in enumerate(sessions, 1):
            text += f"{i}. {s['phone']}\n"
        text += "\nSend: 1,2,3 or all"
        
        user_states[uid] = {'state': 'select', 'type': 'bulk'}
        btns = [[Button.inline("❌ Cancel", b"menu_report")]]
        await event.edit(text, buttons=btns)
    
    elif data == "set_limit":
        user_states[uid] = {'state': 'setlimit'}
        text = f"📊 **LIMIT**\n\nCurrent: {get_setting(uid, 'limit', 10)}\n\nSend new (1-100):"
        btns = [[Button.inline("❌ Cancel", b"menu_settings")]]
        await event.edit(text, buttons=btns)
    
    elif data == "set_delay":
        user_states[uid] = {'state': 'setdelay'}
        text = f"⏱ **DELAY**\n\nCurrent: {get_setting(uid, 'delay', 1)}s\n\nSend new (0-10):"
        btns = [[Button.inline("❌ Cancel", b"menu_settings")]]
        await event.edit(text, buttons=btns)
    
    elif data == "tog_retry":
        curr = get_setting(uid, 'retry', True)
        set_setting(uid, 'retry', not curr)
        await event.answer(f"✅ Retry: {'ON' if not curr else 'OFF'}")
    
    elif data == "tog_random":
        curr = get_setting(uid, 'random', False)
        set_setting(uid, 'random', not curr)
        await event.answer(f"✅ Random: {'ON' if not curr else 'OFF'}")
    
    elif data == "reset_set":
        set_setting(uid, 'limit', 10)
        set_setting(uid, 'delay', 1)
        set_setting(uid, 'retry', True)
        set_setting(uid, 'random', False)
        await event.answer("✅ Reset!")
    
    elif data == "clear_stats":
        if str(uid) in report_stats:
            report_stats[str(uid)] = {'success': 0, 'failed': 0, 'total': 0}
            save_json('data/stats.json', report_stats)
        await event.answer("✅ Cleared!")
    
    elif data == "start":
        await start(event)

@bot.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith('/')))
async def msg_handler(event):
    uid = event.sender_id
    state = user_states.get(uid, {})
    
    if state.get('state') == 'phone':
        phone = event.text.strip()
        if not phone.startswith('+'):
            await event.respond("❌ Add +\nExample: +919876543210")
            return
        
        msg = await event.respond("⏳ Connecting...")
        
        try:
            client, name = await create_client(uid, phone)
            await client.send_code_request(phone)
            
            user_states[uid] = {
                'state': 'code',
                'phone': phone,
                'client': client,
                'session': name
            }
            
            await msg.edit(
                f"📱 Code sent to {phone}\n\n"
                f"Send: /verify CODE\n"
                f"2FA: /verify CODE PASSWORD"
            )
        except PhoneNumberInvalidError:
            await msg.edit("❌ Invalid!")
            user_states.pop(uid, None)
        except Exception as e:
            await msg.edit(f"❌ {str(e)[:50]}")
            user_states.pop(uid, None)
    
    elif state.get('state') == 'select':
        sessions = get_sessions(uid)
        indices = parse_selection(event.text, len(sessions))
        
        if not indices:
            await event.respond("❌ Invalid!")
            return
        
        selected = [sessions[i] for i in indices]
        user_states[uid]['selected'] = selected
        
        rtype = state.get('type')
        if rtype == 'user':
            user_states[uid]['state'] = 'target'
            text = f"✅ {len(selected)} selected\n\nSend target:"
        elif rtype == 'message':
            user_states[uid]['state'] = 'msglink'
            text = f"✅ {len(selected)} selected\n\nSend link:"
        elif rtype == 'group':
            user_states[uid]['state'] = 'target'
            text = f"✅ {len(selected)} selected\n\nSend group:"
        elif rtype == 'bulk':
            user_states[uid]['state'] = 'bulklist'
            text = f"✅ {len(selected)} selected\n\nSend targets:"
        
        await event.respond(text)
    
    elif state.get('state') == 'target':
        target = event.text.strip()
        user_states[uid]['state'] = 'category'
        user_states[uid]['target'] = target
        
        if state.get('mode') == 'all':
            sessions = get_sessions(uid)
        else:
            sessions = state.get('selected', [])
        
        user_states[uid]['sessions'] = sessions
        
        text = f"🎯 {target}\n📱 {len(sessions)} sessions\n\n**Category (1-10):**\n"
        for k, (n, _) in REASONS.items():
            text += f"{k}. {n}\n"
        
        await event.respond(text)
    
    elif state.get('state') == 'msglink':
        link = event.text.strip()
        
        try:
            if '/c/' in link:
                parts = link.split('/')
                cid = int(parts[-2])
                mid = int(parts[-1])
            else:
                parts = link.split('/')
                ch = parts[-2]
                mid = int(parts[-1])
                cid = ch
        except:
            await event.respond("❌ Invalid link!")
            return
        
        user_states[uid]['state'] = 'category'
        user_states[uid]['target'] = link
        user_states[uid]['msgid'] = mid
        user_states[uid]['chid'] = cid
        
        if state.get('mode') == 'all':
            sessions = get_sessions(uid)
        else:
            sessions = state.get('selected', [])
        
        user_states[uid]['sessions'] = sessions
        
        text = f"💬 Link set\n📱 {len(sessions)} sessions\n\n**Category (1-10):**\n"
        for k, (n, _) in REASONS.items():
            text += f"{k}. {n}\n"
        
        await event.respond(text)
    
    elif state.get('state') == 'bulklist':
        targets = [t.strip() for t in event.text.split('\n') if t.strip()]
        
        if len(targets) > 50:
            await event.respond("❌ Max 50!")
            return
        
        if not targets:
            await event.respond("❌ Empty!")
            return
        
        user_states[uid]['state'] = 'category'
        user_states[uid]['targets'] = targets
        
        if state.get('mode') == 'all':
            sessions = get_sessions(uid)
        else:
            sessions = state.get('selected', [])
        
        user_states[uid]['sessions'] = sessions
        
        text = f"📋 {len(targets)} targets\n📱 {len(sessions)} sessions\n\n**Category:**\n"
        for k, (n, _) in REASONS.items():
            text += f"{k}. {n}\n"
        
        await event.respond(text)
    
    elif state.get('state') == 'category':
        cat = event.text.strip()
        if cat not in REASONS:
            await event.respond("❌ Invalid! 1-10")
            return
        
        name, reason = REASONS[cat]
        sessions = state.get('sessions', [])
        
        limit = get_setting(uid, 'limit', 10)
        delay = get_setting(uid, 'delay', 1)
        randomize = get_setting(uid, 'random', False)
        
        if randomize:
            random.shuffle(sessions)
        
        if 'targets' in state:
            targets = state['targets']
            msg = await event.respond(f"🎯 Starting...\n{len(targets)} targets")
            
            suc = 0
            fail = 0
            
            for tgt in targets:
                for i, sess in enumerate(sessions[:limit]):
                    path = os.path.join('sessions_db', sess['session'])
                    res, err = await report_user(path, tgt, reason)
                    
                    if res:
                        suc += 1
                    else:
                        fail += 1
                    
                    await asyncio.sleep(delay)
            
            update_stats(uid, suc, fail)
            user_states.pop(uid, None)
            
            rate = int(suc/(suc+fail)*100) if suc+fail > 0 else 0
            await msg.edit(
                f"✅ **DONE!**\n\n"
                f"Targets: {len(targets)}\n"
                f"✅ {suc}\n❌ {fail}\n"
                f"📊 {rate}%",
                buttons=[[Button.inline("🎯 Report", b"menu_report"), Button.inline("🏠 Home", b"start")]]
            )
        
        elif 'msgid' in state:
            mid = state['msgid']
            cid = state['chid']
            
            msg = await event.respond(f"💬 Starting...")
            
            suc = 0
            fail = 0
            
            for i, sess in enumerate(sessions[:limit]):
                path = os.path.join('sessions_db', sess['session'])
                res, err = await report_message(path, cid, [mid], reason)
                
                if res:
                    suc += 1
                else:
                    fail += 1
                
                await asyncio.sleep(delay)
            
            update_stats(uid, suc, fail)
            user_states.pop(uid, None)
            
            rate = int(suc/(suc+fail)*100) if suc+fail > 0 else 0
            await msg.edit(
                f"✅ **DONE!**\n\n"
                f"✅ {suc}\n❌ {fail}\n"
                f"📊 {rate}%",
                buttons=[[Button.inline("🎯 Report", b"menu_report"), Button.inline("🏠 Home", b"start")]]
            )
        
        else:
            target = state['target']
            msg = await event.respond(f"🎯 Starting...\n{target}")
            
            suc = 0
            fail = 0
            
            for i, sess in enumerate(sessions[:limit]):
                path = os.path.join('sessions_db', sess['session'])
                res, err = await report_user(path, target, reason)
                
                if res:
                    suc += 1
                else:
                    fail += 1
                
                if (i + 1) % 3 == 0:
                    await msg.edit(f"🎯 {i+1}/{len(sessions)}\n✅ {suc} ❌ {fail}")
                
                await asyncio.sleep(delay)
            
            update_stats(uid, suc, fail)
            user_states.pop(uid, None)
            
            rate = int(suc/(suc+fail)*100) if suc+fail > 0 else 0
            await msg.edit(
                f"✅ **DONE!**\n\n"
                f"Target: {target}\n"
                f"✅ {suc}\n❌ {fail}\n"
                f"📊 {rate}%",
                buttons=[[Button.inline("🎯 Report", b"menu_report"), Button.inline("🏠 Home", b"start")]]
            )
    
    elif state.get('state') == 'setlimit':
        try:
            lim = int(event.text.strip())
            if 1 <= lim <= 100:
                set_setting(uid, 'limit', lim)
                await event.respond(f"✅ Limit: {lim}")
                user_states.pop(uid, None)
            else:
                await event.respond("❌ 1-100")
        except:
            await event.respond("❌ Invalid!")
    
    elif state.get('state') == 'setdelay':
        try:
            dly = int(event.text.strip())
            if 0 <= dly <= 10:
                set_setting(uid, 'delay', dly)
                await event.respond(f"✅ Delay: {dly}s")
                user_states.pop(uid, None)
            else:
                await event.respond("❌ 0-10")
        except:
            await event.respond("❌ Invalid!")
    
    elif state.get('state') == 'remove':
        phone = event.text.strip()
        sessions = get_sessions(uid)
        
        found = False
        for s in sessions:
            if s['phone'] == phone:
                remove_session(uid, phone)
                path = os.path.join('sessions_db', s['session'])
                try:
                    if os.path.exists(path + '.session'):
                        os.remove(path + '.session')
                except:
                    pass
                found = True
                break
        
        if found:
            await event.respond(f"✅ Removed: {phone}")
        else:
            await event.respond("❌ Not found!")
        
        user_states.pop(uid, None)

@bot.on(events.NewMessage(pattern='/verify (.+)'))
async def verify(event):
    uid = event.sender_id
    args = event.pattern_match.group(1).split()
    
    state = user_states.get(uid, {})
    if state.get('state') != 'code':
        await event.respond("❌ No verification pending!\nUse /start")
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
                await event.respond("❌ 2FA!\nSend: /verify CODE PASSWORD")
                return
        
        me = await client.get_me()
        await client.disconnect()
        
        add_session(uid, {
            'phone': phone,
            'name': me.first_name,
            'session': state['session'],
            'verified': True,
            'added': time.strftime("%Y-%m-%d %H:%M")
        })
        
        user_states.pop(uid, None)
        
        await event.respond(
            f"✅ **VERIFIED!**\n\n"
            f"📱 {phone}\n"
            f"👤 {me.first_name}\n\n"
            f"Ready to report!",
            buttons=[[Button.inline("🎯 Report", b"menu_report")]]
        )
        
    except PhoneCodeInvalidError:
        await event.respond("❌ Invalid code!")
    except Exception as e:
        await event.respond(f"❌ {str(e)[:50]}")
        user_states.pop(uid, None)

@bot.on(events.NewMessage(pattern='/cancel'))
async def cancel(event):
    uid = event.sender_id
    state = user_states.get(uid, {})
    
    if 'client' in state:
        try:
            await state['client'].disconnect()
        except:
            pass
    
    user_states.pop(uid, None)
    await event.respond("✅ Cancelled!")

@bot.on(events.NewMessage(func=lambda e: e.document and e.is_private))
async def file_handler(event):
    uid = event.sender_id
    file = event.document
    
    if not file.attributes:
        return
    
    fname = file.attributes[0].file_name
    
    if fname.endswith('.session'):
        msg = await event.respond("📥 Processing...")
        path = os.path.join('temp_files', fname)
        await event.download_media(file=path)
        
        ok, phone, name = await test_session(path.replace('.session', ''))
        
        if ok:
            sname = f"{uid}_{phone.replace('+', '')}"
            new = os.path.join('sessions_db', sname + '.session')
            shutil.move(path, new)
            
            add_session(uid, {
                'phone': phone,
                'name': name,
                'session': sname,
                'verified': True,
                'added': time.strftime("%Y-%m-%d %H:%M")
            })
            
            await msg.edit(f"✅ **ADDED!**\n\n📱 {phone}\n👤 {name}")
        else:
            try:
                os.remove(path)
            except:
                pass
            await msg.edit("❌ Invalid session!")
    
    elif fname.endswith('.zip'):
        msg = await event.respond("📦 Extracting...")
        zpath = os.path.join('temp_files', fname)
        await event.download_media(file=zpath)
        
        added = 0
        failed = 0
        
        try:
            with zipfile.ZipFile(zpath, 'r') as z:
                files = [f for f in z.namelist() if f.endswith('.session')]
                
                for f in files:
                    try:
                        z.extract(f, 'temp_files')
                        tpath = os.path.join('temp_files', f)
                        
                        ok, phone, name = await test_session(tpath.replace('.session', ''))
                        
                        if ok:
                            sname = f"{uid}_{phone.replace('+', '')}"
                            new = os.path.join('sessions_db', sname + '.session')
                            shutil.move(tpath, new)
                            
                            add_session(uid, {
                                'phone': phone,
                                'name': name,
                                'session': sname,
                                'verified': True,
                                'added': time.strftime("%Y-%m-%d %H:%M")
                            })
                            added += 1
                        else:
                            try:
                                os.remove(tpath)
                            except:
                                pass
                            failed += 1
                    except:
                        failed += 1
                        continue
        except Exception as e:
            await msg.edit(f"❌ {str(e)[:50]}")
            return
        finally:
            try:
                os.remove(zpath)
            except:
                pass
        
        await msg.edit(
            f"✅ **DONE!**\n\n"
            f"✅ Added: {added}\n"
            f"❌ Failed: {failed}"
        )

print("╔════════════════════════════════╗")
print("║  ADVANCED REPORTER v9.0      ║")
print("╚════════════════════════════════╝")
print(f"📊 Users: {len(user_sessions)}")
print(f"✅ Running...")

bot.run_until_disconnected()
