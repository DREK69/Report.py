#!/usr/bin/env python3
import os,sys,json,asyncio,zipfile,shutil,time,random,logging,sqlite3,hashlib,re
from datetime import datetime,timedelta
from typing import Dict,List,Optional,Tuple,Any
from pathlib import Path
from telethon import TelegramClient,events,Button
from telethon.errors import *
from telethon.tl.functions.account import ReportPeerRequest
from telethon.tl.functions.messages import ReportRequest,CheckChatInviteRequest,ImportChatInviteRequest,GetMessagesRequest
from telethon.tl.functions.channels import JoinChannelRequest,LeaveChannelRequest
from telethon.tl.types import *

API_ID=25723056
API_HASH="cbda56fac135e92b755e1243aefe9697"
BOT_TOKEN="8528337956:AAGU7PX6JooceLLL7HkH_LJ27v-QaKyrZVw"
OWNER_IDS=[8101867786]

for d in ['sessions_db','temp_files','data','backups','logs','exports','cache','reports']:
    os.makedirs(d,exist_ok=True)

logging.basicConfig(level=logging.INFO,format='%(asctime)s [%(levelname)s] %(message)s',handlers=[logging.FileHandler(f'logs/bot_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),logging.StreamHandler()])
logger=logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.conn=sqlite3.connect('data/advanced_reporter.db',check_same_thread=False,timeout=30)
        self.conn.row_factory=sqlite3.Row
        self.init_db()
        self.optimize()
    def init_db(self):
        c=self.conn.cursor()
        c.executescript('''
            CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY,username TEXT,first_name TEXT,joined_date TEXT,last_active TEXT,is_owner INTEGER DEFAULT 0,is_approved INTEGER DEFAULT 0,is_banned INTEGER DEFAULT 0,approval_type TEXT,approved_by INTEGER,approved_date TEXT,total_reports INTEGER DEFAULT 0,successful_reports INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,phone TEXT UNIQUE,name TEXT,session_file TEXT,verified INTEGER DEFAULT 0,added_date TEXT,total_reports INTEGER DEFAULT 0,success_reports INTEGER DEFAULT 0,failed_reports INTEGER DEFAULT 0,is_active INTEGER DEFAULT 1,last_used TEXT,health_score INTEGER DEFAULT 100);
            CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,session_phone TEXT,target TEXT,target_type TEXT,message_link TEXT,message_id INTEGER,reason TEXT,reason_name TEXT,success INTEGER,timestamp TEXT,error_msg TEXT,execution_time REAL);
            CREATE TABLE IF NOT EXISTS global_settings(id INTEGER PRIMARY KEY DEFAULT 1,delay_min INTEGER DEFAULT 2,delay_max INTEGER DEFAULT 5,max_reports_per_id INTEGER DEFAULT 20,require_approval INTEGER DEFAULT 1,auto_approve_enabled INTEGER DEFAULT 0,default_user_sessions INTEGER DEFAULT 5,default_user_reports_per_day INTEGER DEFAULT 50,flood_protection INTEGER DEFAULT 1,maintenance_mode INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS user_settings(user_id INTEGER PRIMARY KEY,reports_per_target INTEGER DEFAULT 1,selected_sessions INTEGER DEFAULT 0,delay_seconds INTEGER DEFAULT 3,auto_join INTEGER DEFAULT 1,random_order INTEGER DEFAULT 1,max_reports_per_session INTEGER DEFAULT 20);
            CREATE TABLE IF NOT EXISTS approval_requests(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,username TEXT,first_name TEXT,requested_date TEXT,status TEXT DEFAULT 'pending',reviewed_by INTEGER,reviewed_date TEXT,notes TEXT,approval_duration_days INTEGER);
            CREATE TABLE IF NOT EXISTS pending_reports(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,target TEXT,target_type TEXT,message_link TEXT,message_id INTEGER,reason TEXT,reason_name TEXT,reports_count INTEGER,sessions_count INTEGER,requested_date TEXT,status TEXT DEFAULT 'pending',approved_by INTEGER,approved_date TEXT,scheduled_time TEXT);
            CREATE TABLE IF NOT EXISTS statistics(user_id INTEGER PRIMARY KEY,total_sessions INTEGER DEFAULT 0,active_sessions INTEGER DEFAULT 0,total_reports INTEGER DEFAULT 0,successful_reports INTEGER DEFAULT 0,failed_reports INTEGER DEFAULT 0,last_report_date TEXT,targets_reported INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS flood_wait(session_phone TEXT PRIMARY KEY,wait_until TEXT,wait_seconds INTEGER);
            CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id,timestamp);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id,is_active);
            CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status,requested_date);
            CREATE INDEX IF NOT EXISTS idx_pending_reports_status ON pending_reports(status,requested_date);
            INSERT OR IGNORE INTO global_settings(id) VALUES(1);
        ''')
        self.conn.commit()
    def optimize(self):
        c=self.conn.cursor()
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA cache_size=10000")
        c.execute("PRAGMA temp_store=MEMORY")
        self.conn.commit()
    def execute(self,query,params=()):
        try:
            c=self.conn.cursor()
            c.execute(query,params)
            self.conn.commit()
            return c
        except Exception as e:
            logger.error(f"DB Error: {e}")
            return None
    def fetchone(self,query,params=()):
        c=self.execute(query,params)
        if c:
            row=c.fetchone()
            return dict(row) if row else None
        return None
    def fetchall(self,query,params=()):
        c=self.execute(query,params)
        return [dict(row) for row in c.fetchall()] if c else []

db=Database()
bot=TelegramClient('advanced_reporter_bot',API_ID,API_HASH).start(bot_token=BOT_TOKEN)

REASONS={"1":("📧 Spam",InputReportReasonSpam()),"2":("⚔️ Violence",InputReportReasonViolence()),"3":("🔞 Pornography",InputReportReasonPornography()),"4":("👶 Child Abuse",InputReportReasonChildAbuse()),"5":("© Copyright",InputReportReasonCopyright()),"6":("🎭 Fake Account",InputReportReasonFake()),"7":("💊 Illegal Drugs",InputReportReasonIllegalDrugs()),"8":("🔐 Personal Info",InputReportReasonPersonalDetails()),"9":("🌍 Geo Irrelevant",InputReportReasonGeoIrrelevant()),"10":("❓ Other",InputReportReasonOther()),"11":("💣 Terrorism",InputReportReasonViolence()),"12":("💰 Scam",InputReportReasonOther()),"13":("😡 Harassment",InputReportReasonOther()),"14":("🤖 Bot Spam",InputReportReasonSpam()),"15":("🎯 Custom",InputReportReasonOther()),"16":("🎣 Phishing",InputReportReasonOther()),"17":("🦠 Malware",InputReportReasonOther()),"18":("💀 Self Harm",InputReportReasonViolence()),"19":("🐕 Animal Abuse",InputReportReasonViolence()),"20":("☠️ Extremism",InputReportReasonViolence())}

user_states={}

def set_state(uid,state,**data):
    user_states[uid]={'state':state,'timestamp':time.time(),**data}

def get_state(uid):
    state=user_states.get(uid)
    if state and time.time()-state.get('timestamp',0)>1800:
        clear_state(uid)
        return None
    return state

def clear_state(uid):
    if uid in user_states:
        if 'client' in user_states[uid]:
            try:
                asyncio.create_task(user_states[uid]['client'].disconnect())
            except:
                pass
        del user_states[uid]

def is_owner(uid):
    return uid in OWNER_IDS

def check_user_access(uid):
    user=db.fetchone('SELECT is_approved,is_banned,is_owner FROM users WHERE user_id=?',(uid,))
    if not user:
        return False,'not_registered'
    if user['is_banned']:
        return False,'banned'
    if user['is_owner'] or is_owner(uid):
        return True,'owner'
    if not user['is_approved']:
        return False,'not_approved'
    return True,'approved'

def register_user(uid,username,first_name):
    existing=db.fetchone('SELECT user_id FROM users WHERE user_id=?',(uid,))
    if existing:
        db.execute('UPDATE users SET username=?,first_name=?,last_active=?,is_owner=? WHERE user_id=?',(username,first_name,datetime.now().isoformat(),1 if is_owner(uid) else 0,uid))
    else:
        db.execute('INSERT INTO users(user_id,username,first_name,joined_date,last_active,is_owner,is_approved) VALUES(?,?,?,?,?,?,?)',(uid,username,first_name,datetime.now().isoformat(),datetime.now().isoformat(),1 if is_owner(uid) else 0,1 if is_owner(uid) else 0))
        db.execute('INSERT OR IGNORE INTO user_settings(user_id) VALUES(?)',(uid,))
        db.execute('INSERT OR IGNORE INTO statistics(user_id) VALUES(?)',(uid,))

async def add_session_from_file(uid,session_path,phone,name):
    try:
        temp_client=TelegramClient(session_path,API_ID,API_HASH)
        try:
            await temp_client.connect()
            if not await temp_client.is_user_authorized():
                await temp_client.disconnect()
                return False,"Session not authorized"
            me=await temp_client.get_me()
            await temp_client.disconnect()
            final_name=name if name else f"Session_{phone}"
            session_file=f"{phone}_{int(time.time())}.session"
            final_path=os.path.join('sessions_db',session_file)
            shutil.copy2(session_path,final_path)
            db.execute('INSERT INTO sessions(user_id,phone,name,session_file,verified,added_date) VALUES(?,?,?,?,1,?)',(uid,phone,final_name,session_file,datetime.now().isoformat()))
            db.execute('UPDATE statistics SET total_sessions=total_sessions+1,active_sessions=active_sessions+1 WHERE user_id=?',(uid,))
            return True,"Session added successfully"
        except Exception as e:
            await temp_client.disconnect()
            return False,str(e)
    except Exception as e:
        return False,str(e)

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    uid=event.sender_id
    username=event.sender.username or ""
    first_name=event.sender.first_name or "User"
    register_user(uid,username,first_name)
    access,access_type=check_user_access(uid)
    if not access:
        if access_type=='banned':
            await event.respond("⛔ You are banned from using this bot.")
            return
        elif access_type=='not_approved':
            await event.respond("⏳ Your account is pending approval. Please wait for admin approval.",buttons=[[Button.inline("📮 Request Approval","request_approval")]])
            return
    buttons=[[Button.inline("🎯 Start Reporting","menu_main")]]
    if is_owner(uid):
        buttons.append([Button.inline("👑 Owner Panel","owner_panel")])
    buttons.append([Button.inline("📊 My Statistics","menu_stats")])
    buttons.append([Button.inline("⚙️ My Settings","menu_settings")])
    buttons.append([Button.inline("📱 Manage Sessions","menu_sessions")])
    await event.respond(f"👋 Welcome {first_name}!\n\n🤖 Advanced Telegram Reporter Bot v5.0\n\n✨ Features:\n├ Multi-session reporting\n├ Custom report counts\n├ Message & peer reporting\n├ Real-time statistics\n└ Professional interface\n\n🎯 Ready to start!",buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'menu_main'))
async def main_menu_handler(event):
    uid=event.sender_id
    access,_=check_user_access(uid)
    if not access:
        await event.answer("❌ Access denied",alert=True)
        return
    await event.edit("🎯 MAIN REPORTING MENU\n\nChoose reporting type:",buttons=[[Button.inline("📱 Report Peer/Channel","report_peer")],[Button.inline("💬 Report Message","report_message")],[Button.inline("📊 My Statistics","menu_stats")],[Button.inline("« Back","/start")]])

@bot.on(events.CallbackQuery(pattern=b'report_peer'))
async def report_peer_handler(event):
    uid=event.sender_id
    access,_=check_user_access(uid)
    if not access:
        await event.answer("❌ Access denied",alert=True)
        return
    sessions=db.fetchall('SELECT COUNT(*) as count FROM sessions WHERE user_id=? AND is_active=1',(uid,))
    if not sessions or sessions[0]['count']==0:
        await event.answer("❌ No active sessions! Add sessions first.",alert=True)
        return
    set_state(uid,'awaiting_target',target_type='peer')
    await event.edit("🎯 PEER/CHANNEL REPORTING\n\n📝 Send target username or link:\n\nExamples:\n├ @username\n├ https://t.me/username\n└ https://t.me/joinchat/xxxxx\n\n❌ /cancel to abort",buttons=[[Button.inline("« Cancel","menu_main")]])

@bot.on(events.CallbackQuery(pattern=b'report_message'))
async def report_message_handler(event):
    uid=event.sender_id
    access,_=check_user_access(uid)
    if not access:
        await event.answer("❌ Access denied",alert=True)
        return
    sessions=db.fetchall('SELECT COUNT(*) as count FROM sessions WHERE user_id=? AND is_active=1',(uid,))
    if not sessions or sessions[0]['count']==0:
        await event.answer("❌ No active sessions! Add sessions first.",alert=True)
        return
    set_state(uid,'awaiting_target',target_type='message')
    await event.edit("💬 MESSAGE REPORTING\n\n📝 Send message link:\n\nExamples:\n├ https://t.me/channel/123\n├ https://t.me/c/123456/789\n\n❌ /cancel to abort",buttons=[[Button.inline("« Cancel","menu_main")]])

@bot.on(events.NewMessage(func=lambda e:get_state(e.sender_id) and get_state(e.sender_id)['state']=='awaiting_target'))
async def target_input_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state:
        return
    target=event.text.strip()
    if target.startswith('/'):
        return
    target_type=state['target_type']
    message_id=None
    message_link=None
    if target_type=='message':
        msg_match=re.match(r'https?://t\.me/([^/]+)/(\d+)',target)
        msg_match_c=re.match(r'https?://t\.me/c/(\d+)/(\d+)',target)
        if msg_match:
            target=msg_match.group(1)
            message_id=int(msg_match.group(2))
            message_link=event.text.strip()
        elif msg_match_c:
            target=f"-100{msg_match_c.group(1)}"
            message_id=int(msg_match_c.group(2))
            message_link=event.text.strip()
        else:
            await event.respond("❌ Invalid message link format!\n\nUse: https://t.me/channel/123",buttons=[[Button.inline("« Back","menu_main")]])
            return
    else:
        if target.startswith('@'):
            target=target[1:]
        elif 't.me/' in target:
            target=target.split('t.me/')[-1].split('?')[0]
    set_state(uid,'awaiting_sessions_count',target=target,target_type=target_type,message_link=message_link,message_id=message_id)
    total_sessions=db.fetchone('SELECT COUNT(*) as count FROM sessions WHERE user_id=? AND is_active=1',(uid,))['count']
    buttons=[]
    for i in range(1,min(total_sessions+1,11)):
        buttons.append([Button.inline(f"{'✅' if i==total_sessions else '🔢'} {i} Session{'s' if i>1 else ''}",f"select_sessions_{i}")])
    if total_sessions>10:
        buttons.append([Button.inline(f"🔢 All {total_sessions} Sessions",f"select_sessions_{total_sessions}")])
    buttons.append([Button.inline("« Cancel","menu_main")])
    await event.respond(f"📱 SESSION SELECTION\n\n🎯 Target: {target}\n📊 Available Sessions: {total_sessions}\n\nSelect number of sessions to use:",buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'select_sessions_(\d+)'))
async def sessions_count_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state or state['state']!='awaiting_sessions_count':
        await event.answer("❌ Session expired. Start over.",alert=True)
        return
    sessions_count=int(event.data.decode().split('_')[-1])
    target=state['target']
    target_type=state['target_type']
    message_link=state.get('message_link')
    message_id=state.get('message_id')
    set_state(uid,'awaiting_reports_count',target=target,target_type=target_type,sessions_count=sessions_count,message_link=message_link,message_id=message_id)
    buttons=[]
    for i in [1,2,3,5,10,15,20]:
        buttons.append([Button.inline(f"📊 {i} Report{'s' if i>1 else ''} per session",f"select_reports_{i}")])
    buttons.append([Button.inline("« Back","menu_main")])
    await event.edit(f"📊 REPORT COUNT\n\n🎯 Target: {target}\n📱 Sessions: {sessions_count}\n\nSelect reports per session:",buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'select_reports_(\d+)'))
async def reports_count_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state or state['state']!='awaiting_reports_count':
        await event.answer("❌ Session expired. Start over.",alert=True)
        return
    reports_count=int(event.data.decode().split('_')[-1])
    target=state['target']
    sessions_count=state['sessions_count']
    target_type=state['target_type']
    message_link=state.get('message_link')
    message_id=state.get('message_id')
    set_state(uid,'awaiting_reason',target=target,sessions_count=sessions_count,reports_count=reports_count,target_type=target_type,message_link=message_link,message_id=message_id)
    buttons=[]
    for r_id,r_data in list(REASONS.items())[:10]:
        buttons.append([Button.inline(f"{r_data[0]}",f"reason_{r_id}")])
    buttons.append([Button.inline("📋 More Reasons","more_reasons")])
    buttons.append([Button.inline("« Cancel","menu_main")])
    await event.edit(f"📝 SELECT REASON\n\n🎯 Target: {target}\n📱 Sessions: {sessions_count}\n📊 Reports: {reports_count} per session\n\nSelect report reason:",buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'more_reasons'))
async def more_reasons_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state:
        await event.answer("❌ Session expired",alert=True)
        return
    buttons=[]
    for r_id,r_data in list(REASONS.items())[10:]:
        buttons.append([Button.inline(f"{r_data[0]}",f"reason_{r_id}")])
    buttons.append([Button.inline("« Back","report_peer")])
    await event.edit("📝 MORE REASONS\n\nSelect report reason:",buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'reason_(\d+)'))
async def reason_selection_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state or state['state']!='awaiting_reason':
        await event.answer("❌ Session expired. Start over.",alert=True)
        return
    reason_id=event.data.decode().split('_')[-1]
    if reason_id not in REASONS:
        await event.answer("❌ Invalid reason",alert=True)
        return
    await event.answer("⏳ Starting report execution...",alert=False)
    asyncio.create_task(execute_report(uid,reason_id))

async def execute_report(uid,reason_id):
    try:
        state=get_state(uid)
        if not state:
            await bot.send_message(uid,"❌ Session expired. Please start over.")
            return
        reason_name,reason_obj=REASONS[reason_id]
        target=state['target']
        reports_count=state['reports_count']
        sessions_count=state['sessions_count']
        target_type=state.get('target_type','peer')
        message_link=state.get('message_link')
        message_id=state.get('message_id')
        sessions=db.fetchall('SELECT * FROM sessions WHERE user_id=? AND is_active=1 ORDER BY health_score DESC LIMIT ?',(uid,sessions_count))
        if not sessions:
            await bot.send_message(uid,"❌ No active sessions found!")
            clear_state(uid)
            return
        global_settings=db.fetchone('SELECT * FROM global_settings WHERE id=1')
        delay_min=global_settings['delay_min']
        delay_max=global_settings['delay_max']
        progress_msg=await bot.send_message(uid,f"⏳ EXECUTING REPORT\n\n🎯 Target: {target}\n📝 Reason: {reason_name}\n📊 Reports: {reports_count} x {sessions_count} sessions\n💤 Delay: {delay_min}-{delay_max}s\n\nProgress: 0/{sessions_count} sessions")
        total_success=0
        total_failed=0
        for idx,session in enumerate(sessions,1):
            session_path=os.path.join('sessions_db',session['session_file'])
            if not os.path.exists(session_path):
                total_failed+=reports_count
                continue
            try:
                client=TelegramClient(session_path,API_ID,API_HASH)
                await client.connect()
                if not await client.is_user_authorized():
                    total_failed+=reports_count
                    await client.disconnect()
                    continue
                for rep in range(reports_count):
                    try:
                        start_time=time.time()
                        if target_type=='message' and message_id:
                            entity=await client.get_entity(target)
                            await client(ReportRequest(peer=entity,id=[message_id],reason=reason_obj,message="Violation"))
                        else:
                            entity=await client.get_entity(target)
                            await client(ReportPeerRequest(peer=entity,reason=reason_obj,message="Violation"))
                        execution_time=time.time()-start_time
                        db.execute('INSERT INTO reports(user_id,session_phone,target,target_type,message_link,message_id,reason,reason_name,success,timestamp,execution_time) VALUES(?,?,?,?,?,?,?,?,1,?,?)',(uid,session['phone'],target,target_type,message_link,message_id,reason_id,reason_name,datetime.now().isoformat(),execution_time))
                        total_success+=1
                        db.execute('UPDATE sessions SET success_reports=success_reports+1,total_reports=total_reports+1,last_used=? WHERE id=?',(datetime.now().isoformat(),session['id']))
                        if rep<reports_count-1:
                            await asyncio.sleep(random.uniform(delay_min,delay_max))
                    except FloodWaitError as e:
                        wait_time=e.seconds
                        db.execute('INSERT OR REPLACE INTO flood_wait(session_phone,wait_until,wait_seconds) VALUES(?,?,?)',(session['phone'],(datetime.now()+timedelta(seconds=wait_time)).isoformat(),wait_time))
                        total_failed+=(reports_count-rep)
                        break
                    except Exception as e:
                        db.execute('INSERT INTO reports(user_id,session_phone,target,target_type,message_link,message_id,reason,reason_name,success,timestamp,error_msg) VALUES(?,?,?,?,?,?,?,?,0,?,?)',(uid,session['phone'],target,target_type,message_link,message_id,reason_id,reason_name,datetime.now().isoformat(),str(e)[:200]))
                        total_failed+=1
                await client.disconnect()
                try:
                    await progress_msg.edit(f"⏳ EXECUTING REPORT\n\n🎯 Target: {target}\n📝 Reason: {reason_name}\n📊 Reports: {reports_count} x {sessions_count} sessions\n💤 Delay: {delay_min}-{delay_max}s\n\nProgress: {idx}/{sessions_count} sessions\n✅ Success: {total_success}\n❌ Failed: {total_failed}")
                except:
                    pass
                if idx<sessions_count:
                    await asyncio.sleep(random.uniform(delay_min,delay_max))
            except Exception as e:
                logger.error(f"Session error: {e}")
                total_failed+=reports_count
        db.execute('UPDATE statistics SET total_reports=total_reports+?,successful_reports=successful_reports+?,failed_reports=failed_reports+?,last_report_date=?,targets_reported=targets_reported+1 WHERE user_id=?',(total_success+total_failed,total_success,total_failed,datetime.now().isoformat(),uid))
        db.execute('UPDATE users SET total_reports=total_reports+?,successful_reports=successful_reports+? WHERE user_id=?',(total_success+total_failed,total_success,uid))
        success_rate=(total_success/(total_success+total_failed)*100) if (total_success+total_failed)>0 else 0
        await progress_msg.edit(f"✅ REPORT COMPLETED\n\n🎯 Target: {target}\n📝 Reason: {reason_name}\n\n📊 RESULTS:\n├ Total: {total_success+total_failed}\n├ Success: ✅ {total_success}\n├ Failed: ❌ {total_failed}\n└ Rate: {success_rate:.1f}%\n\n{'🎉 All reports successful!' if total_failed==0 else '⚠️ Some reports failed'}",buttons=[[Button.inline("🎯 Report Again","menu_main")],[Button.inline("« Main Menu","/start")]])
        clear_state(uid)
    except Exception as e:
        logger.error(f"Execute report error: {e}")
        await bot.send_message(uid,f"❌ Error executing report: {str(e)}")
        clear_state(uid)

@bot.on(events.CallbackQuery(pattern=b'menu_sessions'))
async def sessions_menu_handler(event):
    uid=event.sender_id
    access,_=check_user_access(uid)
    if not access:
        await event.answer("❌ Access denied",alert=True)
        return
    sessions=db.fetchall('SELECT COUNT(*) as total,SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) as active FROM sessions WHERE user_id=?',(uid,))
    total=sessions[0]['total'] if sessions else 0
    active=sessions[0]['active'] if sessions else 0
    await event.edit(f"📱 SESSION MANAGEMENT\n\n📊 Total Sessions: {total}\n✅ Active: {active}\n❌ Inactive: {total-active}\n\nWhat would you like to do?",buttons=[[Button.inline("➕ Add Session","add_session")],[Button.inline("📋 View Sessions","view_sessions")],[Button.inline("🗑️ Remove Session","remove_session")],[Button.inline("« Back","/start")]])

@bot.on(events.CallbackQuery(pattern=b'add_session'))
async def add_session_handler(event):
    uid=event.sender_id
    set_state(uid,'awaiting_session_file')
    await event.edit("📱 ADD SESSION\n\n📤 Upload your .session file\n\nOr send a .zip file containing multiple sessions\n\n❌ /cancel to abort",buttons=[[Button.inline("« Cancel","menu_sessions")]])

@bot.on(events.NewMessage(func=lambda e:e.is_private and e.document and get_state(e.sender_id) and get_state(e.sender_id)['state']=='awaiting_session_file'))
async def session_file_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state:
        return
    file_name=event.file.name
    if not file_name:
        await event.respond("❌ Invalid file. Please send a .session or .zip file.",buttons=[[Button.inline("« Back","menu_sessions")]])
        return
    if file_name.endswith('.zip'):
        progress_msg=await event.respond("⏳ Processing ZIP file...")
        try:
            zip_path=os.path.join('temp_files',f'{uid}_{int(time.time())}.zip')
            await event.download_media(zip_path)
            extract_dir=os.path.join('temp_files',f'extract_{uid}_{int(time.time())}')
            os.makedirs(extract_dir,exist_ok=True)
            with zipfile.ZipFile(zip_path,'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            session_files=[f for f in os.listdir(extract_dir) if f.endswith('.session')]
            if not session_files:
                await progress_msg.edit("❌ No .session files found in ZIP!",buttons=[[Button.inline("« Back","menu_sessions")]])
                shutil.rmtree(extract_dir,ignore_errors=True)
                os.remove(zip_path)
                clear_state(uid)
                return
            added=0
            failed=0
            for session_file in session_files:
                phone=session_file.replace('.session','')
                session_path=os.path.join(extract_dir,session_file)
                success,msg=await add_session_from_file(uid,session_path,phone,f"Session_{phone}")
                if success:
                    added+=1
                else:
                    failed+=1
            await progress_msg.edit(f"✅ Sessions Processed!\n\n✅ Added: {added}\n❌ Failed: {failed}\n\nTotal: {added+failed}",buttons=[[Button.inline("📱 View Sessions","view_sessions")],[Button.inline("« Back","menu_sessions")]])
            shutil.rmtree(extract_dir,ignore_errors=True)
            os.remove(zip_path)
            clear_state(uid)
        except Exception as e:
            await progress_msg.edit(f"❌ Error processing ZIP: {str(e)}",buttons=[[Button.inline("« Back","menu_sessions")]])
            clear_state(uid)
    elif file_name.endswith('.session'):
        progress_msg=await event.respond("⏳ Processing session file...")
        try:
            phone=file_name.replace('.session','')
            temp_path=os.path.join('temp_files',f'{uid}_{int(time.time())}.session')
            await event.download_media(temp_path)
            success,msg=await add_session_from_file(uid,temp_path,phone,f"Session_{phone}")
            if success:
                await progress_msg.edit(f"✅ {msg}\n\n📱 Phone: {phone}",buttons=[[Button.inline("📱 View Sessions","view_sessions")],[Button.inline("« Back","menu_sessions")]])
            else:
                await progress_msg.edit(f"❌ {msg}",buttons=[[Button.inline("« Back","menu_sessions")]])
            os.remove(temp_path)
            clear_state(uid)
        except Exception as e:
            await progress_msg.edit(f"❌ Error: {str(e)}",buttons=[[Button.inline("« Back","menu_sessions")]])
            clear_state(uid)
    else:
        await event.respond("❌ Invalid file type. Send .session or .zip file only.",buttons=[[Button.inline("« Back","menu_sessions")]])

@bot.on(events.CallbackQuery(pattern=b'view_sessions'))
async def view_sessions_handler(event):
    uid=event.sender_id
    sessions=db.fetchall('SELECT * FROM sessions WHERE user_id=? ORDER BY id DESC LIMIT 20',(uid,))
    if not sessions:
        await event.edit("📱 No sessions found!\n\nAdd your first session to get started.",buttons=[[Button.inline("➕ Add Session","add_session")],[Button.inline("« Back","menu_sessions")]])
        return
    text="📱 YOUR SESSIONS\n\n"
    for idx,s in enumerate(sessions,1):
        status="✅" if s['is_active'] else "❌"
        text+=f"{idx}. {status} {s['name']}\n   📞 {s['phone']}\n   📊 Reports: {s['total_reports']} (✅ {s['success_reports']})\n   💯 Health: {s['health_score']}%\n\n"
    buttons=[[Button.inline("➕ Add More","add_session")],[Button.inline("« Back","menu_sessions")]]
    await event.edit(text[:4000],buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'remove_session'))
async def remove_session_handler(event):
    uid=event.sender_id
    sessions=db.fetchall('SELECT * FROM sessions WHERE user_id=? ORDER BY id DESC LIMIT 10',(uid,))
    if not sessions:
        await event.answer("No sessions to remove",alert=True)
        return
    buttons=[]
    for s in sessions:
        buttons.append([Button.inline(f"🗑️ {s['name']} ({s['phone']})",f"delete_session_{s['id']}")])
    buttons.append([Button.inline("« Cancel","menu_sessions")])
    await event.edit("🗑️ SELECT SESSION TO REMOVE",buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'delete_session_(\d+)'))
async def delete_session_confirm_handler(event):
    uid=event.sender_id
    session_id=int(event.data.decode().split('_')[-1])
    session=db.fetchone('SELECT * FROM sessions WHERE id=? AND user_id=?',(session_id,uid))
    if not session:
        await event.answer("Session not found",alert=True)
        return
    session_file=os.path.join('sessions_db',session['session_file'])
    if os.path.exists(session_file):
        os.remove(session_file)
    db.execute('DELETE FROM sessions WHERE id=?',(session_id,))
    db.execute('UPDATE statistics SET total_sessions=total_sessions-1,active_sessions=active_sessions-? WHERE user_id=?',(1 if session['is_active'] else 0,uid))
    await event.answer("✅ Session removed",alert=False)
    await event.edit("✅ Session removed successfully!",buttons=[[Button.inline("📱 View Sessions","view_sessions")],[Button.inline("« Back","menu_sessions")]])

@bot.on(events.CallbackQuery(pattern=b'menu_stats'))
async def stats_menu_handler(event):
    uid=event.sender_id
    access,_=check_user_access(uid)
    if not access:
        await event.answer("❌ Access denied",alert=True)
        return
    stats=db.fetchone('SELECT * FROM statistics WHERE user_id=?',(uid,))
    user=db.fetchone('SELECT * FROM users WHERE user_id=?',(uid,))
    if not stats:
        await event.edit("📊 No statistics available yet.",buttons=[[Button.inline("« Back","/start")]])
        return
    success_rate=(stats['successful_reports']/stats['total_reports']*100) if stats['total_reports']>0 else 0
    text=f"📊 YOUR STATISTICS\n\n"
    text+=f"👤 User: {user['first_name']}\n"
    text+=f"📅 Joined: {user['joined_date'][:10]}\n\n"
    text+=f"📱 Sessions:\n"
    text+=f"├ Total: {stats['total_sessions']}\n"
    text+=f"└ Active: {stats['active_sessions']}\n\n"
    text+=f"📊 Reports:\n"
    text+=f"├ Total: {stats['total_reports']}\n"
    text+=f"├ Success: ✅ {stats['successful_reports']}\n"
    text+=f"├ Failed: ❌ {stats['failed_reports']}\n"
    text+=f"└ Rate: {success_rate:.1f}%\n\n"
    text+=f"🎯 Targets: {stats['targets_reported']}\n"
    if stats['last_report_date']:
        text+=f"📅 Last: {stats['last_report_date'][:10]}"
    await event.edit(text,buttons=[[Button.inline("🔄 Refresh","menu_stats")],[Button.inline("« Back","/start")]])

@bot.on(events.CallbackQuery(pattern=b'menu_settings'))
async def settings_menu_handler(event):
    uid=event.sender_id
    access,_=check_user_access(uid)
    if not access:
        await event.answer("❌ Access denied",alert=True)
        return
    settings=db.fetchone('SELECT * FROM user_settings WHERE user_id=?',(uid,))
    if not settings:
        db.execute('INSERT INTO user_settings(user_id) VALUES(?)',(uid,))
        settings=db.fetchone('SELECT * FROM user_settings WHERE user_id=?',(uid,))
    text=f"⚙️ YOUR SETTINGS\n\n"
    text+=f"📊 Reports per target: {settings['reports_per_target']}\n"
    text+=f"📱 Selected sessions: {settings['selected_sessions'] if settings['selected_sessions']>0 else 'All'}\n"
    text+=f"⏱️ Delay: {settings['delay_seconds']}s\n"
    text+=f"🔗 Auto-join: {'✅' if settings['auto_join'] else '❌'}\n"
    text+=f"🔀 Random order: {'✅' if settings['random_order'] else '❌'}\n"
    await event.edit(text,buttons=[[Button.inline("« Back","/start")]])

@bot.on(events.CallbackQuery(pattern=b'owner_panel'))
async def owner_panel_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner access only",alert=True)
        return
    total_users=db.fetchone('SELECT COUNT(*) as count FROM users')['count']
    pending=db.fetchone('SELECT COUNT(*) as count FROM approval_requests WHERE status="pending"')['count']
    await event.edit(f"👑 OWNER PANEL\n\n📊 Statistics:\n├ Total Users: {total_users}\n├ Pending Approvals: {pending}\n└ System: Online\n\nSelect option:",buttons=[[Button.inline("👥 User Management","owner_users")],[Button.inline("✅ Approvals","owner_approvals")],[Button.inline("⚙️ Global Settings","owner_settings")],[Button.inline("📢 Broadcast","owner_broadcast")],[Button.inline("« Back","/start")]])

@bot.on(events.CallbackQuery(pattern=b'owner_users'))
async def owner_users_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Access denied",alert=True)
        return
    users=db.fetchall('SELECT * FROM users ORDER BY joined_date DESC LIMIT 10')
    text="👥 USER MANAGEMENT\n\n"
    for u in users:
        status="👑" if u['is_owner'] else "✅" if u['is_approved'] else "⏳"
        text+=f"{status} {u['first_name']} (@{u['username'] or 'N/A'})\n   ID: {u['user_id']}\n   Reports: {u['total_reports']}\n\n"
    await event.edit(text[:4000],buttons=[[Button.inline("« Back","owner_panel")]])

@bot.on(events.CallbackQuery(pattern=b'owner_approvals'))
async def owner_approvals_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Access denied",alert=True)
        return
    requests=db.fetchall('SELECT * FROM approval_requests WHERE status="pending" ORDER BY requested_date DESC LIMIT 10')
    if not requests:
        await event.edit("✅ No pending approval requests!",buttons=[[Button.inline("« Back","owner_panel")]])
        return
    buttons=[]
    for req in requests:
        buttons.append([Button.inline(f"👤 {req['first_name']} ({req['user_id']})",f"approve_user_{req['user_id']}")])
    buttons.append([Button.inline("« Back","owner_panel")])
    await event.edit(f"✅ PENDING APPROVALS ({len(requests)})\n\nSelect user to approve:",buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'approve_user_(\d+)'))
async def approve_user_handler(event):
    owner_id=event.sender_id
    if not is_owner(owner_id):
        await event.answer("❌ Access denied",alert=True)
        return
    target_uid=int(event.data.decode().split('_')[-1])
    db.execute('UPDATE users SET is_approved=1,approved_by=?,approved_date=? WHERE user_id=?',(owner_id,datetime.now().isoformat(),target_uid))
    db.execute('UPDATE approval_requests SET status="approved",reviewed_by=?,reviewed_date=? WHERE user_id=?',(owner_id,datetime.now().isoformat(),target_uid))
    await event.answer("✅ User approved!",alert=False)
    try:
        await bot.send_message(target_uid,"✅ Your account has been approved! You can now use all features.")
    except:
        pass
    await event.edit("✅ User approved successfully!",buttons=[[Button.inline("✅ More Approvals","owner_approvals")],[Button.inline("« Back","owner_panel")]])

@bot.on(events.CallbackQuery(pattern=b'owner_settings'))
async def owner_settings_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Access denied",alert=True)
        return
    settings=db.fetchone('SELECT * FROM global_settings WHERE id=1')
    text=f"⚙️ GLOBAL SETTINGS\n\n"
    text+=f"⏱️ Delay: {settings['delay_min']}-{settings['delay_max']}s\n"
    text+=f"📊 Max reports per ID: {settings['max_reports_per_id']}\n"
    text+=f"✅ Require approval: {'Yes' if settings['require_approval'] else 'No'}\n"
    text+=f"🛡️ Flood protection: {'On' if settings['flood_protection'] else 'Off'}\n"
    text+=f"🔧 Maintenance: {'On' if settings['maintenance_mode'] else 'Off'}\n"
    await event.edit(text,buttons=[[Button.inline("« Back","owner_panel")]])

@bot.on(events.CallbackQuery(pattern=b'owner_broadcast'))
async def owner_broadcast_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Access denied",alert=True)
        return
    set_state(uid,'awaiting_broadcast')
    await event.edit("📢 BROADCAST MESSAGE\n\nSend message to broadcast to all users:\n\n❌ /cancel to abort",buttons=[[Button.inline("« Cancel","owner_panel")]])

@bot.on(events.NewMessage(func=lambda e:e.is_private and get_state(e.sender_id) and get_state(e.sender_id)['state']=='awaiting_broadcast'))
async def broadcast_message_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        return
    state=get_state(uid)
    if not state:
        return
    msg_text=event.text
    if msg_text.startswith('/'):
        return
    users=db.fetchall('SELECT user_id FROM users WHERE is_banned=0')
    progress_msg=await event.respond(f"📢 Broadcasting to {len(users)} users...")
    sent=0
    failed=0
    for user in users:
        try:
            await bot.send_message(user['user_id'],f"📢 BROADCAST MESSAGE\n\n{msg_text}")
            sent+=1
            await asyncio.sleep(0.1)
        except:
            failed+=1
    await progress_msg.edit(f"✅ Broadcast complete!\n\n✅ Sent: {sent}\n❌ Failed: {failed}",buttons=[[Button.inline("« Back","owner_panel")]])
    clear_state(uid)

@bot.on(events.CallbackQuery(pattern=b'request_approval'))
async def request_approval_handler(event):
    uid=event.sender_id
    existing=db.fetchone('SELECT * FROM approval_requests WHERE user_id=? AND status="pending"',(uid,))
    if existing:
        await event.answer("You already have a pending request",alert=True)
        return
    user=db.fetchone('SELECT * FROM users WHERE user_id=?',(uid,))
    db.execute('INSERT INTO approval_requests(user_id,username,first_name,requested_date) VALUES(?,?,?,?)',(uid,user['username'],user['first_name'],datetime.now().isoformat()))
    await event.answer("✅ Approval request sent!",alert=False)
    await event.edit("✅ Approval request submitted!\n\nPlease wait for admin review.",buttons=[[Button.inline("« Back","/start")]])
    for owner_id in OWNER_IDS:
        try:
            await bot.send_message(owner_id,f"📮 NEW APPROVAL REQUEST\n\n👤 User: {user['first_name']}\n🆔 ID: {uid}\n📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",buttons=[[Button.inline("✅ Approve",f"approve_user_{uid}")],[Button.inline("👑 Owner Panel","owner_panel")]])
        except:
            pass

@bot.on(events.NewMessage(pattern='/cancel'))
async def cancel_handler(event):
    uid=event.sender_id
    clear_state(uid)
    await event.respond("❌ Operation cancelled",buttons=[[Button.inline("« Menu","menu_main")]])

def main():
    print("""
╔════════════════════════════════════════════════════╗
║                                                    ║
║   🎯 ADVANCED TELEGRAM REPORTER BOT v5.0 🎯       ║
║        Professional Edition with Approval          ║
║                                                    ║
╚════════════════════════════════════════════════════╝

✨ Features:
  ├ 👑 Owner/User Separation
  ├ ✅ Approval System
  ├ 📊 Settings per User & Global
  ├ 💬 Message Link Reporting
  ├ 🎯 Peer Reporting
  ├ 📱 Session Management
  ├ 📦 ZIP Upload Support
  ├ 🔢 Session Selection (1-20+)
  ├ 🔢 Report Count Selection (1-20)
  ├ ⏱️ Configurable Delays
  ├ 📈 Detailed Statistics
  ├ 🛡️ Flood Protection
  ├ 📢 Broadcast System
  ├ 👥 User Management
  └ 🔐 Secure & Professional

🔥 System Status:
  ├ Database: ✅ Connected
  ├ Bot: ✅ Online
  ├ API: ✅ Authenticated
  └ Owner: ✅ Configured

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📱 Bot is running...
💡 Press Ctrl+C to stop
""")
    try:
        logger.info("Advanced Reporter Bot started")
        bot.run_until_disconnected()
    except KeyboardInterrupt:
        print("\n\n⚠️  Shutting down...")
        logger.info("Bot stopped by user")
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        logger.exception("Fatal error")
    finally:
        try:
            db.conn.close()
            print("✅ Database closed")
        except:
            pass
        print("✅ Cleanup complete\n")

if __name__=="__main__":
    main()
