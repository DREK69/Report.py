import requests, random, re, time, json, os, asyncio, zipfile, shutil
from telethon import TelegramClient, events, Button
from telethon.errors import SessionPasswordNeededError, FloodWaitError, InviteHashExpiredError, UserAlreadyParticipantError, ChannelPrivateError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.account import ReportPeerRequest
from telethon.tl.types import InputReportReasonSpam, InputReportReasonViolence, InputReportReasonPornography, InputReportReasonChildAbuse, InputReportReasonCopyright, InputReportReasonFake, InputReportReasonIllegalDrugs, InputReportReasonPersonalDetails, InputReportReasonOther

API_ID = 25723056
API_HASH = "cbda56fac135e92b755e1243aefe9697"
BOT_TOKEN = "8528337956:AAGU7PX6JooceLLL7HkH_LJ27v-QaKyrZVw"
OWNER_IDS = [8101867786]
SESSIONS_DIR = "sessions"
TEMP_DIR = "temp"
os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

def load_json(filename, default=None):
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except:
        return default or {}

def save_json(filename, data):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)

sessions_data = load_json('sessions.json', {})
owners = load_json('owners.json', {str(i): {"id": i} for i in OWNER_IDS})
approved_users = load_json('approved.json', {})
report_stats = load_json('stats.json', {})
user_states = {}

REASONS = {
    "1": ("🚫 Spam", InputReportReasonSpam()),
    "2": ("⚔️ Violence", InputReportReasonViolence()),
    "3": ("🔞 Pornography", InputReportReasonPornography()),
    "4": ("👶 Child Abuse", InputReportReasonChildAbuse()),
    "5": ("©️ Copyright", InputReportReasonCopyright()),
    "6": ("🎭 Fake Account", InputReportReasonFake()),
    "7": ("💊 Drugs", InputReportReasonIllegalDrugs()),
    "8": ("🔐 Personal Info", InputReportReasonPersonalDetails()),
    "9": ("📝 Other", InputReportReasonOther())
}

def is_owner(user_id):
    return user_id in OWNER_IDS

def is_approved(user_id):
    return str(user_id) in approved_users or is_owner(user_id)

def get_sessions():
    sessions = []
    for file in os.listdir(SESSIONS_DIR):
        if file.endswith('.session'):
            name = file.replace('.session', '')
            sessions.append(name)
    return sessions

async def extract_zip(file_path):
    extracted = []
    try:
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            for file in zip_ref.namelist():
                if file.endswith('.session'):
                    zip_ref.extract(file, TEMP_DIR)
                    name = os.path.basename(file).replace('.session', '')
                    old_path = os.path.join(TEMP_DIR, file)
                    new_path = os.path.join(SESSIONS_DIR, f"{name}.session")
                    shutil.move(old_path, new_path)
                    extracted.append(name)
    except Exception as e:
        print(f"Extract error: {e}")
    return extracted

async def test_session(session_name):
    try:
        client = TelegramClient(os.path.join(SESSIONS_DIR, session_name), API_ID, API_HASH)
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            await client.disconnect()
            return True, me.first_name, me.phone
        await client.disconnect()
        return False, None, None
    except:
        return False, None, None

async def report_target(client, target, reason, message="Violating ToS"):
    try:
        await client(ReportPeerRequest(peer=target, reason=reason, message=message))
        return True
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds)
        return False
    except Exception as e:
        print(f"Report error: {e}")
        return False

async def send_main_menu(event, user_id):
    sessions = get_sessions()
    active = sum(1 for s in sessions_data.values() if s.get('active'))
    
    text = f"╔════════════════════════╗\n"
    text += f"║  🎯 MASS REPORT BOT  ║\n"
    text += f"╚════════════════════════╝\n\n"
    text += f"📊 Sessions: {len(sessions)}\n"
    text += f"✅ Active: {active}\n"
    text += f"👤 Your ID: {user_id}\n\n"
    text += f"┏━━━━━━━━━━━━━━━━━━━┓\n"
    text += f"┃  SELECT ACTION  ┃\n"
    text += f"┗━━━━━━━━━━━━━━━━━━━┛"
    
    buttons = []
    if is_owner(user_id):
        buttons.append([Button.inline("➕ Add Sessions", b"add_session")])
        buttons.append([Button.inline("📋 Manage Sessions", b"manage_sessions"), Button.inline("⚙️ Settings", b"settings")])
    buttons.append([Button.inline("🎯 Start Report", b"start_report"), Button.inline("📊 Statistics", b"stats")])
    buttons.append([Button.inline("🔄 Refresh", b"refresh")])
    
    await event.edit(text, buttons=buttons)

async def show_add_sessions(event):
    text = f"╔════════════════════════╗\n"
    text += f"║  ➕ ADD SESSIONS  ║\n"
    text += f"╚════════════════════════╝\n\n"
    text += f"Choose method to add sessions:\n\n"
    text += f"1️⃣ Upload .session file\n"
    text += f"2️⃣ Upload ZIP with sessions\n"
    text += f"3️⃣ Login with Phone Number\n\n"
    text += f"Send your choice or files"
    
    buttons = [
        [Button.inline("📱 Login Phone", b"login_phone")],
        [Button.inline("🔙 Back", b"main_menu")]
    ]
    await event.edit(text, buttons=buttons)

async def show_sessions_list(event):
    sessions = get_sessions()
    text = f"╔════════════════════════╗\n"
    text += f"║  📋 SESSIONS LIST  ║\n"
    text += f"╚════════════════════════╝\n\n"
    text += f"Total: {len(sessions)}\n\n"
    
    if sessions:
        for i, name in enumerate(sessions[:20], 1):
            status = "✅" if sessions_data.get(name, {}).get('active') else "❌"
            text += f"{i}. {status} {name}\n"
        if len(sessions) > 20:
            text += f"\n...and {len(sessions)-20} more"
    else:
        text += "No sessions found"
    
    buttons = [
        [Button.inline("🔄 Test All", b"test_all"), Button.inline("🗑️ Clear All", b"clear_all")],
        [Button.inline("🔙 Back", b"main_menu")]
    ]
    await event.edit(text, buttons=buttons)

async def show_report_menu(event, user_id):
    user_states[user_id] = user_states.get(user_id, {})
    sessions = get_sessions()
    
    text = f"╔════════════════════════╗\n"
    text += f"║  🎯 REPORT SETUP  ║\n"
    text += f"╚════════════════════════╝\n\n"
    
    state = user_states[user_id]
    target = state.get('target', 'Not set')
    reason = state.get('reason_name', 'Not set')
    count = state.get('session_count', len(sessions))
    
    text += f"📌 Target: {target}\n"
    text += f"📝 Reason: {reason}\n"
    text += f"🔢 Sessions: {count}/{len(sessions)}\n\n"
    text += f"┏━━━━━━━━━━━━━━━━━━━┓\n"
    text += f"┃  SETUP OPTIONS  ┃\n"
    text += f"┗━━━━━━━━━━━━━━━━━━━┛"
    
    buttons = [
        [Button.inline("🎯 Set Target", b"set_target")],
        [Button.inline("📝 Choose Reason", b"choose_reason")],
        [Button.inline("🔢 Select Sessions", b"select_sessions")],
    ]
    
    if target != 'Not set' and reason != 'Not set':
        buttons.append([Button.inline("🚀 START REPORT", b"execute_report")])
    
    buttons.append([Button.inline("🔙 Back", b"main_menu")])
    await event.edit(text, buttons=buttons)

async def show_reason_menu(event):
    text = f"╔════════════════════════╗\n"
    text += f"║  📝 REPORT REASON  ║\n"
    text += f"╚════════════════════════╝\n\n"
    text += f"Select report reason:\n\n"
    
    buttons = []
    for key, (name, _) in REASONS.items():
        text += f"{key}. {name}\n"
        buttons.append([Button.inline(name, f"reason_{key}".encode())])
    
    buttons.append([Button.inline("🔙 Back", b"start_report")])
    await event.edit(text, buttons=buttons)

async def show_session_count_menu(event):
    sessions = get_sessions()
    text = f"╔════════════════════════╗\n"
    text += f"║  🔢 SELECT COUNT  ║\n"
    text += f"╚════════════════════════╝\n\n"
    text += f"Available sessions: {len(sessions)}\n\n"
    text += f"Choose how many to use:\n"
    
    buttons = []
    counts = [10, 25, 50, 100, len(sessions)]
    for c in counts:
        if c <= len(sessions):
            buttons.append([Button.inline(f"Use {c} sessions", f"count_{c}".encode())])
    
    buttons.append([Button.inline("🔙 Back", b"start_report")])
    await event.edit(text, buttons=buttons)

async def execute_mass_report(event, user_id):
    state = user_states.get(user_id, {})
    target = state.get('target')
    reason = state.get('reason')
    session_count = state.get('session_count', 999)
    
    if not target or not reason:
        await event.answer("❌ Setup incomplete!", alert=True)
        return
    
    sessions = get_sessions()[:session_count]
    if not sessions:
        await event.answer("❌ No sessions available!", alert=True)
        return
    
    progress_msg = await event.edit(
        f"╔════════════════════════╗\n"
        f"║  🚀 REPORTING...  ║\n"
        f"╚════════════════════════╝\n\n"
        f"Target: {target}\n"
        f"Sessions: 0/{len(sessions)}\n"
        f"Success: 0\nFailed: 0\n\n"
        f"⏳ Starting..."
    )
    
    success = 0
    failed = 0
    
    async def report_with_session(session_name, index):
        nonlocal success, failed
        try:
            client = TelegramClient(os.path.join(SESSIONS_DIR, session_name), API_ID, API_HASH)
            await client.connect()
            
            if not await client.is_user_authorized():
                failed += 1
                await client.disconnect()
                return
            
            try:
                entity = await client.get_entity(target)
                result = await report_target(client, entity, reason)
                if result:
                    success += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                print(f"Report failed: {e}")
            
            await client.disconnect()
            
            if (index + 1) % 5 == 0 or index == len(sessions) - 1:
                await progress_msg.edit(
                    f"╔════════════════════════╗\n"
                    f"║  🚀 REPORTING...  ║\n"
                    f"╚════════════════════════╝\n\n"
                    f"Target: {target}\n"
                    f"Progress: {index+1}/{len(sessions)}\n"
                    f"✅ Success: {success}\n"
                    f"❌ Failed: {failed}\n\n"
                    f"⏳ Processing..."
                )
        except Exception as e:
            failed += 1
            print(f"Session error: {e}")
    
    tasks = [report_with_session(s, i) for i, s in enumerate(sessions)]
    await asyncio.gather(*tasks)
    
    report_stats[str(user_id)] = report_stats.get(str(user_id), 0) + success
    save_json('stats.json', report_stats)
    
    final_text = f"╔════════════════════════╗\n"
    final_text += f"║  ✅ COMPLETED!  ║\n"
    final_text += f"╚════════════════════════╝\n\n"
    final_text += f"Target: {target}\n"
    final_text += f"Total Used: {len(sessions)}\n"
    final_text += f"✅ Success: {success}\n"
    final_text += f"❌ Failed: {failed}\n"
    final_text += f"📊 Success Rate: {int(success/len(sessions)*100)}%\n\n"
    final_text += f"Time: {time.strftime('%H:%M:%S')}"
    
    await progress_msg.edit(final_text, buttons=[
        [Button.inline("🎯 Report Again", b"start_report")],
        [Button.inline("🏠 Main Menu", b"main_menu")]
    ])

async def show_stats(event, user_id):
    sessions = get_sessions()
    total_reports = sum(report_stats.values())
    user_reports = report_stats.get(str(user_id), 0)
    
    text = f"╔════════════════════════╗\n"
    text += f"║  📊 STATISTICS  ║\n"
    text += f"╚════════════════════════╝\n\n"
    text += f"┏━━━━━━━━━━━━━━━━━━━┓\n"
    text += f"┃  YOUR STATS  ┃\n"
    text += f"┗━━━━━━━━━━━━━━━━━━━┛\n"
    text += f"📊 Your Reports: {user_reports}\n"
    text += f"🎯 Sessions: {len(sessions)}\n\n"
    text += f"┏━━━━━━━━━━━━━━━━━━━┓\n"
    text += f"┃  GLOBAL STATS  ┃\n"
    text += f"┗━━━━━━━━━━━━━━━━━━━┛\n"
    text += f"🌐 Total Reports: {total_reports}\n"
    text += f"👥 Users: {len(approved_users)}\n"
    text += f"📱 Sessions: {len(sessions)}"
    
    await event.edit(text, buttons=[[Button.inline("🔙 Back", b"main_menu")]])

bot = TelegramClient('reporter_bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user_id = event.sender_id
    if not is_approved(user_id):
        await event.respond(
            f"❌ Access Denied!\n\n"
            f"Your ID: {user_id}\n"
            f"Contact owner for access."
        )
        return
    
    await event.respond(
        f"╔════════════════════════╗\n"
        f"║  🎯 MASS REPORT BOT  ║\n"
        f"╚════════════════════════╝\n\n"
        f"Loading...",
        buttons=[[Button.inline("🔄 Continue", b"main_menu")]]
    )

@bot.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode() if isinstance(event.data, bytes) else event.data
    
    if not is_approved(user_id):
        await event.answer("❌ Access denied!", alert=True)
        return
    
    if data == "main_menu":
        await send_main_menu(event, user_id)
    
    elif data == "add_session":
        if not is_owner(user_id):
            await event.answer("❌ Owner only!", alert=True)
            return
        await show_add_sessions(event)
    
    elif data == "manage_sessions":
        await show_sessions_list(event)
    
    elif data == "start_report":
        await show_report_menu(event, user_id)
    
    elif data == "set_target":
        user_states[user_id] = user_states.get(user_id, {})
        user_states[user_id]['waiting_for'] = 'target'
        await event.edit(
            f"╔════════════════════════╗\n"
            f"║  🎯 SET TARGET  ║\n"
            f"╚════════════════════════╝\n\n"
            f"Send target:\n"
            f"• Username (@username)\n"
            f"• User ID (123456789)\n"
            f"• Channel link\n"
            f"• Group link\n\n"
            f"Example: @telegram",
            buttons=[[Button.inline("🔙 Cancel", b"start_report")]]
        )
    
    elif data == "choose_reason":
        await show_reason_menu(event)
    
    elif data.startswith("reason_"):
        reason_key = data.split("_")[1]
        reason_name, reason_obj = REASONS[reason_key]
        user_states[user_id] = user_states.get(user_id, {})
        user_states[user_id]['reason'] = reason_obj
        user_states[user_id]['reason_name'] = reason_name
        await event.answer(f"✅ Selected: {reason_name}")
        await show_report_menu(event, user_id)
    
    elif data == "select_sessions":
        await show_session_count_menu(event)
    
    elif data.startswith("count_"):
        count = int(data.split("_")[1])
        user_states[user_id] = user_states.get(user_id, {})
        user_states[user_id]['session_count'] = count
        await event.answer(f"✅ Selected: {count} sessions")
        await show_report_menu(event, user_id)
    
    elif data == "execute_report":
        await execute_mass_report(event, user_id)
    
    elif data == "stats":
        await show_stats(event, user_id)
    
    elif data == "test_all":
        sessions = get_sessions()
        msg = await event.edit(f"Testing {len(sessions)} sessions...")
        active = 0
        for s in sessions:
            status, name, phone = await test_session(s)
            if status:
                active += 1
                sessions_data[s] = {"active": True, "name": name, "phone": phone}
            else:
                sessions_data[s] = {"active": False}
        save_json('sessions.json', sessions_data)
        await msg.edit(f"✅ Test complete!\nActive: {active}/{len(sessions)}", buttons=[[Button.inline("🔙 Back", b"manage_sessions")]])
    
    elif data == "clear_all":
        if not is_owner(user_id):
            await event.answer("❌ Owner only!", alert=True)
            return
        for file in os.listdir(SESSIONS_DIR):
            if file.endswith('.session'):
                os.remove(os.path.join(SESSIONS_DIR, file))
        sessions_data.clear()
        save_json('sessions.json', sessions_data)
        await event.answer("✅ All sessions cleared!")
        await show_sessions_list(event)
    
    elif data == "refresh":
        await send_main_menu(event, user_id)

@bot.on(events.NewMessage(func=lambda e: e.is_private))
async def message_handler(event):
    user_id = event.sender_id
    if not is_approved(user_id):
        return
    
    state = user_states.get(user_id, {})
    
    if state.get('waiting_for') == 'target':
        target = event.text.strip()
        user_states[user_id]['target'] = target
        user_states[user_id]['waiting_for'] = None
        await event.respond(
            f"✅ Target set: {target}",
            buttons=[[Button.inline("🔙 Back to Setup", b"start_report")]]
        )
    
    elif event.document:
        if not is_owner(user_id):
            await event.respond("❌ Owner only!")
            return
        
        file = event.document
        filename = file.attributes[0].file_name if file.attributes else "file"
        
        if filename.endswith('.session'):
            msg = await event.respond("📥 Downloading session...")
            path = await event.download_media(file=os.path.join(SESSIONS_DIR, filename))
            session_name = filename.replace('.session', '')
            status, name, phone = await test_session(session_name)
            if status:
                sessions_data[session_name] = {"active": True, "name": name, "phone": phone}
                save_json('sessions.json', sessions_data)
                await msg.edit(f"✅ Session added!\nName: {name}\nPhone: {phone}")
            else:
                os.remove(path)
                await msg.edit("❌ Invalid session!")
        
        elif filename.endswith('.zip'):
            msg = await event.respond("📥 Extracting ZIP...")
            zip_path = os.path.join(TEMP_DIR, filename)
            await event.download_media(file=zip_path)
            extracted = await extract_zip(zip_path)
            os.remove(zip_path)
            
            if extracted:
                await msg.edit(f"✅ Extracted {len(extracted)} sessions!")
                for s in extracted:
                    status, name, phone = await test_session(s)
                    if status:
                        sessions_data[s] = {"active": True, "name": name, "phone": phone}
                save_json('sessions.json', sessions_data)
            else:
                await msg.edit("❌ No sessions found in ZIP!")

print("╔════════════════════════╗")
print("║  🎯 BOT STARTING...  ║")
print("╚════════════════════════╝")
print(f"Sessions: {len(get_sessions())}")
print(f"Users: {len(approved_users)}")
print("Bot is running...")

bot.run_until_disconnected()
