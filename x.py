#!/usr/bin/env python3
import os,sys,json,asyncio,zipfile,shutil,time,random,logging,sqlite3,hashlib,re
from datetime import datetime,timedelta
from typing import Dict,List,Optional,Tuple,Any
from pathlib import Path
from telethon import TelegramClient,events,Button
from telethon.errors import *
from telethon.tl.functions.account import ReportPeerRequest
from telethon.tl.functions.messages import ReportRequest,CheckChatInviteRequest,ImportChatInviteRequest,GetMessagesRequest
from telethon.tl.functions.channels import JoinChannelRequest,LeaveChannelRequest,GetParticipantsRequest
from telethon.tl.types import *

API_ID=28286832
API_HASH="2a8fba924d58c9c3f928d7db2c149b47"
BOT_TOKEN="7930383726:AAETy8tyvgZcP6UaPYuaQwLAkGUu9qyNJ4Q"
ADMIN_IDS=[8101867786]

for d in ['sessions_db','temp_files','data','backups','logs','exports','cache']:
    os.makedirs(d,exist_ok=True)

logging.basicConfig(level=logging.INFO,format='%(asctime)s [%(levelname)s] %(message)s',handlers=[logging.FileHandler(f'logs/bot_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),logging.StreamHandler()])
logger=logging.getLogger(__name__)

class DB:
    def __init__(self):
        self.conn=sqlite3.connect('data/reporter.db',check_same_thread=False,timeout=30)
        self.init_db()
        self.migrate_db()
    
    def init_db(self):
        c=self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY,username TEXT,first_name TEXT,joined_date TEXT,last_active TEXT,is_premium INTEGER DEFAULT 0,is_approved INTEGER DEFAULT 0,is_banned INTEGER DEFAULT 0,approval_type TEXT,trial_expires TEXT,max_sessions INTEGER DEFAULT 0,max_reports_per_day INTEGER DEFAULT 0,approved_by INTEGER,approved_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,phone TEXT,name TEXT,session_file TEXT,verified INTEGER,added_date TEXT,total_reports INTEGER DEFAULT 0,success_reports INTEGER DEFAULT 0,failed_reports INTEGER DEFAULT 0,is_active INTEGER DEFAULT 1,last_used TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,session_phone TEXT,target TEXT,target_type TEXT,reason TEXT,success INTEGER,timestamp TEXT,error_msg TEXT,comment TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings(user_id INTEGER PRIMARY KEY,delay INTEGER DEFAULT 2,report_limit INTEGER DEFAULT 50,auto_join INTEGER DEFAULT 1,session_count INTEGER DEFAULT 0,random_order INTEGER DEFAULT 1,retry_failed INTEGER DEFAULT 0,reports_per_target INTEGER DEFAULT 1)''')
        c.execute('''CREATE TABLE IF NOT EXISTS statistics(user_id INTEGER PRIMARY KEY,total_sessions INTEGER DEFAULT 0,total_reports INTEGER DEFAULT 0,successful_reports INTEGER DEFAULT 0,failed_reports INTEGER DEFAULT 0,last_report_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS flood_wait(session_phone TEXT PRIMARY KEY,wait_until TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS targets_cache(target TEXT PRIMARY KEY,entity_id TEXT,entity_type TEXT,cached_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS approval_requests(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,username TEXT,first_name TEXT,request_type TEXT,requested_date TEXT,status TEXT DEFAULT 'pending',reviewed_by INTEGER,reviewed_date TEXT,notes TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_limits(user_id INTEGER PRIMARY KEY,daily_reports_used INTEGER DEFAULT 0,last_reset_date TEXT)''')
        self.conn.commit()
    
    def migrate_db(self):
        c=self.conn.cursor()
        migrations=[
            ("last_used","sessions","ALTER TABLE sessions ADD COLUMN last_used TEXT"),
            ("session_count","settings","ALTER TABLE settings ADD COLUMN session_count INTEGER DEFAULT 0"),
            ("random_order","settings","ALTER TABLE settings ADD COLUMN random_order INTEGER DEFAULT 1"),
            ("retry_failed","settings","ALTER TABLE settings ADD COLUMN retry_failed INTEGER DEFAULT 0"),
            ("error_msg","reports","ALTER TABLE reports ADD COLUMN error_msg TEXT"),
            ("target_type","reports","ALTER TABLE reports ADD COLUMN target_type TEXT"),
            ("reports_per_target","settings","ALTER TABLE settings ADD COLUMN reports_per_target INTEGER DEFAULT 1"),
            ("is_approved","users","ALTER TABLE users ADD COLUMN is_approved INTEGER DEFAULT 0"),
            ("approval_type","users","ALTER TABLE users ADD COLUMN approval_type TEXT"),
            ("trial_expires","users","ALTER TABLE users ADD COLUMN trial_expires TEXT"),
            ("max_sessions","users","ALTER TABLE users ADD COLUMN max_sessions INTEGER DEFAULT 0"),
            ("max_reports_per_day","users","ALTER TABLE users ADD COLUMN max_reports_per_day INTEGER DEFAULT 0"),
            ("approved_by","users","ALTER TABLE users ADD COLUMN approved_by INTEGER"),
            ("approved_date","users","ALTER TABLE users ADD COLUMN approved_date TEXT"),
            ("comment","reports","ALTER TABLE reports ADD COLUMN comment TEXT")
        ]
        for col,table,sql in migrations:
            try:
                c.execute(f"SELECT {col} FROM {table} LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    c.execute(sql)
                    self.conn.commit()
                except:pass
    
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
            return row
        return None
    
    def fetchall(self,query,params=()):
        c=self.execute(query,params)
        return c.fetchall() if c else []

db=DB()
bot=TelegramClient('reporter_bot',API_ID,API_HASH).start(bot_token=BOT_TOKEN)

# Complete list of all Telegram report reasons
REASONS={
    "1":("📧 Spam",InputReportReasonSpam()),
    "2":("⚔️ Violence",InputReportReasonViolence()),
    "3":("🔞 Pornography",InputReportReasonPornography()),
    "4":("👶 Child Abuse",InputReportReasonChildAbuse()),
    "5":("© Copyright",InputReportReasonCopyright()),
    "6":("🎭 Fake Account",InputReportReasonFake()),
    "7":("💊 Illegal Drugs",InputReportReasonIllegalDrugs()),
    "8":("🔐 Personal Details",InputReportReasonPersonalDetails()),
    "9":("🌍 Geo Irrelevant",InputReportReasonGeoIrrelevant()),
    "10":("💰 Scam/Fraud",InputReportReasonFake()),
    "11":("🎣 Phishing",InputReportReasonFake()),
    "12":("🦠 Malware",InputReportReasonFake()),
    "13":("🛒 Fake Product",InputReportReasonFake()),
    "14":("🗣️ Harassment",InputReportReasonViolence()),
    "15":("🎯 Terrorism",InputReportReasonViolence()),
    "16":("❓ Other",InputReportReasonOther())
}

user_states={}

def set_state(uid,state,data=None):
    user_states[uid]={'state':state,'timestamp':time.time()}
    if data:
        user_states[uid].update(data)

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
            except:pass
        del user_states[uid]

def is_admin(uid):
    return uid in ADMIN_IDS

def check_user_access(uid):
    user=db.fetchone('SELECT is_approved,is_banned,trial_expires,approval_type FROM users WHERE user_id=?',(uid,))
    if not user:
        return False,'not_registered'
    if user[1]:
        return False,'banned'
    if is_admin(uid):
        return True,'admin'
    if not user[0]:
        return False,'not_approved'
    if user[3]and user[3].startswith('trial'):
        if user[2]:
            expires=datetime.fromisoformat(user[2])
            if datetime.now()>expires:
                db.execute('UPDATE users SET is_approved=0,approval_type=NULL WHERE user_id=?',(uid,))
                return False,'trial_expired'
    return True,'approved'

def check_daily_limit(uid):
    user=db.fetchone('SELECT max_reports_per_day FROM users WHERE user_id=?',(uid,))
    if not user or user[0]==0:
        return True,0
    
    limit_data=db.fetchone('SELECT daily_reports_used,last_reset_date FROM user_limits WHERE user_id=?',(uid,))
    today=datetime.now().date().isoformat()
    
    if not limit_data:
        db.execute('INSERT INTO user_limits(user_id,last_reset_date)VALUES(?,?)',(uid,today))
        return True,user[0]
    
    if limit_data[1]!=today:
        db.execute('UPDATE user_limits SET daily_reports_used=0,last_reset_date=? WHERE user_id=?',(today,uid))
        return True,user[0]
    
    if limit_data[0]>=user[0]:
        return False,0
    
    return True,user[0]-limit_data[0]

def increment_daily_usage(uid,count=1):
    db.execute('UPDATE user_limits SET daily_reports_used=daily_reports_used+? WHERE user_id=?',(count,uid))

def register_user(uid,username,first_name):
    if not db.fetchone('SELECT user_id FROM users WHERE user_id=?',(uid,)):
        now=datetime.now().isoformat()
        db.execute('INSERT INTO users(user_id,username,first_name,joined_date,last_active)VALUES(?,?,?,?,?)',(uid,username,first_name,now,now))
        db.execute('INSERT OR IGNORE INTO settings(user_id)VALUES(?)',(uid,))
        db.execute('INSERT OR IGNORE INTO statistics(user_id)VALUES(?)',(uid,))
        db.execute('INSERT INTO user_limits(user_id,last_reset_date)VALUES(?,?)',(uid,datetime.now().date().isoformat()))
        if not is_admin(uid):
            db.execute('INSERT INTO approval_requests(user_id,username,first_name,request_type,requested_date)VALUES(?,?,?,?,?)',(uid,username,first_name,'access',now))
    else:
        db.execute('UPDATE users SET last_active=? WHERE user_id=?',(datetime.now().isoformat(),uid))

def get_sessions(uid):
    rows=db.fetchall('SELECT id,phone,name,session_file,verified,added_date,total_reports,success_reports,failed_reports,last_used FROM sessions WHERE user_id=? AND is_active=1 ORDER BY success_reports DESC',(uid,))
    sessions=[]
    for r in rows:
        sessions.append({
            'id':r[0],
            'phone':r[1],
            'name':r[2],
            'session_file':r[3],
            'verified':r[4],
            'added_date':r[5],
            'total_reports':r[6],
            'success_reports':r[7],
            'failed_reports':r[8],
            'last_used':r[9]
        })
    return sessions

def add_session(uid,phone,name,session_file):
    user=db.fetchone('SELECT max_sessions FROM users WHERE user_id=?',(uid,))
    max_sessions=user[0]if user else 0
    
    if max_sessions>0:
        current=db.fetchone('SELECT COUNT(*) FROM sessions WHERE user_id=? AND is_active=1',(uid,))
        if current and current[0]>=max_sessions:
            return False
    
    if not db.fetchone('SELECT id FROM sessions WHERE user_id=? AND phone=?',(uid,phone)):
        now=datetime.now().isoformat()
        db.execute('INSERT INTO sessions(user_id,phone,name,session_file,verified,added_date)VALUES(?,?,?,?,?,?)',(uid,phone,name,session_file,1,now))
        db.execute('UPDATE statistics SET total_sessions=total_sessions+1 WHERE user_id=?',(uid,))
        return True
    return False

def remove_session(uid,session_id):
    session=db.fetchone('SELECT session_file FROM sessions WHERE id=? AND user_id=?',(session_id,uid))
    if session:
        try:
            os.remove(os.path.join('sessions_db',session[0]))
        except:pass
        db.execute('UPDATE sessions SET is_active=0 WHERE id=?',(session_id,))
        return True
    return False

async def verify_session(session_path):
    try:
        client=TelegramClient(session_path,API_ID,API_HASH)
        await client.connect()
        
        if not await client.is_user_authorized():
            await client.disconnect()
            return False,None,None
        
        me=await client.get_me()
        phone=me.phone
        name=f"{me.first_name or ''} {me.last_name or ''}".strip()
        
        await client.disconnect()
        return True,phone,name
    except Exception as e:
        logger.error(f"Verify: {e}")
        return False,None,None

async def get_entity_safe(client,target):
    try:
        return await client.get_entity(target)
    except:
        try:
            if target.startswith('https://t.me/'):
                target=target.replace('https://t.me/','').split('?')[0].split('/')[0]
            if target.startswith('@'):
                target=target[1:]
            return await client.get_entity(target)
        except Exception as e:
            logger.error(f"Entity: {e}")
            return None

async def report_with_session(session_file,target,reason_obj,msg_id=None,comment=None):
    try:
        spath=os.path.join('sessions_db',session_file)
        client=TelegramClient(spath.replace('.session',''),API_ID,API_HASH)
        await client.connect()
        
        if not await client.is_user_authorized():
            await client.disconnect()
            return False,"Not authorized"
        
        entity=await get_entity_safe(client,target)
        if not entity:
            await client.disconnect()
            return False,"Entity not found"
        
        # Report with comment if provided
        if msg_id:
            # Reporting a specific message
            await client(ReportRequest(
                peer=entity,
                id=[msg_id],
                reason=reason_obj,
                message=comment or ""
            ))
        else:
            # Reporting user/channel/group
            await client(ReportPeerRequest(
                peer=entity,
                reason=reason_obj,
                message=comment or ""
            ))
        
        await asyncio.sleep(random.uniform(1,2))
        await client.disconnect()
        return True,"Success"
    except FloodWaitError as e:
        return False,f"Flood {e.seconds}s"
    except Exception as e:
        return False,str(e)[:100]

async def auto_join_target(client,target):
    try:
        if 'joinchat/' in target or 't.me/+' in target:
            hash_part=target.split('/')[-1]
            result=await client(CheckChatInviteRequest(hash=hash_part))
            await client(ImportChatInviteRequest(hash=hash_part))
            return True
        else:
            entity=await get_entity_safe(client,target)
            if entity:
                await client(JoinChannelRequest(entity))
                return True
    except:
        pass
    return False

async def safe_edit_message(event,text,buttons=None):
    """Safely edit message, avoiding MessageNotModifiedError"""
    try:
        if buttons:
            await event.edit(text,buttons=buttons)
        else:
            await event.edit(text)
    except MessageNotModifiedError:
        # Message content is identical, no need to edit
        pass
    except Exception as e:
        logger.error(f"Edit error: {e}")

@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    uid=event.sender_id
    user=await event.get_sender()
    username=user.username or 'None'
    first_name=user.first_name or 'User'
    
    register_user(uid,username,first_name)
    
    access,status=check_user_access(uid)
    
    if status=='not_approved':
        await event.respond("""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃  ⏳ PENDING APPROVAL ⏳ ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Your access request is pending.
An admin will review soon.

📱 You'll be notified when approved.""")
        return
    
    if status=='banned':
        await event.respond("❌ You are banned")
        return
    
    if status=='trial_expired':
        await event.respond("""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃  ⌛ TRIAL EXPIRED ⌛   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Your trial period has ended.
Contact admin for full access.""")
        return
    
    sessions=get_sessions(uid)
    session_count=len(sessions)
    stats=db.fetchone('SELECT total_reports,successful_reports,failed_reports FROM statistics WHERE user_id=?',(uid,))
    total,success,failed=(stats[0],stats[1],stats[2])if stats else(0,0,0)
    
    can_report,remaining=check_daily_limit(uid)
    limit_text=f"\n📊 Daily: {remaining} left"if remaining>0 else""
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃  🎯 TELEGRAM REPORTER 🎯┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

👤 {first_name}
{'🌟 ADMIN' if is_admin(uid) else '✅ Active'}

📊 Statistics:
  ├ Sessions: {session_count}
  ├ Reports: {total}
  ├ Success: ✅ {success}
  └ Failed: ❌ {failed}{limit_text}

🚀 Ready to report!"""
    
    buttons=[
        [Button.inline("🎯 Report","report_main")],
        [Button.inline("📱 Sessions","menu_sessions"),Button.inline("⚙️ Settings","menu_settings")],
        [Button.inline("📊 Stats","menu_stats"),Button.inline("🛠️ Tools","menu_tools")]
    ]
    
    if is_admin(uid):
        buttons.append([Button.inline("👑 Admin","admin_main")])
    
    await event.respond(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'menu_main'))
async def menu_main(event):
    uid=event.sender_id
    
    access,status=check_user_access(uid)
    if not access:
        await safe_edit_message(event,"❌ Access denied")
        return
    
    sessions=get_sessions(uid)
    session_count=len(sessions)
    stats=db.fetchone('SELECT total_reports,successful_reports,failed_reports FROM statistics WHERE user_id=?',(uid,))
    total,success,failed=(stats[0],stats[1],stats[2])if stats else(0,0,0)
    
    can_report,remaining=check_daily_limit(uid)
    limit_text=f"\n📊 Daily: {remaining} left"if remaining>0 else""
    
    user=await bot.get_entity(uid)
    first_name=user.first_name or 'User'
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃  🎯 TELEGRAM REPORTER 🎯┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

👤 {first_name}
{'🌟 ADMIN' if is_admin(uid) else '✅ Active'}

📊 Statistics:
  ├ Sessions: {session_count}
  ├ Reports: {total}
  ├ Success: ✅ {success}
  └ Failed: ❌ {failed}{limit_text}

🚀 Ready to report!"""
    
    buttons=[
        [Button.inline("🎯 Report","report_main")],
        [Button.inline("📱 Sessions","menu_sessions"),Button.inline("⚙️ Settings","menu_settings")],
        [Button.inline("📊 Stats","menu_stats"),Button.inline("🛠️ Tools","menu_tools")]
    ]
    
    if is_admin(uid):
        buttons.append([Button.inline("👑 Admin","admin_main")])
    
    await safe_edit_message(event,text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'report_main'))
async def report_main(event):
    uid=event.sender_id
    
    access,status=check_user_access(uid)
    if not access:
        await safe_edit_message(event,"❌ Access denied")
        return
    
    sessions=get_sessions(uid)
    if not sessions:
        await safe_edit_message(event,"❌ No sessions\n\nAdd sessions first",buttons=[[Button.inline("📱 Add Session","menu_sessions")],[Button.inline("« Back","menu_main")]])
        return
    
    can_report,remaining=check_daily_limit(uid)
    if not can_report:
        await safe_edit_message(event,"❌ Daily limit reached\n\nTry tomorrow",buttons=[[Button.inline("« Back","menu_main")]])
        return
    
    text="""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃    🎯 REPORT MENU 🎯   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Choose report type:"""
    
    buttons=[
        [Button.inline("👤 User/Bot","report_user")],
        [Button.inline("📢 Channel","report_channel")],
        [Button.inline("👥 Group","report_group")],
        [Button.inline("💬 Message","report_message")],
        [Button.inline("« Back","menu_main")]
    ]
    
    await safe_edit_message(event,text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'report_user'))
async def report_user_handler(event):
    uid=event.sender_id
    
    text="""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃   👤 REPORT USER 👤    ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Send username or ID:
  • @username
  • User ID
  • t.me/username"""
    
    set_state(uid,'awaiting_user_target')
    await safe_edit_message(event,text,buttons=[[Button.inline("« Cancel","report_main")]])

@bot.on(events.CallbackQuery(pattern=b'report_channel'))
async def report_channel_handler(event):
    uid=event.sender_id
    
    text="""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃  📢 REPORT CHANNEL 📢  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Send channel link:
  • @channelname
  • t.me/channelname
  • t.me/joinchat/xxx"""
    
    set_state(uid,'awaiting_channel_target')
    await safe_edit_message(event,text,buttons=[[Button.inline("« Cancel","report_main")]])

@bot.on(events.CallbackQuery(pattern=b'report_group'))
async def report_group_handler(event):
    uid=event.sender_id
    
    text="""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃   👥 REPORT GROUP 👥   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Send group link:
  • @groupname
  • t.me/groupname
  • t.me/joinchat/xxx"""
    
    set_state(uid,'awaiting_group_target')
    await safe_edit_message(event,text,buttons=[[Button.inline("« Cancel","report_main")]])

@bot.on(events.CallbackQuery(pattern=b'report_message'))
async def report_message_handler(event):
    uid=event.sender_id
    
    text="""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃  💬 REPORT MESSAGE 💬  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Forward the message to report
Or send message link:
  • t.me/username/123"""
    
    set_state(uid,'awaiting_message_target')
    await safe_edit_message(event,text,buttons=[[Button.inline("« Cancel","report_main")]])

@bot.on(events.NewMessage(func=lambda e:e.is_private and not e.via_bot_id))
async def message_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    
    if not state:
        return
    
    access,status=check_user_access(uid)
    if not access:
        return
    
    current_state=state.get('state')
    
    # Handle target input
    if current_state in ['awaiting_user_target','awaiting_channel_target','awaiting_group_target']:
        target=event.text.strip()
        target_type={'awaiting_user_target':'user','awaiting_channel_target':'channel','awaiting_group_target':'group'}[current_state]
        
        set_state(uid,'awaiting_reason',{'target':target,'target_type':target_type})
        
        # Show all report reasons
        text="""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃   📋 SELECT REASON 📋  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Choose report reason:"""
        
        buttons=[]
        for key,val in REASONS.items():
            buttons.append([Button.inline(val[0],f"reason_{key}")])
        buttons.append([Button.inline("« Cancel","report_main")])
        
        await event.respond(text,buttons=buttons)
    
    elif current_state=='awaiting_message_target':
        # Handle forwarded message or message link
        if event.fwd_from:
            # Forwarded message
            try:
                msg_link=f"t.me/c/{event.fwd_from.from_id.channel_id}/{event.fwd_from.channel_post}"
                set_state(uid,'awaiting_reason',{'target':msg_link,'target_type':'message','msg_id':event.fwd_from.channel_post})
            except:
                await event.respond("❌ Invalid forwarded message")
                return
        else:
            # Message link
            msg_link=event.text.strip()
            if 't.me/' not in msg_link:
                await event.respond("❌ Send valid message link or forward message")
                return
            
            try:
                msg_id=int(msg_link.split('/')[-1])
                set_state(uid,'awaiting_reason',{'target':msg_link,'target_type':'message','msg_id':msg_id})
            except:
                await event.respond("❌ Invalid message link")
                return
        
        # Show all report reasons
        text="""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃   📋 SELECT REASON 📋  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Choose report reason:"""
        
        buttons=[]
        for key,val in REASONS.items():
            buttons.append([Button.inline(val[0],f"reason_{key}")])
        buttons.append([Button.inline("« Cancel","report_main")])
        
        await event.respond(text,buttons=buttons)
    
    elif current_state=='awaiting_comment':
        comment=event.text.strip()
        state_data=get_state(uid)
        
        if not state_data:
            return
        
        target=state_data.get('target')
        reason_key=state_data.get('reason_key')
        target_type=state_data.get('target_type')
        msg_id=state_data.get('msg_id')
        
        # Start reporting
        clear_state(uid)
        await start_reporting(event,target,reason_key,target_type,msg_id,comment)

@bot.on(events.CallbackQuery(pattern=rb'reason_(\d+)'))
async def reason_selected(event):
    uid=event.sender_id
    reason_key=event.data.decode().split('_')[1]
    
    state=get_state(uid)
    if not state:
        await safe_edit_message(event,"❌ Session expired")
        return
    
    target=state.get('target')
    target_type=state.get('target_type')
    msg_id=state.get('msg_id')
    
    # Ask for optional comment
    set_state(uid,'awaiting_comment',{
        'target':target,
        'reason_key':reason_key,
        'target_type':target_type,
        'msg_id':msg_id
    })
    
    reason_name=REASONS[reason_key][0]
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃  💬 ADD COMMENT? 💬   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Reason: {reason_name}

You can add a comment explaining why you're reporting (optional).

Send comment or skip:"""
    
    buttons=[
        [Button.inline("⏭️ Skip Comment","skip_comment")],
        [Button.inline("« Cancel","report_main")]
    ]
    
    await safe_edit_message(event,text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'skip_comment'))
async def skip_comment(event):
    uid=event.sender_id
    state=get_state(uid)
    
    if not state:
        await safe_edit_message(event,"❌ Session expired")
        return
    
    target=state.get('target')
    reason_key=state.get('reason_key')
    target_type=state.get('target_type')
    msg_id=state.get('msg_id')
    
    clear_state(uid)
    await start_reporting(event,target,reason_key,target_type,msg_id,None)

async def start_reporting(event,target,reason_key,target_type,msg_id=None,comment=None):
    uid=event.sender_id
    
    can_report,remaining=check_daily_limit(uid)
    if not can_report:
        await event.respond("❌ Daily limit reached",buttons=[[Button.inline("« Back","menu_main")]])
        return
    
    sessions=get_sessions(uid)
    if not sessions:
        await event.respond("❌ No sessions",buttons=[[Button.inline("« Back","menu_main")]])
        return
    
    reason_name,reason_obj=REASONS[reason_key]
    
    settings=db.fetchone('SELECT delay,auto_join,random_order FROM settings WHERE user_id=?',(uid,))
    delay,auto_join,random_order=(settings[0],settings[1],settings[2])if settings else(2,1,1)
    
    if random_order:
        random.shuffle(sessions)
    
    msg=await event.respond(f"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃   🚀 REPORTING... 🚀   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Target: {target}
Reason: {reason_name}
{'Comment: '+comment[:50] if comment else 'No comment'}
Sessions: {len(sessions)}

⏳ Starting...""")
    
    success_count=0
    failed_count=0
    
    for idx,session in enumerate(sessions,1):
        try:
            # Auto-join if needed
            if auto_join and target_type in ['channel','group']:
                try:
                    spath=os.path.join('sessions_db',session['session_file'])
                    temp_client=TelegramClient(spath.replace('.session',''),API_ID,API_HASH)
                    await temp_client.connect()
                    if await temp_client.is_user_authorized():
                        await auto_join_target(temp_client,target)
                    await temp_client.disconnect()
                    await asyncio.sleep(1)
                except:
                    pass
            
            # Report
            success,error=await report_with_session(session['session_file'],target,reason_obj,msg_id,comment)
            
            if success:
                success_count+=1
                db.execute('UPDATE sessions SET success_reports=success_reports+1,total_reports=total_reports+1,last_used=? WHERE id=?',(datetime.now().isoformat(),session['id']))
                db.execute('INSERT INTO reports(user_id,session_phone,target,target_type,reason,success,timestamp,comment)VALUES(?,?,?,?,?,?,?,?)',(uid,session['phone'],target,target_type,reason_name,1,datetime.now().isoformat(),comment))
            else:
                failed_count+=1
                db.execute('UPDATE sessions SET failed_reports=failed_reports+1,total_reports=total_reports+1,last_used=? WHERE id=?',(datetime.now().isoformat(),session['id']))
                db.execute('INSERT INTO reports(user_id,session_phone,target,target_type,reason,success,timestamp,error_msg,comment)VALUES(?,?,?,?,?,?,?,?,?)',(uid,session['phone'],target,target_type,reason_name,0,datetime.now().isoformat(),error,comment))
            
            # Update progress
            if idx%3==0 or idx==len(sessions):
                try:
                    await msg.edit(f"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃   🚀 REPORTING... 🚀   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Progress: {idx}/{len(sessions)}
Success: ✅ {success_count}
Failed: ❌ {failed_count}

⏳ Please wait...""")
                except MessageNotModifiedError:
                    pass
            
            await asyncio.sleep(delay)
            
        except Exception as e:
            logger.error(f"Report error: {e}")
            failed_count+=1
    
    # Update statistics
    db.execute('UPDATE statistics SET total_reports=total_reports+?,successful_reports=successful_reports+?,failed_reports=failed_reports+?,last_report_date=? WHERE user_id=?',(success_count+failed_count,success_count,failed_count,datetime.now().isoformat(),uid))
    increment_daily_usage(uid,success_count+failed_count)
    
    result_text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃   ✅ COMPLETE! ✅      ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

📊 Results:
  ├ Total: {len(sessions)}
  ├ Success: ✅ {success_count}
  └ Failed: ❌ {failed_count}

🎯 Target: {target}
📋 Reason: {reason_name}
{'💬 Comment: '+comment[:30]+'...' if comment and len(comment)>30 else '💬 Comment: '+comment if comment else ''}"""
    
    await msg.edit(result_text,buttons=[[Button.inline("🎯 Report Again","report_main")],[Button.inline("« Menu","menu_main")]])

@bot.on(events.CallbackQuery(pattern=b'menu_sessions'))
async def menu_sessions(event):
    uid=event.sender_id
    
    access,status=check_user_access(uid)
    if not access:
        await safe_edit_message(event,"❌ Access denied")
        return
    
    sessions=get_sessions(uid)
    user=db.fetchone('SELECT max_sessions FROM users WHERE user_id=?',(uid,))
    max_sessions=user[0]if user and user[0]>0 else'∞'
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃  📱 SESSION MANAGER 📱 ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Sessions: {len(sessions)}/{max_sessions}

{'📱 Sessions:' if sessions else '❌ No sessions'}"""
    
    if sessions:
        for s in sessions[:10]:
            text+=f"\n\n{s['phone']}\n👤 {s['name']}\n✅ {s['success_reports']} ❌ {s['failed_reports']}"
    
    buttons=[]
    if sessions:
        buttons.append([Button.inline("🗑️ Remove","session_remove")])
    buttons.append([Button.inline("📤 Export","session_export")])
    buttons.append([Button.inline("« Back","menu_main")])
    
    await safe_edit_message(event,text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'session_remove'))
async def session_remove_menu(event):
    uid=event.sender_id
    sessions=get_sessions(uid)
    
    if not sessions:
        await safe_edit_message(event,"❌ No sessions",buttons=[[Button.inline("« Back","menu_sessions")]])
        return
    
    text="""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃  🗑️ REMOVE SESSION 🗑️  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Select session to remove:"""
    
    buttons=[]
    for s in sessions[:20]:
        buttons.append([Button.inline(f"❌ {s['phone']}",f"delete_{s['id']}")])
    buttons.append([Button.inline("« Back","menu_sessions")])
    
    await safe_edit_message(event,text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'delete_(\d+)'))
async def delete_session(event):
    uid=event.sender_id
    session_id=int(event.data.decode().split('_')[1])
    
    if remove_session(uid,session_id):
        await safe_edit_message(event,"✅ Session removed",buttons=[[Button.inline("« Back","menu_sessions")]])
    else:
        await safe_edit_message(event,"❌ Error",buttons=[[Button.inline("« Back","menu_sessions")]])

@bot.on(events.CallbackQuery(pattern=b'session_export'))
async def session_export(event):
    uid=event.sender_id
    sessions=get_sessions(uid)
    
    if not sessions:
        await safe_edit_message(event,"❌ No sessions",buttons=[[Button.inline("« Back","menu_sessions")]])
        return
    
    msg=await event.respond("📦 Creating export...")
    
    try:
        timestamp=datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_name=f"sessions_{uid}_{timestamp}.zip"
        zip_path=os.path.join('exports',zip_name)
        
        with zipfile.ZipFile(zip_path,'w')as zf:
            for s in sessions:
                spath=os.path.join('sessions_db',s['session_file'])
                if os.path.exists(spath):
                    zf.write(spath,s['session_file'])
        
        await bot.send_file(uid,zip_path,caption=f"📦 Your sessions ({len(sessions)} files)")
        await msg.delete()
        
        try:
            os.remove(zip_path)
        except:pass
        
    except Exception as e:
        await msg.edit(f"❌ Export error: {str(e)[:80]}",buttons=[[Button.inline("« Back","menu_sessions")]])

@bot.on(events.CallbackQuery(pattern=b'menu_settings'))
async def menu_settings(event):
    uid=event.sender_id
    
    access,status=check_user_access(uid)
    if not access:
        await safe_edit_message(event,"❌ Access denied")
        return
    
    settings=db.fetchone('SELECT delay,report_limit,auto_join,random_order,retry_failed FROM settings WHERE user_id=?',(uid,))
    delay,limit,auto_join,random_order,retry=(settings[0],settings[1],settings[2],settings[3],settings[4])if settings else(2,50,1,1,0)
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃    ⚙️ SETTINGS ⚙️      ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Current Settings:
  ├ Delay: {delay}s
  ├ Limit: {limit}
  ├ Auto Join: {'✅' if auto_join else '❌'}
  ├ Random: {'✅' if random_order else '❌'}
  └ Retry: {'✅' if retry else '❌'}"""
    
    buttons=[
        [Button.inline("⏱️ Delay","set_delay"),Button.inline("📊 Limit","set_limit")],
        [Button.inline(f"{'✅' if auto_join else '❌'} Auto Join","toggle_join")],
        [Button.inline(f"{'✅' if random_order else '❌'} Random","toggle_random")],
        [Button.inline("« Back","menu_main")]
    ]
    
    await safe_edit_message(event,text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'set_delay'))
async def set_delay_handler(event):
    uid=event.sender_id
    
    text="""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃   ⏱️ SET DELAY ⏱️      ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Send delay in seconds (1-10):"""
    
    set_state(uid,'setting_delay')
    await safe_edit_message(event,text,buttons=[[Button.inline("« Cancel","menu_settings")]])

@bot.on(events.CallbackQuery(pattern=b'set_limit'))
async def set_limit_handler(event):
    uid=event.sender_id
    
    text="""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃   📊 SET LIMIT 📊      ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Send report limit (1-1000):"""
    
    set_state(uid,'setting_limit')
    await safe_edit_message(event,text,buttons=[[Button.inline("« Cancel","menu_settings")]])

@bot.on(events.CallbackQuery(pattern=b'toggle_join'))
async def toggle_join(event):
    uid=event.sender_id
    settings=db.fetchone('SELECT auto_join FROM settings WHERE user_id=?',(uid,))
    current=settings[0]if settings else 1
    new_val=0 if current else 1
    
    db.execute('UPDATE settings SET auto_join=? WHERE user_id=?',(new_val,uid))
    await menu_settings(event)

@bot.on(events.CallbackQuery(pattern=b'toggle_random'))
async def toggle_random(event):
    uid=event.sender_id
    settings=db.fetchone('SELECT random_order FROM settings WHERE user_id=?',(uid,))
    current=settings[0]if settings else 1
    new_val=0 if current else 1
    
    db.execute('UPDATE settings SET random_order=? WHERE user_id=?',(new_val,uid))
    await menu_settings(event)

@bot.on(events.CallbackQuery(pattern=b'menu_stats'))
async def menu_stats(event):
    uid=event.sender_id
    
    access,status=check_user_access(uid)
    if not access:
        await safe_edit_message(event,"❌ Access denied")
        return
    
    stats=db.fetchone('SELECT total_sessions,total_reports,successful_reports,failed_reports,last_report_date FROM statistics WHERE user_id=?',(uid,))
    sessions_count,total,success,failed,last_date=(stats[0],stats[1],stats[2],stats[3],stats[4])if stats else(0,0,0,0,'Never')
    
    success_rate=round((success/total*100))if total>0 else 0
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃   📊 STATISTICS 📊     ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

📱 Sessions: {sessions_count}
📊 Total Reports: {total}
✅ Successful: {success} ({success_rate}%)
❌ Failed: {failed}

🕐 Last Report: {last_date[:16] if last_date!='Never' else 'Never'}"""
    
    buttons=[[Button.inline("📊 Detailed","stats_detailed")],[Button.inline("« Back","menu_main")]]
    
    await safe_edit_message(event,text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'stats_detailed'))
async def stats_detailed(event):
    uid=event.sender_id
    
    recent=db.fetchall('SELECT target,reason,success,timestamp FROM reports WHERE user_id=? ORDER BY timestamp DESC LIMIT 10',(uid,))
    
    text="""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃  📊 RECENT REPORTS 📊  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Last 10 reports:"""
    
    if recent:
        for r in recent:
            status_icon='✅'if r[2]else'❌'
            target_short=r[0][:20]+'...'if len(r[0])>20 else r[0]
            text+=f"\n\n{status_icon} {target_short}\n{r[1]} | {r[3][:16]}"
    else:
        text+="\n\n❌ No reports yet"
    
    await safe_edit_message(event,text,buttons=[[Button.inline("« Back","menu_stats")]])

@bot.on(events.CallbackQuery(pattern=b'menu_tools'))
async def menu_tools(event):
    uid=event.sender_id
    
    access,status=check_user_access(uid)
    if not access:
        await safe_edit_message(event,"❌ Access denied")
        return
    
    text="""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃    🛠️ TOOLS 🛠️         ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Available tools:"""
    
    buttons=[
        [Button.inline("🧹 Clean Cache","tools_clean")],
        [Button.inline("📤 Backup Data","tools_backup")],
        [Button.inline("« Back","menu_main")]
    ]
    
    await safe_edit_message(event,text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'tools_clean'))
async def tools_clean(event):
    uid=event.sender_id
    
    try:
        db.execute('DELETE FROM targets_cache')
        db.execute('DELETE FROM flood_wait WHERE datetime(wait_until)<datetime("now")')
        
        await safe_edit_message(event,"✅ Cache cleaned",buttons=[[Button.inline("« Back","menu_tools")]])
    except Exception as e:
        await safe_edit_message(event,f"❌ Error: {str(e)[:50]}",buttons=[[Button.inline("« Back","menu_tools")]])

@bot.on(events.CallbackQuery(pattern=b'tools_backup'))
async def tools_backup(event):
    uid=event.sender_id
    
    msg=await event.respond("📦 Creating backup...")
    
    try:
        timestamp=datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name=f"backup_{uid}_{timestamp}.zip"
        backup_path=os.path.join('backups',backup_name)
        
        with zipfile.ZipFile(backup_path,'w')as zf:
            sessions=get_sessions(uid)
            for s in sessions:
                spath=os.path.join('sessions_db',s['session_file'])
                if os.path.exists(spath):
                    zf.write(spath,s['session_file'])
            
            reports=db.fetchall('SELECT target,reason,success,timestamp FROM reports WHERE user_id=? ORDER BY timestamp DESC LIMIT 100',(uid,))
            report_data=json.dumps([{'target':r[0],'reason':r[1],'success':r[2],'time':r[3]}for r in reports],indent=2)
            zf.writestr('reports.json',report_data)
        
        await bot.send_file(uid,backup_path,caption="📦 Your backup\n\nIncludes:\n• Sessions\n• Recent reports")
        await msg.delete()
        
        try:
            os.remove(backup_path)
        except:pass
        
    except Exception as e:
        await msg.edit(f"❌ Backup error: {str(e)[:80]}",buttons=[[Button.inline("« Back","menu_tools")]])

@bot.on(events.CallbackQuery(pattern=b'admin_main'))
async def admin_main(event):
    uid=event.sender_id
    
    if not is_admin(uid):
        await safe_edit_message(event,"❌ Admin only")
        return
    
    total_users=db.fetchone('SELECT COUNT(*) FROM users')[0]
    approved_users=db.fetchone('SELECT COUNT(*) FROM users WHERE is_approved=1')[0]
    pending=db.fetchone('SELECT COUNT(*) FROM approval_requests WHERE status="pending"')[0]
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃   👑 ADMIN PANEL 👑    ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

📊 Overview:
  ├ Users: {total_users}
  ├ Approved: {approved_users}
  └ Pending: {pending}"""
    
    buttons=[
        [Button.inline("👥 Users","admin_users")],
        [Button.inline("⏳ Pending","admin_pending")],
        [Button.inline("📊 Stats","admin_stats")],
        [Button.inline("« Back","menu_main")]
    ]
    
    await safe_edit_message(event,text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'admin_users'))
async def admin_users(event):
    uid=event.sender_id
    
    if not is_admin(uid):
        await safe_edit_message(event,"❌ Admin only")
        return
    
    users=db.fetchall('SELECT user_id,username,first_name,is_approved,approval_type FROM users ORDER BY user_id DESC LIMIT 20')
    
    text="""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃   👥 USER LIST 👥      ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Recent users:"""
    
    buttons=[]
    for u in users:
        status='✅'if u[3]else'⏳'
        type_str=f"({u[4]})"if u[4]else""
        buttons.append([Button.inline(f"{status} {u[0]} {u[2]} {type_str}",f"user_{u[0]}")])
    
    buttons.append([Button.inline("« Back","admin_main")])
    
    await safe_edit_message(event,text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'user_(\d+)'))
async def admin_user_detail(event):
    uid=event.sender_id
    
    if not is_admin(uid):
        return
    
    user_id=int(event.data.decode().split('_')[1])
    user=db.fetchone('SELECT username,first_name,is_approved,is_banned,approval_type,max_sessions,max_reports_per_day FROM users WHERE user_id=?',(user_id,))
    
    if not user:
        await safe_edit_message(event,"❌ User not found")
        return
    
    stats=db.fetchone('SELECT total_sessions,total_reports,successful_reports FROM statistics WHERE user_id=?',(user_id,))
    sessions,reports,success=(stats[0],stats[1],stats[2])if stats else(0,0,0)
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃   👤 USER DETAILS 👤   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

ID: {user_id}
Name: {user[1]}
Username: @{user[0] or 'None'}

Status: {'✅ Approved' if user[2] else '⏳ Pending'}
{'🔴 BANNED' if user[3] else ''}
Type: {user[4] or 'None'}

Limits:
  ├ Sessions: {user[5] or '∞'}
  └ Daily: {user[6] or '∞'}

Stats:
  ├ Sessions: {sessions}
  ├ Reports: {reports}
  └ Success: {success}"""
    
    buttons=[
        [Button.inline("✅ Approve","approve_user"),Button.inline("❌ Ban","ban_user")],
        [Button.inline("⚙️ Set Limits","set_limits")],
        [Button.inline("« Back","admin_users")]
    ]
    
    await safe_edit_message(event,text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'admin_pending'))
async def admin_pending(event):
    uid=event.sender_id
    
    if not is_admin(uid):
        await safe_edit_message(event,"❌ Admin only")
        return
    
    pending=db.fetchall('SELECT user_id,username,first_name,requested_date FROM approval_requests WHERE status="pending" ORDER BY requested_date DESC LIMIT 20')
    
    text="""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃  ⏳ PENDING REQUESTS ⏳ ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Pending approvals:"""
    
    buttons=[]
    for p in pending:
        buttons.append([Button.inline(f"👤 {p[0]} - {p[2]}",f"approve_{p[0]}")])
    
    buttons.append([Button.inline("« Back","admin_main")])
    
    if not pending:
        text+="\n\n✅ No pending requests"
    
    await safe_edit_message(event,text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'approve_(\d+)'))
async def approve_request_handler(event):
    uid=event.sender_id
    
    if not is_admin(uid):
        return
    
    user_id=int(event.data.decode().split('_')[1])
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃  ✅ APPROVE USER ✅    ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

User ID: {user_id}

Choose approval type:"""
    
    buttons=[
        [Button.inline("🌟 Full Access",f"approve_full_{user_id}")],
        [Button.inline("⏰ Trial 3d",f"approve_trial3_{user_id}")],
        [Button.inline("⏰ Trial 5d",f"approve_trial5_{user_id}")],
        [Button.inline("⏰ Trial 7d",f"approve_trial7_{user_id}")],
        [Button.inline("❌ Reject",f"reject_{user_id}")],
        [Button.inline("« Cancel","admin_pending")]
    ]
    
    await safe_edit_message(event,text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'approve_full_(\d+)'))
async def approve_full(event):
    admin_uid=event.sender_id
    
    if not is_admin(admin_uid):
        return
    
    user_id=int(event.data.decode().split('_')[2])
    now=datetime.now().isoformat()
    
    db.execute('UPDATE users SET is_approved=1,approval_type="full",approved_by=?,approved_date=?,max_sessions=100,max_reports_per_day=10000 WHERE user_id=?',(admin_uid,now,user_id))
    db.execute('UPDATE approval_requests SET status="approved",reviewed_by=?,reviewed_date=? WHERE user_id=?',(admin_uid,now,user_id))
    
    try:
        await bot.send_message(user_id,"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃  ✅ ACCESS GRANTED! ✅  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Your account is now approved!
Full access activated.

🎯 You can now:
  ├ Add sessions
  ├ Report targets
  └ Use all features

Type /start to begin!""")
    except:pass
    
    await safe_edit_message(event,f"✅ User {user_id} approved (Full)",buttons=[[Button.inline("« Back","admin_pending")]])

@bot.on(events.CallbackQuery(pattern=rb'approve_trial(\d+)_(\d+)'))
async def approve_trial(event):
    admin_uid=event.sender_id
    
    if not is_admin(admin_uid):
        return
    
    parts=event.data.decode().split('_')
    days=int(parts[1].replace('trial',''))
    user_id=int(parts[2])
    
    now=datetime.now()
    expires=(now+timedelta(days=days)).isoformat()
    now_str=now.isoformat()
    
    db.execute('UPDATE users SET is_approved=1,approval_type=?,trial_expires=?,approved_by=?,approved_date=?,max_sessions=50,max_reports_per_day=500 WHERE user_id=?',(f'trial_{days}d',expires,admin_uid,now_str,user_id))
    db.execute('UPDATE approval_requests SET status="approved",reviewed_by=?,reviewed_date=? WHERE user_id=?',(admin_uid,now_str,user_id))
    
    try:
        await bot.send_message(user_id,f"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃  ⏰ TRIAL APPROVED! ⏰  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Your {days}-day trial is active!
Expires: {expires[:10]}

🎯 Trial includes:
  ├ 50 sessions max
  ├ 500 reports/day
  └ All features

Type /start to begin!""")
    except:pass
    
    await safe_edit_message(event,f"✅ User {user_id} approved ({days}d trial)",buttons=[[Button.inline("« Back","admin_pending")]])

@bot.on(events.CallbackQuery(pattern=rb'reject_(\d+)'))
async def reject_request(event):
    admin_uid=event.sender_id
    
    if not is_admin(admin_uid):
        return
    
    user_id=int(event.data.decode().split('_')[1])
    now=datetime.now().isoformat()
    
    db.execute('UPDATE approval_requests SET status="rejected",reviewed_by=?,reviewed_date=? WHERE user_id=?',(admin_uid,now,user_id))
    
    try:
        await bot.send_message(user_id,"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃   ❌ REQUEST DENIED ❌  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

Your request was not approved.
Contact admin for details.""")
    except:pass
    
    await safe_edit_message(event,f"❌ User {user_id} rejected",buttons=[[Button.inline("« Back","admin_pending")]])

@bot.on(events.CallbackQuery(pattern=b'admin_stats'))
async def admin_stats(event):
    uid=event.sender_id
    
    if not is_admin(uid):
        return
    
    total_users=db.fetchone('SELECT COUNT(*) FROM users')[0]
    total_sessions=db.fetchone('SELECT COUNT(*) FROM sessions WHERE is_active=1')[0]
    total_reports=db.fetchone('SELECT SUM(total_reports) FROM statistics')[0]or 0
    success_reports=db.fetchone('SELECT SUM(successful_reports) FROM statistics')[0]or 0
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃  📊 GLOBAL STATS 📊    ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

👥 Total Users: {total_users}
📱 Total Sessions: {total_sessions}
📊 Total Reports: {total_reports}
✅ Successful: {success_reports}

Success Rate: {round(success_reports/total_reports*100) if total_reports>0 else 0}%"""
    
    await safe_edit_message(event,text,buttons=[[Button.inline("« Back","admin_main")]])

@bot.on(events.NewMessage(func=lambda e:e.document and e.is_private))
async def file_handler(event):
    uid=event.sender_id
    
    access,status=check_user_access(uid)
    if not access:
        await event.respond("❌ Access denied")
        return
    
    doc=event.document
    fname=None
    for attr in doc.attributes:
        if hasattr(attr,'file_name'):
            fname=attr.file_name
            break
    
    if not fname:
        return
    
    if fname.endswith('.session'):
        msg=await event.respond("📥 Processing...")
        path=os.path.join('temp_files',fname)
        try:
            await event.download_media(file=path)
            ok,phone,name=await verify_session(path.replace('.session',''))
            if ok:
                sname=f"{uid}_{phone.replace('+','').replace(' ','')}"
                final=os.path.join('sessions_db',sname+'.session')
                shutil.move(path,final)
                
                added=add_session(uid,phone,name,sname+'.session')
                if added:
                    await msg.edit(f"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃   ✅ SESSION ADDED ✅  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

📱 {phone}
👤 {name}

🎯 Ready!""",buttons=[[Button.inline("📱 Sessions","menu_sessions")],[Button.inline("🎯 Report","report_main")]])
                else:
                    try:
                        os.remove(final)
                    except:pass
                    await msg.edit("❌ Session limit reached",buttons=[[Button.inline("« Back","menu_sessions")]])
            else:
                try:
                    os.remove(path)
                except:pass
                await msg.edit("❌ Invalid session",buttons=[[Button.inline("« Back","menu_sessions")]])
        except Exception as e:
            await msg.edit(f"❌ Error: {str(e)[:80]}",buttons=[[Button.inline("« Back","menu_sessions")]])
    
    elif fname.endswith('.zip'):
        msg=await event.respond("📦 Extracting...")
        zpath=os.path.join('temp_files',fname)
        try:
            await event.download_media(file=zpath)
            added,failed=0,0
            with zipfile.ZipFile(zpath,'r')as zf:
                session_files=[f for f in zf.namelist()if f.endswith('.session')]
                total=len(session_files)
                
                if total==0:
                    await msg.edit("❌ No sessions in ZIP",buttons=[[Button.inline("« Back","menu_sessions")]])
                    return
                
                await msg.edit(f"📦 Found {total}\n⏳ Verifying...")
                
                for idx,f in enumerate(session_files,1):
                    try:
                        zf.extract(f,'temp_files')
                        tpath=os.path.join('temp_files',f)
                        ok,phone,name=await verify_session(tpath.replace('.session',''))
                        if ok:
                            sname=f"{uid}_{phone.replace('+','').replace(' ','')}"
                            final=os.path.join('sessions_db',sname+'.session')
                            shutil.move(tpath,final)
                            if add_session(uid,phone,name,sname+'.session'):
                                added+=1
                            else:
                                failed+=1
                                try:
                                    os.remove(final)
                                except:pass
                        else:
                            failed+=1
                            try:
                                os.remove(tpath)
                            except:pass
                        
                        if idx%5==0 or idx==total:
                            try:
                                await msg.edit(f"📦 {idx}/{total}\n✅ {added} ❌ {failed}")
                            except MessageNotModifiedError:
                                pass
                    except Exception as e:
                        logger.error(f"Extract: {e}")
                        failed+=1
            
            await msg.edit(f"""┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃   📦 ZIP COMPLETE 📦  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━┛

📊 Results:
  ├ Total: {total}
  ├ Added: ✅ {added}
  └ Failed: ❌ {failed}

{'🎯 Ready!'if added>0 else''}""",buttons=[[Button.inline("📱 Sessions","menu_sessions")],[Button.inline("« Menu","menu_main")]])
        except Exception as e:
            await msg.edit(f"❌ ZIP Error: {str(e)[:80]}",buttons=[[Button.inline("« Back","menu_sessions")]])
        finally:
            try:
                os.remove(zpath)
            except:pass

# Handle setting states
@bot.on(events.NewMessage(func=lambda e:e.is_private and e.text and not e.text.startswith('/')))
async def settings_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    
    if not state:
        return
    
    current_state=state.get('state')
    
    if current_state=='setting_delay':
        try:
            delay=int(event.text)
            if 1<=delay<=10:
                db.execute('UPDATE settings SET delay=? WHERE user_id=?',(delay,uid))
                clear_state(uid)
                await event.respond(f"✅ Delay set to {delay}s",buttons=[[Button.inline("« Settings","menu_settings")]])
            else:
                await event.respond("❌ Enter 1-10")
        except:
            await event.respond("❌ Invalid number")
    
    elif current_state=='setting_limit':
        try:
            limit=int(event.text)
            if 1<=limit<=1000:
                db.execute('UPDATE settings SET report_limit=? WHERE user_id=?',(limit,uid))
                clear_state(uid)
                await event.respond(f"✅ Limit set to {limit}",buttons=[[Button.inline("« Settings","menu_settings")]])
            else:
                await event.respond("❌ Enter 1-1000")
        except:
            await event.respond("❌ Invalid number")

def main():
    print("""
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                           ┃
┃   🎯 TELEGRAM REPORTER PROFESSIONAL 🎯  ┃
┃         Advanced Edition v3.0             ┃
┃                                           ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

✨ Features:
  ├ 🔐 Admin Approval System
  ├ ⏰ Trial Periods (3/5/7 days)
  ├ 📊 Daily Limits
  ├ 📱 Session Management
  ├ 🎯 Multi-Target Reporting
  ├ 💬 Optional Comments
  ├ 📋 16 Report Types
  ├ 🛡️ Flood Protection
  ├ 📈 Statistics
  └ 🚀 Fast & Reliable

🔥 Status:
  ├ Database: ✅ Connected
  ├ Bot: ✅ Online
  └ Admin: ✅ Ready

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📱 Press Ctrl+C to stop
💡 All features operational
""")
    
    try:
        logger.info("Bot started")
        bot.run_until_disconnected()
    except KeyboardInterrupt:
        print("\n\n⚠️  Stopping...")
        logger.info("Bot stopped")
    except Exception as e:
        print(f"\n\n❌ Fatal: {e}")
        logger.exception("Fatal error")
    finally:
        try:
            db.conn.close()
            print("✅ Database closed")
        except:pass
        print("✅ Cleanup complete\n")

if __name__=="__main__":
    main()
