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
            actual_phone=me.phone if me.phone else phone
            await temp_client.disconnect()
            final_path=os.path.join('sessions_db',f"{uid}_{actual_phone.replace('+','').replace(' ','')}.session")
            shutil.move(session_path,final_path)
            db.execute('INSERT OR REPLACE INTO sessions(user_id,phone,name,session_file,verified,added_date,is_active,health_score) VALUES(?,?,?,?,1,?,1,100)',(uid,actual_phone,name or f"Session {actual_phone}",os.path.basename(final_path),datetime.now().isoformat()))
            db.execute('UPDATE statistics SET total_sessions=total_sessions+1,active_sessions=(SELECT COUNT(*) FROM sessions WHERE user_id=? AND is_active=1) WHERE user_id=?',(uid,uid))
            return True,"Session added successfully"
        except Exception as e:
            await temp_client.disconnect()
            return False,f"Session verification failed: {str(e)}"
    except Exception as e:
        return False,f"Error adding session: {str(e)}"

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    uid=event.sender_id
    user=await event.get_sender()
    username=user.username or ""
    first_name=user.first_name or "User"
    register_user(uid,username,first_name)
    db.execute('UPDATE users SET last_active=? WHERE user_id=?',(datetime.now().isoformat(),uid))
    has_access,reason=check_user_access(uid)
    welcome_text=f"╔═══════════════════════════════╗\n║  🎯 ADVANCED REPORTER BOT 🎯  ║\n║     Professional Edition       ║\n╚═══════════════════════════════╝\n\n👋 Welcome, {first_name}!\n\n"
    if is_owner(uid):
        welcome_text+="🔱 OWNER ACCESS GRANTED\n\nYou have full control over:\n├ 👥 User Management\n├ ⚙️ Global Settings\n├ ✅ Approval System\n├ 📊 Full Statistics\n└ 🎯 All Features\n"
        buttons=[[Button.inline("👑 Owner Menu","owner_menu")],[Button.inline("📊 Bot Statistics","owner_stats")],[Button.inline("⚙️ Global Settings","owner_settings")],[Button.inline("✅ Approvals","owner_approvals")],[Button.inline("🎯 Report (Owner)","menu_main")]]
    else:
        if reason=='not_approved':
            existing_request=db.fetchone("SELECT id FROM approval_requests WHERE user_id=? AND status='pending'",(uid,))
            if existing_request:
                welcome_text+="⏳ APPROVAL PENDING\n\nYour access request is being reviewed.\nPlease wait for owner approval.\n\nStatus: Waiting for Review"
                await event.respond(welcome_text,buttons=[[Button.inline("🔄 Refresh","/start")]])
                return
            else:
                welcome_text+="🔐 APPROVAL REQUIRED\n\nYour account needs approval from the bot owner.\nClick below to request access:"
                buttons=[[Button.inline("📝 Request Access","request_approval")]]
                await event.respond(welcome_text,buttons=buttons)
                return
        welcome_text+="✅ ACCESS GRANTED\n\nAvailable features:\n├ 📱 Session Management\n├ 🎯 Report Targets\n├ 💬 Report Messages\n├ 📊 Your Statistics\n└ ⚙️ Your Settings\n"
        buttons=[[Button.inline("🎯 Start Reporting","menu_main")],[Button.inline("📱 My Sessions","menu_sessions")],[Button.inline("📊 My Stats","menu_stats"),Button.inline("⚙️ My Settings","user_settings_menu")]]
    await event.respond(welcome_text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'request_approval'))
async def request_approval_handler(event):
    uid=event.sender_id
    user=await event.get_sender()
    username=user.username or "No username"
    first_name=user.first_name or "User"
    existing=db.fetchone("SELECT id FROM approval_requests WHERE user_id=? AND status='pending'",(uid,))
    if existing:
        await event.answer("⏳ You already have a pending request!",alert=True)
        return
    db.execute('INSERT INTO approval_requests(user_id,username,first_name,requested_date) VALUES(?,?,?,?)',(uid,username,first_name,datetime.now().isoformat()))
    await event.answer("✅ Request submitted! Wait for owner approval.",alert=True)
    for owner_id in OWNER_IDS:
        try:
            await bot.send_message(owner_id,f"📢 NEW APPROVAL REQUEST\n\n👤 User: {first_name} (@{username})\n🆔 ID: {uid}\n📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\nUse /approvals or click button below:",buttons=[[Button.inline("✅ View Approvals","owner_approvals")]])
        except:
            pass
    await event.edit("✅ Access request submitted successfully!\n\nYour request has been sent to the bot owner.\nYou will be notified once approved.\n\nPlease wait patiently.",buttons=[[Button.inline("« Back","/start")]])

@bot.on(events.CallbackQuery(pattern=b'owner_menu'))
async def owner_menu_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    total_users=db.fetchone("SELECT COUNT(*) as count FROM users")['count']
    approved_users=db.fetchone("SELECT COUNT(*) as count FROM users WHERE is_approved=1")['count']
    pending_approvals=db.fetchone("SELECT COUNT(*) as count FROM approval_requests WHERE status='pending'")['count']
    total_sessions=db.fetchone("SELECT COUNT(*) as count FROM sessions")['count']
    total_reports=db.fetchone("SELECT COUNT(*) as count FROM reports")['count']
    pending_reports=db.fetchone("SELECT COUNT(*) as count FROM pending_reports WHERE status='pending'")['count']
    text=f"╔══════════════════════════════╗\n║     👑 OWNER CONTROL PANEL    ║\n╚══════════════════════════════╝\n\n📊 BOT STATISTICS:\n├ Total Users: {total_users}\n├ Approved: {approved_users}\n├ Pending Approvals: {pending_approvals}\n├ Total Sessions: {total_sessions}\n├ Total Reports: {total_reports}\n└ Pending Reports: {pending_reports}\n\nSelect an option:"
    buttons=[[Button.inline("✅ Pending Approvals","owner_approvals"),Button.inline("📋 Pending Reports","owner_pending_reports")],[Button.inline("👥 User Management","owner_users"),Button.inline("📊 Statistics","owner_stats")],[Button.inline("⚙️ Global Settings","owner_settings"),Button.inline("📢 Broadcast","owner_broadcast")],[Button.inline("🎯 Report (Owner)","menu_main"),Button.inline("« Main Menu","/start")]]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'owner_approvals'))
async def owner_approvals_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    pending=db.fetchall("SELECT * FROM approval_requests WHERE status='pending' ORDER BY requested_date DESC LIMIT 10")
    if not pending:
        await event.edit("✅ No pending approval requests",buttons=[[Button.inline("« Back","owner_menu")]])
        return
    text="🔐 PENDING APPROVAL REQUESTS:\n\n"
    buttons=[]
    for req in pending:
        req_date=datetime.fromisoformat(req['requested_date']).strftime('%Y-%m-%d %H:%M')
        text+=f"━━━━━━━━━━━━━━━━\n👤 {req['first_name']} (@{req['username']})\n🆔 ID: {req['user_id']}\n📅 {req_date}\n\n"
        buttons.append([Button.inline(f"✅ Approve",f"approve_{req['id']}"),Button.inline(f"❌ Reject",f"reject_{req['id']}")])
    buttons.append([Button.inline("« Back","owner_menu")])
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'approve_(\d+)'))
async def approve_user_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    req_id=int(event.data.decode().split('_')[1])
    req=db.fetchone('SELECT * FROM approval_requests WHERE id=?',(req_id,))
    if not req:
        await event.answer("❌ Request not found",alert=True)
        return
    set_state(uid,'approve_duration',req_id=req_id,user_id=req['user_id'])
    await event.edit(f"✅ Approve User: {req['first_name']}\n\nSelect approval duration:",buttons=[[Button.inline("🔓 Permanent",f"approve_perm_{req_id}")],[Button.inline("📅 7 Days Trial",f"approve_trial_7_{req_id}")],[Button.inline("📅 15 Days Trial",f"approve_trial_15_{req_id}")],[Button.inline("📅 30 Days Trial",f"approve_trial_30_{req_id}")],[Button.inline("« Cancel","owner_approvals")]])

@bot.on(events.CallbackQuery(pattern=rb'approve_(perm|trial)_(\d+)_(\d+)'))
async def process_approval_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    data_parts=event.data.decode().split('_')
    if data_parts[1]=='perm':
        approval_type='permanent'
        days=None
        req_id=int(data_parts[2])
    else:
        days=int(data_parts[2])
        approval_type=f'trial_{days}d'
        req_id=int(data_parts[3])
    req=db.fetchone('SELECT * FROM approval_requests WHERE id=?',(req_id,))
    if not req:
        await event.answer("❌ Request not found",alert=True)
        return
    now=datetime.now().isoformat()
    db.execute('UPDATE approval_requests SET status=?,reviewed_by=?,reviewed_date=?,approval_duration_days=? WHERE id=?',('approved',uid,now,days,req_id))
    db.execute('UPDATE users SET is_approved=1,approval_type=?,approved_by=?,approved_date=? WHERE user_id=?',(approval_type,uid,now,req['user_id']))
    await event.answer("✅ User approved!",alert=True)
    approval_text=f"╔══════════════════════════════╗\n║      ✅ APPROVAL GRANTED      ║\n╚══════════════════════════════╝\n\nYour access request has been approved!\n\nType: {approval_type.upper()}\n"
    if days:
        approval_text+=f"Valid for: {days} days\n"
    approval_text+="\nYou can now use all bot features!"
    try:
        await bot.send_message(req['user_id'],approval_text,buttons=[[Button.inline("🎯 Start","/start")]])
    except:
        pass
    await owner_approvals_handler(event)

@bot.on(events.CallbackQuery(pattern=rb'reject_(\d+)'))
async def reject_user_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    req_id=int(event.data.decode().split('_')[1])
    req=db.fetchone('SELECT * FROM approval_requests WHERE id=?',(req_id,))
    if not req:
        await event.answer("❌ Request not found",alert=True)
        return
    now=datetime.now().isoformat()
    db.execute('UPDATE approval_requests SET status=?,reviewed_by=?,reviewed_date=? WHERE id=?',('rejected',uid,now,req_id))
    await event.answer("❌ Request rejected",alert=True)
    try:
        await bot.send_message(req['user_id'],"╔══════════════════════════════╗\n║      ❌ REQUEST DENIED        ║\n╚══════════════════════════════╝\n\nYour access request has been reviewed and denied.\n\nIf you believe this was a mistake, please contact support.")
    except:
        pass
    await owner_approvals_handler(event)

@bot.on(events.CallbackQuery(pattern=b'owner_pending_reports'))
async def owner_pending_reports_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    pending=db.fetchall("SELECT pr.*,u.first_name,u.username FROM pending_reports pr JOIN users u ON pr.user_id=u.user_id WHERE pr.status='pending' ORDER BY pr.requested_date DESC LIMIT 10")
    if not pending:
        await event.edit("✅ No pending report requests",buttons=[[Button.inline("« Back","owner_menu")]])
        return
    text="📋 PENDING REPORT REQUESTS:\n\n"
    buttons=[]
    for req in pending:
        req_date=datetime.fromisoformat(req['requested_date']).strftime('%Y-%m-%d %H:%M')
        text+=f"━━━━━━━━━━━━━━━━\n👤 {req['first_name']} (@{req['username']})\n🎯 {req['target']}\n📝 {req['reason_name']}\n📊 {req['reports_count']} x {req['sessions_count']}\n📅 {req_date}\n\n"
        buttons.append([Button.inline(f"✅ Approve",f"preport_approve_{req['id']}"),Button.inline(f"❌ Reject",f"preport_reject_{req['id']}")])
    buttons.append([Button.inline("« Back","owner_menu")])
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'preport_(approve|reject)_(\d+)'))
async def pending_report_action_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    data_parts=event.data.decode().split('_')
    action=data_parts[1]
    report_id=int(data_parts[2])
    req=db.fetchone('SELECT * FROM pending_reports WHERE id=?',(report_id,))
    if not req:
        await event.answer("❌ Request not found",alert=True)
        return
    now=datetime.now().isoformat()
    if action=='approve':
        db.execute('UPDATE pending_reports SET status=?,approved_by=?,approved_date=? WHERE id=?',('approved',uid,now,report_id))
        await event.answer("✅ Report approved! Executing...",alert=True)
        state={'target':req['target'],'target_type':req['target_type'],'message_link':req['message_link'],'message_id':req['message_id'],'reason':req['reason'],'reason_name':req['reason_name'],'reports_count':req['reports_count'],'sessions_count':req['sessions_count']}
        try:
            await bot.send_message(req['user_id'],"✅ REPORT APPROVED\n\nYour report request has been approved and is being executed.\nYou will receive a notification once completed.")
        except:
            pass
        asyncio.create_task(execute_report(req['user_id'],state))
    else:
        db.execute('UPDATE pending_reports SET status=?,approved_by=?,approved_date=? WHERE id=?',('rejected',uid,now,report_id))
        await event.answer("❌ Report rejected",alert=True)
        try:
            await bot.send_message(req['user_id'],"❌ REPORT REJECTED\n\nYour report request has been reviewed and rejected.\n\nIf you have questions, please contact support.")
        except:
            pass
    await owner_pending_reports_handler(event)

@bot.on(events.CallbackQuery(pattern=b'owner_settings'))
async def owner_settings_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    settings=db.fetchone('SELECT * FROM global_settings WHERE id=1')
    text=f"╔══════════════════════════════╗\n║     ⚙️ GLOBAL SETTINGS ⚙️      ║\n╚══════════════════════════════╝\n\nCurrent Global Settings:\n├ Delay Min: {settings['delay_min']}s\n├ Delay Max: {settings['delay_max']}s\n├ Max Reports/ID: {settings['max_reports_per_id']}\n├ Require Approval: {'✅' if settings['require_approval'] else '❌'}\n├ Auto Approve: {'✅' if settings['auto_approve_enabled'] else '❌'}\n├ Flood Protection: {'✅' if settings['flood_protection'] else '❌'}\n└ Maintenance: {'✅' if settings['maintenance_mode'] else '❌'}\n\nSelect setting to modify:"
    buttons=[[Button.inline("⏱️ Delay Min","gsetting_delay_min"),Button.inline("⏱️ Delay Max","gsetting_delay_max")],[Button.inline("📊 Max Reports/ID","gsetting_max_reports")],[Button.inline("✅ Approval Mode","gsetting_approval")],[Button.inline("🛡️ Protection","gsetting_protection")],[Button.inline("🔧 Maintenance","gsetting_maintenance")],[Button.inline("« Back","owner_menu")]]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'gsetting_approval'))
async def gsetting_approval_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    settings=db.fetchone('SELECT require_approval FROM global_settings WHERE id=1')
    current=settings['require_approval']
    new_value=0 if current else 1
    db.execute('UPDATE global_settings SET require_approval=? WHERE id=1',(new_value,))
    await event.answer(f"✅ Approval requirement: {'ENABLED' if new_value else 'DISABLED'}",alert=True)
    await owner_settings_handler(event)

@bot.on(events.CallbackQuery(pattern=b'gsetting_protection'))
async def gsetting_protection_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    settings=db.fetchone('SELECT flood_protection FROM global_settings WHERE id=1')
    current=settings['flood_protection']
    new_value=0 if current else 1
    db.execute('UPDATE global_settings SET flood_protection=? WHERE id=1',(new_value,))
    await event.answer(f"✅ Flood Protection: {'ENABLED' if new_value else 'DISABLED'}",alert=True)
    await owner_settings_handler(event)

@bot.on(events.CallbackQuery(pattern=b'gsetting_maintenance'))
async def gsetting_maintenance_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    settings=db.fetchone('SELECT maintenance_mode FROM global_settings WHERE id=1')
    current=settings['maintenance_mode']
    new_value=0 if current else 1
    db.execute('UPDATE global_settings SET maintenance_mode=? WHERE id=1',(new_value,))
    await event.answer(f"✅ Maintenance Mode: {'ENABLED' if new_value else 'DISABLED'}",alert=True)
    await owner_settings_handler(event)

@bot.on(events.CallbackQuery(pattern=b'gsetting_delay_min'))
async def gsetting_delay_min_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    set_state(uid,'awaiting_delay_min')
    await event.edit("⏱️ SET MINIMUM DELAY\n\nEnter minimum delay in seconds (1-60):\n\nType /cancel to cancel",buttons=[[Button.inline("« Cancel","owner_settings")]])

@bot.on(events.CallbackQuery(pattern=b'gsetting_delay_max'))
async def gsetting_delay_max_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    set_state(uid,'awaiting_delay_max')
    await event.edit("⏱️ SET MAXIMUM DELAY\n\nEnter maximum delay in seconds (1-60):\n\nType /cancel to cancel",buttons=[[Button.inline("« Cancel","owner_settings")]])

@bot.on(events.CallbackQuery(pattern=b'gsetting_max_reports'))
async def gsetting_max_reports_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    set_state(uid,'awaiting_max_reports')
    await event.edit("📊 SET MAX REPORTS PER ID\n\nEnter maximum reports per session ID (1-100):\n\nType /cancel to cancel",buttons=[[Button.inline("« Cancel","owner_settings")]])

@bot.on(events.CallbackQuery(pattern=b'owner_users'))
async def owner_users_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    users=db.fetchall("SELECT * FROM users WHERE is_owner=0 ORDER BY joined_date DESC LIMIT 20")
    text="👥 USER MANAGEMENT\n\n"
    buttons=[]
    for u in users:
        status="✅" if u['is_approved'] else "⏳" if not u['is_banned'] else "🚫"
        text+=f"{status} {u['first_name']} (@{u['username']}) - ID: {u['user_id']}\n"
        buttons.append([Button.inline(f"👤 {u['first_name'][:15]}",f"umanage_{u['user_id']}")])
    buttons.append([Button.inline("« Back","owner_menu")])
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'umanage_(\d+)'))
async def user_manage_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    target_uid=int(event.data.decode().split('_')[1])
    user=db.fetchone('SELECT * FROM users WHERE user_id=?',(target_uid,))
    if not user:
        await event.answer("❌ User not found",alert=True)
        return
    text=f"👤 USER MANAGEMENT\n\n🆔 ID: {user['user_id']}\n👤 Name: {user['first_name']}\n📱 Username: @{user['username']}\n📅 Joined: {user['joined_date'][:10]}\n✅ Approved: {'Yes' if user['is_approved'] else 'No'}\n🚫 Banned: {'Yes' if user['is_banned'] else 'No'}\n\nSelect action:"
    buttons=[]
    if user['is_banned']:
        buttons.append([Button.inline("✅ Unban User",f"uunban_{target_uid}")])
    else:
        buttons.append([Button.inline("🚫 Ban User",f"uban_{target_uid}")])
    if not user['is_approved']:
        buttons.append([Button.inline("✅ Approve User",f"uapprove_{target_uid}")])
    buttons.append([Button.inline("🗑️ Delete User",f"udelete_{target_uid}")])
    buttons.append([Button.inline("« Back","owner_users")])
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'uban_(\d+)'))
async def user_ban_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    target_uid=int(event.data.decode().split('_')[1])
    db.execute('UPDATE users SET is_banned=1 WHERE user_id=?',(target_uid,))
    await event.answer("✅ User banned",alert=True)
    await user_manage_handler(event)

@bot.on(events.CallbackQuery(pattern=rb'uunban_(\d+)'))
async def user_unban_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    target_uid=int(event.data.decode().split('_')[1])
    db.execute('UPDATE users SET is_banned=0 WHERE user_id=?',(target_uid,))
    await event.answer("✅ User unbanned",alert=True)
    await user_manage_handler(event)

@bot.on(events.CallbackQuery(pattern=rb'uapprove_(\d+)'))
async def user_quick_approve_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    target_uid=int(event.data.decode().split('_')[1])
    db.execute('UPDATE users SET is_approved=1,approval_type=? WHERE user_id=?',('permanent',target_uid))
    await event.answer("✅ User approved",alert=True)
    await user_manage_handler(event)

@bot.on(events.CallbackQuery(pattern=b'owner_broadcast'))
async def owner_broadcast_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    set_state(uid,'awaiting_broadcast')
    await event.edit("📢 BROADCAST MESSAGE\n\nSend the message you want to broadcast to all users:\n\nType /cancel to cancel",buttons=[[Button.inline("« Cancel","owner_menu")]])

@bot.on(events.CallbackQuery(pattern=b'owner_stats'))
async def owner_stats_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only",alert=True)
        return
    total_users=db.fetchone("SELECT COUNT(*) as count FROM users")['count']
    approved_users=db.fetchone("SELECT COUNT(*) as count FROM users WHERE is_approved=1")['count']
    banned_users=db.fetchone("SELECT COUNT(*) as count FROM users WHERE is_banned=1")['count']
    total_sessions=db.fetchone("SELECT COUNT(*) as count FROM sessions")['count']
    active_sessions=db.fetchone("SELECT COUNT(*) as count FROM sessions WHERE is_active=1")['count']
    total_reports=db.fetchone("SELECT COUNT(*) as count FROM reports")['count']
    success_reports=db.fetchone("SELECT COUNT(*) as count FROM reports WHERE success=1")['count']
    failed_reports=db.fetchone("SELECT COUNT(*) as count FROM reports WHERE success=0")['count']
    success_rate=(success_reports/total_reports*100) if total_reports>0 else 0
    text=f"╔══════════════════════════════╗\n║    📊 BOT STATISTICS (GLOBAL)  ║\n╚══════════════════════════════╝\n\n👥 Users:\n├ Total: {total_users}\n├ Approved: {approved_users}\n└ Banned: {banned_users}\n\n📱 Sessions:\n├ Total: {total_sessions}\n└ Active: {active_sessions}\n\n📊 Reports:\n├ Total: {total_reports}\n├ Success: ✅ {success_reports}\n├ Failed: ❌ {failed_reports}\n└ Rate: {success_rate:.1f}%\n\n🔥 Bot Performance: {'🟢 EXCELLENT' if success_rate>90 else '🟡 GOOD' if success_rate>70 else '🔴 NEEDS ATTENTION'}"
    buttons=[[Button.inline("🔄 Refresh","owner_stats")],[Button.inline("« Back","owner_menu")]]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'menu_main'))
async def main_menu_handler(event):
    uid=event.sender_id
    has_access,reason=check_user_access(uid)
    if not has_access:
        if reason=='not_approved':
            await event.answer("❌ Your account is not approved yet!",alert=True)
        elif reason=='banned':
            await event.answer("❌ Your account has been banned!",alert=True)
        else:
            await event.answer("❌ Access denied!",alert=True)
        return
    stats=db.fetchone('SELECT * FROM statistics WHERE user_id=?',(uid,)) or {}
    sessions_count=stats.get('active_sessions',0)
    text=f"╔══════════════════════════════╗\n║       🎯 REPORTER MENU 🎯      ║\n╚══════════════════════════════╝\n\n📊 Your Stats:\n├ Sessions: {sessions_count}\n├ Total Reports: {stats.get('total_reports',0)}\n└ Success: {stats.get('successful_reports',0)}\n\nSelect report type:"
    buttons=[[Button.inline("👤 Report User/Channel","report_peer")],[Button.inline("💬 Report Message","report_message")],[Button.inline("📱 My Sessions","menu_sessions")],[Button.inline("📊 Statistics","menu_stats"),Button.inline("⚙️ Settings","user_settings_menu")]]
    if is_owner(uid):
        buttons.append([Button.inline("👑 Owner Menu","owner_menu")])
    buttons.append([Button.inline("« Main Menu","/start")])
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'report_peer'))
async def report_peer_handler(event):
    uid=event.sender_id
    has_access,reason=check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!",alert=True)
        return
    set_state(uid,'awaiting_target')
    await event.edit("🎯 REPORT USER/CHANNEL/GROUP\n\nSend me the target:\n├ Username: @username\n├ User ID: 123456789\n├ Channel Link: https://t.me/channel\n├ Group Link: https://t.me/group\n└ Private Group Link: https://t.me/+...\n\nType /cancel to cancel",buttons=[[Button.inline("« Cancel","menu_main")]])

@bot.on(events.CallbackQuery(pattern=b'report_message'))
async def report_message_handler(event):
    uid=event.sender_id
    has_access,reason=check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!",alert=True)
        return
    set_state(uid,'awaiting_message_link')
    await event.edit("💬 REPORT MESSAGE\n\nSend me the message link:\nhttps://t.me/channel/12345\nor\nhttps://t.me/c/123456/789\n\nThe message link must be from a public or private channel/group.\n\nType /cancel to cancel",buttons=[[Button.inline("« Cancel","menu_main")]])

@bot.on(events.CallbackQuery(pattern=rb'reason_(\d+)'))
async def reason_selection_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state:
        await event.answer("❌ Session expired",alert=True)
        return
    reason_id=event.data.decode().split('_')[1]
    reason_name,reason_obj=REASONS[reason_id]
    state['reason']=reason_id
    state['reason_name']=reason_name
    set_state(uid,'awaiting_reports_count',**state)
    settings=db.fetchone('SELECT max_reports_per_session FROM user_settings WHERE user_id=?',(uid,))
    max_reports=settings['max_reports_per_session'] if settings else 20
    await event.edit(f"✅ Selected: {reason_name}\n\n🎯 Target: {state['target']}\n📝 Reason: {reason_name}\n\nHow many reports per session? (1-{max_reports})\n\nType /cancel to cancel",buttons=[[Button.inline("« Cancel","menu_main")]])

@bot.on(events.CallbackQuery(pattern=b'menu_sessions'))
async def sessions_menu_handler(event):
    uid=event.sender_id
    has_access,reason=check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!",alert=True)
        return
    sessions=db.fetchall('SELECT * FROM sessions WHERE user_id=? ORDER BY added_date DESC',(uid,))
    text=f"╔══════════════════════════════╗\n║      📱 SESSION MANAGER       ║\n╚══════════════════════════════╝\n\nTotal Sessions: {len(sessions)}\nActive: {sum(1 for s in sessions if s['is_active'])}\n\n"
    if sessions:
        text+="Your sessions:\n\n"
        for sess in sessions[:5]:
            status="✅" if sess['is_active'] else "❌"
            health="💚" if sess['health_score']>80 else "💛" if sess['health_score']>50 else "❤️"
            text+=f"{status} {sess['phone']}\n   {health} Health: {sess['health_score']}% | Reports: {sess['success_reports']}/{sess['total_reports']}\n\n"
        if len(sessions)>5:
            text+=f"... and {len(sessions)-5} more\n"
    else:
        text+="❌ No sessions added yet\n"
    buttons=[[Button.inline("➕ Add Session","add_session")],[Button.inline("📦 Upload ZIP","upload_zip")],[Button.inline("📋 View All","view_sessions")],[Button.inline("« Back","menu_main")]]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'add_session'))
async def add_session_handler(event):
    uid=event.sender_id
    has_access,reason=check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!",alert=True)
        return
    set_state(uid,'awaiting_session_file')
    await event.edit("➕ ADD SESSION\n\nSend me your .session file\n\nThe file should be a Telethon session file.\n\nType /cancel to cancel",buttons=[[Button.inline("« Cancel","menu_sessions")]])

@bot.on(events.CallbackQuery(pattern=b'upload_zip'))
async def upload_zip_handler(event):
    uid=event.sender_id
    has_access,reason=check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!",alert=True)
        return
    set_state(uid,'awaiting_zip_file')
    await event.edit("📦 UPLOAD ZIP\n\nSend me a ZIP file containing .session files\n\nAll valid sessions will be added to your account.\n\nType /cancel to cancel",buttons=[[Button.inline("« Cancel","menu_sessions")]])

@bot.on(events.CallbackQuery(pattern=b'view_sessions'))
async def view_sessions_handler(event):
    uid=event.sender_id
    has_access,reason=check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!",alert=True)
        return
    sessions=db.fetchall('SELECT * FROM sessions WHERE user_id=? ORDER BY health_score DESC',(uid,))
    if not sessions:
        await event.edit("❌ No sessions found",buttons=[[Button.inline("« Back","menu_sessions")]])
        return
    text="📱 ALL SESSIONS:\n\n"
    for idx,sess in enumerate(sessions,1):
        status="✅" if sess['is_active'] else "❌"
        health="💚" if sess['health_score']>80 else "💛" if sess['health_score']>50 else "❤️"
        text+=f"{idx}. {status} {sess['phone']}\n   {health} Health: {sess['health_score']}%\n   📊 Reports: {sess['success_reports']}/{sess['total_reports']}\n   📅 Added: {sess['added_date'][:10]}\n\n"
    await event.edit(text,buttons=[[Button.inline("« Back","menu_sessions")]])

@bot.on(events.CallbackQuery(pattern=b'user_settings_menu'))
async def user_settings_menu_handler(event):
    uid=event.sender_id
    has_access,reason=check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!",alert=True)
        return
    settings=db.fetchone('SELECT * FROM user_settings WHERE user_id=?',(uid,)) or {}
    text=f"╔══════════════════════════════╗\n║      ⚙️ YOUR SETTINGS ⚙️       ║\n╚══════════════════════════════╝\n\nCurrent Settings:\n├ Reports per target: {settings.get('reports_per_target',1)}\n├ Max reports per ID: {settings.get('max_reports_per_session',20)}\n├ Delay: {settings.get('delay_seconds',3)}s\n├ Auto join: {'✅' if settings.get('auto_join',1) else '❌'}\n└ Random order: {'✅' if settings.get('random_order',1) else '❌'}\n\nSelect option to change:"
    buttons=[[Button.inline("📊 Reports/Target","setting_reports")],[Button.inline("🔢 Max Reports/ID","setting_max_reports_id")],[Button.inline("⏱️ Delay Time","setting_delay")],[Button.inline("🔀 Random Order","setting_random")],[Button.inline("« Back","menu_main")]]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'setting_max_reports_id'))
async def setting_max_reports_id_handler(event):
    uid=event.sender_id
    has_access,reason=check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!",alert=True)
        return
    set_state(uid,'awaiting_max_reports_setting')
    await event.edit("🔢 SET MAX REPORTS PER ID\n\nEnter maximum reports you want per session (1-20):\n\nThis controls how many times each session will report.\n\nType /cancel to cancel",buttons=[[Button.inline("« Cancel","user_settings_menu")]])

@bot.on(events.CallbackQuery(pattern=b'setting_random'))
async def setting_random_handler(event):
    uid=event.sender_id
    has_access,reason=check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!",alert=True)
        return
    settings=db.fetchone('SELECT random_order FROM user_settings WHERE user_id=?',(uid,))
    current=settings['random_order'] if settings else 1
    new_value=0 if current else 1
    db.execute('UPDATE user_settings SET random_order=? WHERE user_id=?',(new_value,uid))
    await event.answer(f"✅ Random order: {'ENABLED' if new_value else 'DISABLED'}",alert=True)
    await user_settings_menu_handler(event)

@bot.on(events.CallbackQuery(pattern=b'menu_stats'))
async def stats_menu_handler(event):
    uid=event.sender_id
    has_access,reason=check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!",alert=True)
        return
    stats=db.fetchone('SELECT * FROM statistics WHERE user_id=?',(uid,)) or {}
    user=db.fetchone('SELECT * FROM users WHERE user_id=?',(uid,))
    total=stats.get('total_reports',0)
    success=stats.get('successful_reports',0)
    failed=stats.get('failed_reports',0)
    success_rate=(success/total*100) if total>0 else 0
    text=f"╔══════════════════════════════╗\n║      📊 YOUR STATISTICS       ║\n╚══════════════════════════════╝\n\n📱 Sessions:\n├ Total: {stats.get('total_sessions',0)}\n└ Active: {stats.get('active_sessions',0)}\n\n📊 Reports:\n├ Total: {total}\n├ Success: ✅ {success}\n├ Failed: ❌ {failed}\n└ Rate: {success_rate:.1f}%\n\n🎯 Targets Reported: {stats.get('targets_reported',0)}\n📅 Last Report: {stats.get('last_report_date','Never')[:10] if stats.get('last_report_date') else 'Never'}\n🔥 Account Status: {'👑 OWNER' if user['is_owner'] else '✅ APPROVED'}"
    buttons=[[Button.inline("🔄 Refresh","menu_stats")],[Button.inline("« Back","menu_main")]]
    await event.edit(text,buttons=buttons)

@bot.on(events.NewMessage)
async def text_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state:
        return
    if state['state']=='awaiting_target':
        target=event.text.strip()
        if not target or target.startswith('/'):
            return
        set_state(uid,'select_reason',target=target,target_type='peer')
        text=f"🎯 Target: {target}\n\n📝 Select report reason:"
        buttons=[]
        for i in range(1,21,2):
            row=[]
            if str(i) in REASONS:
                row.append(Button.inline(REASONS[str(i)][0],f"reason_{i}"))
            if str(i+1) in REASONS:
                row.append(Button.inline(REASONS[str(i+1)][0],f"reason_{i+1}"))
            if row:
                buttons.append(row)
        buttons.append([Button.inline("« Cancel","menu_main")])
        await event.respond(text,buttons=buttons)
    elif state['state']=='awaiting_message_link':
        message_link=event.text.strip()
        if not message_link or 't.me/' not in message_link or message_link.startswith('/'):
            return
        try:
            if '/c/' in message_link:
                parts=message_link.split('/c/')[-1].split('/')
                chat_id=int(parts[0])
                msg_id=int(parts[1])
                target=f"-100{chat_id}"
            else:
                parts=message_link.split('/')
                channel=parts[-2]
                msg_id=int(parts[-1])
                target=channel
            set_state(uid,'select_reason',target=target,target_type='message',message_link=message_link,message_id=msg_id)
            text=f"💬 Message: {message_link}\n\n📝 Select report reason:"
            buttons=[]
            for i in range(1,21,2):
                row=[]
                if str(i) in REASONS:
                    row.append(Button.inline(REASONS[str(i)][0],f"reason_{i}"))
                if str(i+1) in REASONS:
                    row.append(Button.inline(REASONS[str(i+1)][0],f"reason_{i+1}"))
                if row:
                    buttons.append(row)
            buttons.append([Button.inline("« Cancel","menu_main")])
            await event.respond(text,buttons=buttons)
        except Exception as e:
            await event.respond(f"❌ Error parsing message link: {str(e)}")
            return
    elif state['state']=='awaiting_reports_count':
        try:
            count=int(event.text.strip())
            settings=db.fetchone('SELECT max_reports_per_session FROM user_settings WHERE user_id=?',(uid,))
            max_reports=settings['max_reports_per_session'] if settings else 20
            if count<1 or count>max_reports:
                await event.respond(f"❌ Please enter a number between 1 and {max_reports}")
                return
            state['reports_count']=count
            set_state(uid,'awaiting_sessions_count',**state)
            sessions=db.fetchall('SELECT COUNT(*) as count FROM sessions WHERE user_id=? AND is_active=1',(uid,))
            available=sessions[0]['count'] if sessions else 0
            if available==0:
                await event.respond("❌ No active sessions found! Please add sessions first.",buttons=[[Button.inline("📱 Add Sessions","menu_sessions")]])
                clear_state(uid)
                return
            await event.respond(f"✅ Reports per session: {count}\n\n📱 Available sessions: {available}\n\nHow many sessions to use? (1-{available})\n\nType /cancel to cancel")
        except ValueError:
            await event.respond("❌ Please enter a valid number")
    elif state['state']=='awaiting_sessions_count':
        try:
            count=int(event.text.strip())
            sessions=db.fetchall('SELECT COUNT(*) as count FROM sessions WHERE user_id=? AND is_active=1',(uid,))
            available=sessions[0]['count'] if sessions else 0
            if count<1 or count>available:
                await event.respond(f"❌ Please enter a number between 1 and {available}")
                return
            state['sessions_count']=count
            global_settings=db.fetchone('SELECT * FROM global_settings WHERE id=1')
            if is_owner(uid) or not global_settings['require_approval']:
                await event.respond("⏳ Preparing to execute report...")
                await execute_report(uid,state)
            else:
                db.execute('INSERT INTO pending_reports(user_id,target,target_type,message_link,message_id,reason,reason_name,reports_count,sessions_count,requested_date) VALUES(?,?,?,?,?,?,?,?,?,?)',(uid,state['target'],state.get('target_type','peer'),state.get('message_link'),state.get('message_id'),state['reason'],state['reason_name'],state['reports_count'],count,datetime.now().isoformat()))
                await event.respond(f"✅ Report request submitted!\n\nYour report has been queued for owner approval.\nYou will be notified once it's approved.\n\n📊 Summary:\n├ Target: {state['target']}\n├ Reason: {state['reason_name']}\n├ Reports: {state['reports_count']}\n└ Sessions: {count}",buttons=[[Button.inline("« Menu","menu_main")]])
                for owner_id in OWNER_IDS:
                    try:
                        user=db.fetchone('SELECT first_name,username FROM users WHERE user_id=?',(uid,))
                        await bot.send_message(owner_id,f"📢 NEW REPORT REQUEST\n\n👤 User: {user['first_name']} (@{user['username']})\n🎯 Target: {state['target']}\n📝 Reason: {state['reason_name']}\n📊 Reports: {state['reports_count']} x {count} sessions\n\nUse button below to review:",buttons=[[Button.inline("📋 View Pending","owner_pending_reports")]])
                    except:
                        pass
                clear_state(uid)
        except ValueError:
            await event.respond("❌ Please enter a valid number")
    elif state['state']=='awaiting_session_file':
        if not event.file:
            return
        filename=event.file.name
        if not filename or not filename.endswith('.session'):
            await event.respond("❌ Please send a valid .session file")
            return
        try:
            file_path=await event.download_media(file=f"temp_files/{uid}_{int(time.time())}.session")
            phone=filename.replace('.session','').strip()
            success,message=await add_session_from_file(uid,file_path,phone,phone)
            if success:
                await event.respond(f"✅ {message}",buttons=[[Button.inline("📱 Sessions","menu_sessions")]])
            else:
                await event.respond(f"❌ {message}",buttons=[[Button.inline("🔄 Try Again","add_session")]])
            clear_state(uid)
            try:
                os.remove(file_path)
            except:
                pass
        except Exception as e:
            await event.respond(f"❌ Error: {str(e)}")
            clear_state(uid)
    elif state['state']=='awaiting_zip_file':
        if not event.file:
            return
        filename=event.file.name
        if not filename or not filename.endswith('.zip'):
            await event.respond("❌ Please send a valid .zip file")
            return
        try:
            zpath=await event.download_media(file=f"temp_files/{uid}_{int(time.time())}.zip")
            msg=await event.respond("📦 Processing ZIP file...")
            added=0
            failed=0
            with zipfile.ZipFile(zpath,'r') as zf:
                session_files=[f for f in zf.namelist() if f.endswith('.session')]
                total=len(session_files)
                if total==0:
                    await msg.edit("❌ No .session files found in ZIP",buttons=[[Button.inline("« Back","menu_sessions")]])
                    os.remove(zpath)
                    clear_state(uid)
                    return
                for idx,sf in enumerate(session_files,1):
                    try:
                        tpath=f"temp_files/{uid}_{int(time.time())}_{idx}.session"
                        with open(tpath,'wb') as tf:
                            tf.write(zf.read(sf))
                        phone=sf.replace('.session','').strip()
                        success,message=await add_session_from_file(uid,tpath,phone,phone)
                        if success:
                            added+=1
                        else:
                            failed+=1
                        try:
                            os.remove(tpath)
                        except:
                            pass
                        if idx%5==0 or idx==total:
                            try:
                                await msg.edit(f"📦 Processing: {idx}/{total}\n✅ Added: {added}\n❌ Failed: {failed}")
                            except:
                                pass
                    except Exception as e:
                        logger.error(f"Extract: {e}")
                        failed+=1
            await msg.edit(f"╔══════════════════════════╗\n║   📦 ZIP COMPLETE 📦    ║\n╚══════════════════════════╝\n\n📊 Results:\n  ├ Total: {total}\n  ├ Added: ✅ {added}\n  └ Failed: ❌ {failed}\n\n{'🎯 Ready!' if added>0 else ''}",buttons=[[Button.inline("📱 Sessions","menu_sessions")],[Button.inline("« Menu","menu_main")]])
            os.remove(zpath)
            clear_state(uid)
        except Exception as e:
            await event.respond(f"❌ ZIP Error: {str(e)[:80]}",buttons=[[Button.inline("« Back","menu_sessions")]])
            clear_state(uid)
    elif state['state']=='awaiting_delay_min':
        try:
            value=int(event.text.strip())
            if value<1 or value>60:
                await event.respond("❌ Please enter a number between 1 and 60")
                return
            db.execute('UPDATE global_settings SET delay_min=? WHERE id=1',(value,))
            await event.respond(f"✅ Minimum delay set to {value} seconds",buttons=[[Button.inline("⚙️ Settings","owner_settings")]])
            clear_state(uid)
        except ValueError:
            await event.respond("❌ Please enter a valid number")
    elif state['state']=='awaiting_delay_max':
        try:
            value=int(event.text.strip())
            if value<1 or value>60:
                await event.respond("❌ Please enter a number between 1 and 60")
                return
            db.execute('UPDATE global_settings SET delay_max=? WHERE id=1',(value,))
            await event.respond(f"✅ Maximum delay set to {value} seconds",buttons=[[Button.inline("⚙️ Settings","owner_settings")]])
            clear_state(uid)
        except ValueError:
            await event.respond("❌ Please enter a valid number")
    elif state['state']=='awaiting_max_reports':
        try:
            value=int(event.text.strip())
            if value<1 or value>100:
                await event.respond("❌ Please enter a number between 1 and 100")
                return
            db.execute('UPDATE global_settings SET max_reports_per_id=? WHERE id=1',(value,))
            await event.respond(f"✅ Max reports per ID set to {value}",buttons=[[Button.inline("⚙️ Settings","owner_settings")]])
            clear_state(uid)
        except ValueError:
            await event.respond("❌ Please enter a valid number")
    elif state['state']=='awaiting_max_reports_setting':
        try:
            value=int(event.text.strip())
            if value<1 or value>20:
                await event.respond("❌ Please enter a number between 1 and 20")
                return
            db.execute('UPDATE user_settings SET max_reports_per_session=? WHERE user_id=?',(value,uid))
            await event.respond(f"✅ Max reports per ID set to {value}",buttons=[[Button.inline("⚙️ Settings","user_settings_menu")]])
            clear_state(uid)
        except ValueError:
            await event.respond("❌ Please enter a valid number")
    elif state['state']=='awaiting_broadcast':
        if event.text.startswith('/'):
            return
        broadcast_text=event.text
        users=db.fetchall("SELECT user_id FROM users WHERE is_owner=0")
        sent=0
        failed=0
        msg=await event.respond(f"📢 Broadcasting to {len(users)} users...")
        for u in users:
            try:
                await bot.send_message(u['user_id'],f"📢 BROADCAST MESSAGE\n\n{broadcast_text}")
                sent+=1
            except:
                failed+=1
            if sent%10==0:
                try:
                    await msg.edit(f"📢 Broadcasting...\n✅ Sent: {sent}\n❌ Failed: {failed}")
                except:
                    pass
        await msg.edit(f"✅ Broadcast complete!\n\n📊 Results:\n├ Sent: ✅ {sent}\n└ Failed: ❌ {failed}",buttons=[[Button.inline("« Back","owner_menu")]])
        clear_state(uid)

async def execute_report(uid,state):
    try:
        target=state['target']
        reason_id=state['reason']
        reason_name=state['reason_name']
        reports_count=state['reports_count']
        sessions_count=state['sessions_count']
        target_type=state.get('target_type','peer')
        message_link=state.get('message_link')
        message_id=state.get('message_id')
        _,reason_obj=REASONS[reason_id]
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
  ├ 🔢 1-20 Reports per Session
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
