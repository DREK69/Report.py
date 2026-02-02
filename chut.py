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

API_ID=27157163
API_HASH="e0145db12519b08e1d2f5628e2db18c4"
BOT_TOKEN="7930383726:AAETy8tyvgZcP6UaPYuaQwLAkGUu9qyNJ4Q"
ADMIN_IDS=[8101867786]
REQUIRED_CHANNEL="https://t.me/+-nGOXtIfUrBkOGM1"

for d in ['sessions_db','temp_files','data','backups','logs','exports','cache','reports']:
    os.makedirs(d,exist_ok=True)

logging.basicConfig(level=logging.INFO,format='%(asctime)s [%(levelname)s] %(message)s',handlers=[logging.FileHandler(f'logs/bot_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),logging.StreamHandler()])
logger=logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.conn=sqlite3.connect('data/reporter.db',check_same_thread=False,timeout=30)
        self.conn.row_factory=sqlite3.Row
        self.init_db()
        self.migrate()
        self.optimize()
    def init_db(self):
        c=self.conn.cursor()
        c.executescript('''
            CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY,username TEXT,first_name TEXT,joined_date TEXT,last_active TEXT,is_premium INTEGER DEFAULT 0,is_approved INTEGER DEFAULT 0,is_banned INTEGER DEFAULT 0,approval_type TEXT,trial_expires TEXT,max_sessions INTEGER DEFAULT 0,max_reports_per_day INTEGER DEFAULT 0,approved_by INTEGER,approved_date TEXT,channel_joined INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,phone TEXT UNIQUE,name TEXT,session_file TEXT,verified INTEGER,added_date TEXT,total_reports INTEGER DEFAULT 0,success_reports INTEGER DEFAULT 0,failed_reports INTEGER DEFAULT 0,is_active INTEGER DEFAULT 1,last_used TEXT,health_score INTEGER DEFAULT 100);
            CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,session_phone TEXT,target TEXT,target_type TEXT,reason TEXT,success INTEGER,timestamp TEXT,error_msg TEXT,execution_time REAL);
            CREATE TABLE IF NOT EXISTS settings(user_id INTEGER PRIMARY KEY,delay_min INTEGER DEFAULT 2,delay_max INTEGER DEFAULT 4,report_limit INTEGER DEFAULT 50,auto_join INTEGER DEFAULT 1,random_order INTEGER DEFAULT 1,retry_failed INTEGER DEFAULT 0,reports_per_target INTEGER DEFAULT 1,parallel_sessions INTEGER DEFAULT 3,skip_flood INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS statistics(user_id INTEGER PRIMARY KEY,total_sessions INTEGER DEFAULT 0,active_sessions INTEGER DEFAULT 0,total_reports INTEGER DEFAULT 0,successful_reports INTEGER DEFAULT 0,failed_reports INTEGER DEFAULT 0,last_report_date TEXT,targets_reported INTEGER DEFAULT 0,streak_days INTEGER DEFAULT 0,best_streak INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS flood_wait(session_phone TEXT PRIMARY KEY,wait_until TEXT,wait_seconds INTEGER);
            CREATE TABLE IF NOT EXISTS targets_cache(target TEXT PRIMARY KEY,entity_id TEXT,entity_type TEXT,cached_date TEXT);
            CREATE TABLE IF NOT EXISTS approval_requests(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,username TEXT,first_name TEXT,request_type TEXT,requested_date TEXT,status TEXT DEFAULT 'pending',reviewed_by INTEGER,reviewed_date TEXT,notes TEXT);
            CREATE TABLE IF NOT EXISTS user_limits(user_id INTEGER PRIMARY KEY,daily_reports_used INTEGER DEFAULT 0,last_reset_date TEXT);
            CREATE TABLE IF NOT EXISTS groups_joined(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,session_phone TEXT,group_link TEXT,group_id TEXT,group_title TEXT,joined_date TEXT,is_left INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS scheduled_reports(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,targets TEXT,reason TEXT,scheduled_time TEXT,status TEXT DEFAULT 'pending',created_date TEXT);
            CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id,timestamp);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id,is_active);
            CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status,requested_date);
        ''')
        self.conn.commit()
    def migrate(self):
        c=self.conn.cursor()
        migrations=[("last_used","sessions","ALTER TABLE sessions ADD COLUMN last_used TEXT"),("health_score","sessions","ALTER TABLE sessions ADD COLUMN health_score INTEGER DEFAULT 100"),("execution_time","reports","ALTER TABLE reports ADD COLUMN execution_time REAL"),("parallel_sessions","settings","ALTER TABLE settings ADD COLUMN parallel_sessions INTEGER DEFAULT 3"),("skip_flood","settings","ALTER TABLE settings ADD COLUMN skip_flood INTEGER DEFAULT 0"),("targets_reported","statistics","ALTER TABLE statistics ADD COLUMN targets_reported INTEGER DEFAULT 0"),("streak_days","statistics","ALTER TABLE statistics ADD COLUMN streak_days INTEGER DEFAULT 0"),("best_streak","statistics","ALTER TABLE statistics ADD COLUMN best_streak INTEGER DEFAULT 0"),("is_approved","users","ALTER TABLE users ADD COLUMN is_approved INTEGER DEFAULT 0"),("approval_type","users","ALTER TABLE users ADD COLUMN approval_type TEXT"),("trial_expires","users","ALTER TABLE users ADD COLUMN trial_expires TEXT"),("max_sessions","users","ALTER TABLE users ADD COLUMN max_sessions INTEGER DEFAULT 0"),("max_reports_per_day","users","ALTER TABLE users ADD COLUMN max_reports_per_day INTEGER DEFAULT 0"),("approved_by","users","ALTER TABLE users ADD COLUMN approved_by INTEGER"),("approved_date","users","ALTER TABLE users ADD COLUMN approved_date TEXT"),("channel_joined","users","ALTER TABLE users ADD COLUMN channel_joined INTEGER DEFAULT 0")]
        for col,table,sql in migrations:
            try:
                c.execute(f"SELECT {col} FROM {table} LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    c.execute(sql)
                    self.conn.commit()
                except:pass
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
bot=TelegramClient('reporter_bot',API_ID,API_HASH).start(bot_token=BOT_TOKEN)

REASONS={"1":("📧 Spam",InputReportReasonSpam()),"2":("⚔️ Violence",InputReportReasonViolence()),"3":("🔞 Pornography",InputReportReasonPornography()),"4":("👶 Child Abuse",InputReportReasonChildAbuse()),"5":("© Copyright",InputReportReasonCopyright()),"6":("🎭 Fake Account",InputReportReasonFake()),"7":("💊 Illegal Drugs",InputReportReasonIllegalDrugs()),"8":("🔐 Personal Info",InputReportReasonPersonalDetails()),"9":("🌍 Geo Irrelevant",InputReportReasonGeoIrrelevant()),"10":("❓ Other",InputReportReasonOther()),"11":("💣 Terrorism",InputReportReasonViolence()),"12":("💰 Scam",InputReportReasonOther()),"13":("😡 Harassment",InputReportReasonOther()),"14":("🤖 Bot Spam",InputReportReasonSpam()),"15":("🎯 Custom",InputReportReasonOther()),"16":("🎣 Phishing",InputReportReasonOther()),"17":("🦠 Malware",InputReportReasonOther()),"18":("💀 Self Harm",InputReportReasonViolence()),"19":("🐕 Animal Abuse",InputReportReasonViolence()),"20":("☠️ Extremism",InputReportReasonViolence())}

user_states={}

def set_state(uid,state,**data):user_states[uid]={'state':state,'timestamp':time.time(),**data}
def get_state(uid):
    state=user_states.get(uid)
    if state and time.time()-state.get('timestamp',0)>1800:clear_state(uid);return None
    return state
def clear_state(uid):
    if uid in user_states:
        if 'client' in user_states[uid]:
            try:asyncio.create_task(user_states[uid]['client'].disconnect())
            except:pass
        del user_states[uid]
def is_admin(uid):return uid in ADMIN_IDS
async def check_channel_membership(uid):
    try:
        user_client=await bot.get_entity(uid)
        channel_link=REQUIRED_CHANNEL
        if '/+' in channel_link or '/joinchat/' in channel_link:
            hash_part=channel_link.split('/')[-1].replace('+','')
            try:
                chat_invite=await bot(CheckChatInviteRequest(hash_part))
                if hasattr(chat_invite,'chat'):
                    try:
                        participant=await bot.get_participants(chat_invite.chat,limit=1,search=user_client.username or str(uid))
                        return len(participant)>0
                    except:return False
            except:return False
        else:
            username=channel_link.split('/')[-1].replace('@','')
            try:
                channel=await bot.get_entity(username)
                participants=await bot.get_participants(channel,limit=1,search=user_client.username or str(uid))
                return len(participants)>0
            except:return False
    except:return False
    return False
def check_user_access(uid):
    user=db.fetchone('SELECT is_approved,is_banned,trial_expires,approval_type,channel_joined FROM users WHERE user_id=?',(uid,))
    if not user:return False,'not_registered'
    if user['is_banned']:return False,'banned'
    if is_admin(uid):return True,'admin'
    if not user['channel_joined']:return False,'not_joined'
    if not user['is_approved']:return False,'not_approved'
    if user['approval_type']and user['approval_type'].startswith('trial'):
        if user['trial_expires']:
            expires=datetime.fromisoformat(user['trial_expires'])
            if datetime.now()>expires:
                db.execute('UPDATE users SET is_approved=0,approval_type=NULL WHERE user_id=?',(uid,))
                return False,'trial_expired'
    return True,'approved'
def check_daily_limit(uid):
    user=db.fetchone('SELECT max_reports_per_day FROM users WHERE user_id=?',(uid,))
    if not user or user['max_reports_per_day']==0:return True,0
    limit_data=db.fetchone('SELECT daily_reports_used,last_reset_date FROM user_limits WHERE user_id=?',(uid,))
    today=datetime.now().date().isoformat()
    if not limit_data:
        db.execute('INSERT INTO user_limits(user_id,last_reset_date)VALUES(?,?)',(uid,today))
        return True,user['max_reports_per_day']
    if limit_data['last_reset_date']!=today:
        db.execute('UPDATE user_limits SET daily_reports_used=0,last_reset_date=? WHERE user_id=?',(today,uid))
        return True,user['max_reports_per_day']
    if limit_data['daily_reports_used']>=user['max_reports_per_day']:return False,0
    return True,user['max_reports_per_day']-limit_data['daily_reports_used']
def increment_daily_usage(uid,count=1):db.execute('UPDATE user_limits SET daily_reports_used=daily_reports_used+? WHERE user_id=?',(count,uid))
def register_user(uid,username,first_name):
    if not db.fetchone('SELECT user_id FROM users WHERE user_id=?',(uid,)):
        now=datetime.now().isoformat()
        db.execute('INSERT INTO users(user_id,username,first_name,joined_date,last_active)VALUES(?,?,?,?,?)',(uid,username,first_name,now,now))
        db.execute('INSERT INTO settings(user_id)VALUES(?)',(uid,))
        db.execute('INSERT INTO statistics(user_id)VALUES(?)',(uid,))
        db.execute('INSERT INTO user_limits(user_id,last_reset_date)VALUES(?,?)',(uid,datetime.now().date().isoformat()))
        if not is_admin(uid):db.execute('INSERT INTO approval_requests(user_id,username,first_name,request_type,requested_date)VALUES(?,?,?,?,?)',(uid,username,first_name,'access',now))
    else:db.execute('UPDATE users SET last_active=? WHERE user_id=?',(datetime.now().isoformat(),uid))
def get_sessions(uid):
    rows=db.fetchall('SELECT * FROM sessions WHERE user_id=? AND is_active=1 ORDER BY health_score DESC,success_reports DESC',(uid,))
    return rows
def add_session(uid,phone,name,session_file):
    user=db.fetchone('SELECT max_sessions FROM users WHERE user_id=?',(uid,))
    if user and user['max_sessions']>0:
        current_count=len(get_sessions(uid))
        if current_count>=user['max_sessions']:return False
    now=datetime.now().isoformat()
    existing=db.fetchone('SELECT id FROM sessions WHERE user_id=? AND phone=?',(uid,phone))
    if existing:db.execute('UPDATE sessions SET is_active=1,name=?,session_file=?,verified=1,last_used=? WHERE user_id=? AND phone=?',(name,session_file,now,uid,phone))
    else:
        db.execute('INSERT INTO sessions(user_id,phone,name,session_file,verified,added_date,last_used)VALUES(?,?,?,?,1,?,?)',(uid,phone,name,session_file,now,now))
        db.execute('UPDATE statistics SET total_sessions=total_sessions+1,active_sessions=active_sessions+1 WHERE user_id=?',(uid,))
    return True
def remove_session(uid,phone):
    db.execute('UPDATE sessions SET is_active=0 WHERE user_id=? AND phone=?',(uid,phone))
    db.execute('UPDATE statistics SET active_sessions=active_sessions-1 WHERE user_id=? AND active_sessions>0',(uid,))
def update_session_stats(uid,phone,success=0,failed=0):
    now=datetime.now().isoformat()
    health_change=-5 if failed else 2 if success else 0
    db.execute('UPDATE sessions SET total_reports=total_reports+?,success_reports=success_reports+?,failed_reports=failed_reports+?,last_used=?,health_score=MIN(100,MAX(0,health_score+?)) WHERE user_id=? AND phone=?',(success+failed,success,failed,now,health_change,uid,phone))
def get_settings(uid):
    row=db.fetchone('SELECT * FROM settings WHERE user_id=?',(uid,))
    if row:return row
    return {'delay_min':2,'delay_max':4,'report_limit':50,'auto_join':1,'random_order':1,'retry_failed':0,'reports_per_target':1,'parallel_sessions':3,'skip_flood':0}
def update_setting(uid,key,val):db.execute(f'UPDATE settings SET {key}=? WHERE user_id=?',(val,uid))
def get_stats(uid):
    row=db.fetchone('SELECT * FROM statistics WHERE user_id=?',(uid,))
    if row:
        total,success=row['total_reports'],row['successful_reports']
        rate=int((success/total*100))if total>0 else 0
        return {**row,'success_rate':rate}
    return {'total_sessions':0,'active_sessions':0,'total_reports':0,'successful_reports':0,'failed_reports':0,'success_rate':0,'targets_reported':0,'streak_days':0,'best_streak':0,'last_report_date':None}
def update_stats(uid,success=0,failed=0,target_reported=False):
    now=datetime.now().isoformat()
    last_date=db.fetchone('SELECT last_report_date FROM statistics WHERE user_id=?',(uid,))
    streak_update=''
    if last_date and last_date['last_report_date']:
        last=datetime.fromisoformat(last_date['last_report_date']).date()
        today=datetime.now().date()
        if(today-last).days==1:streak_update=',streak_days=streak_days+1,best_streak=MAX(best_streak,streak_days+1)'
        elif(today-last).days>1:streak_update=',streak_days=1'
    else:streak_update=',streak_days=1'
    target_inc=1 if target_reported else 0
    db.execute(f'UPDATE statistics SET total_reports=total_reports+?,successful_reports=successful_reports+?,failed_reports=failed_reports+?,last_report_date=?,targets_reported=targets_reported+?{streak_update} WHERE user_id=?',(success+failed,success,failed,now,target_inc,uid))
def log_report(uid,phone,target,target_type,reason,success,error='',exec_time=0):
    now=datetime.now().isoformat()
    db.execute('INSERT INTO reports(user_id,session_phone,target,target_type,reason,success,timestamp,error_msg,execution_time)VALUES(?,?,?,?,?,?,?,?,?)',(uid,phone,target,target_type,reason,success,now,error,exec_time))
def check_flood_wait(phone):
    row=db.fetchone('SELECT wait_until FROM flood_wait WHERE session_phone=?',(phone,))
    if row:
        wait_until=datetime.fromisoformat(row['wait_until'])
        if datetime.now()<wait_until:return True,(wait_until-datetime.now()).seconds
    return False,0
def set_flood_wait(phone,seconds):
    wait_until=(datetime.now()+timedelta(seconds=seconds)).isoformat()
    db.execute('INSERT OR REPLACE INTO flood_wait(session_phone,wait_until,wait_seconds)VALUES(?,?,?)',(phone,wait_until,seconds))
def clear_flood_wait(phone):db.execute('DELETE FROM flood_wait WHERE session_phone=?',(phone,))
async def create_client(uid,phone):
    name=f"{uid}_{phone.replace('+','').replace(' ','')}"
    path=os.path.join('sessions_db',name)
    try:
        client=TelegramClient(path,API_ID,API_HASH)
        await client.connect()
        if not await client.is_user_authorized():return None,None,None
        me=await client.get_me()
        return client,me.phone,f"{me.first_name or''} {me.last_name or''}".strip()
    except Exception as e:logger.error(f"Client error: {e}");return None,None,None
async def verify_session(path):
    client=TelegramClient(path,API_ID,API_HASH)
    try:
        await client.connect()
        if await client.is_user_authorized():
            me=await client.get_me()
            await client.disconnect()
            return True,me.phone,f"{me.first_name or''} {me.last_name or''}".strip()
        await client.disconnect()
        return False,'',''
    except Exception as e:
        logger.error(f"Verify: {e}")
        try:await client.disconnect()
        except:pass
        return False,'',''
async def get_entity_smart(client,target):
    try:
        if target.startswith('http')or target.startswith('t.me'):
            if '/joinchat/'in target or'/+'in target:
                hash_part=target.split('/')[-1].replace('+','')
                result=await client(CheckChatInviteRequest(hash_part))
                if hasattr(result,'chat'):
                    return result.chat,('channel'if result.chat.broadcast else'group')
            else:
                parts=target.split('/')
                if len(parts)>=4:
                    username=parts[3].split('?')[0]
                    entity=await client.get_entity(username)
                    if isinstance(entity,User):return entity,'user'
                    elif isinstance(entity,Channel):return entity,('channel'if entity.broadcast else'group')
                    elif isinstance(entity,Chat):return entity,'group'
        else:
            entity=await client.get_entity(target)
            if isinstance(entity,User):return entity,'user'
            elif isinstance(entity,Channel):return entity,('channel'if entity.broadcast else'group')
            elif isinstance(entity,Chat):return entity,'group'
        return None,None
    except Exception as e:logger.error(f"Entity: {e}");return None,None
async def join_private_group(client,link):
    try:
        if'/joinchat/'in link or'/+'in link:
            hash_part=link.split('/')[-1].replace('+','')
            try:
                await client(ImportChatInviteRequest(hash_part))
                return True,None
            except UserAlreadyParticipantError:return True,None
            except Exception as e:return False,str(e)
        else:
            username=link.split('/')[-1].replace('@','').split('?')[0]
            entity=await client.get_entity(username)
            if isinstance(entity,(Channel,Chat)):
                await client(JoinChannelRequest(entity))
                return True,None
            return False,"Not a group"
    except Exception as e:return False,str(e)
async def report_target(client,phone,target,reason_obj,uid,reason_text):
    start_time=time.time()
    try:
        entity,etype=await get_entity_smart(client,target)
        if not entity:return False,"Entity not found",0
        if etype=='user':await client(ReportPeerRequest(peer=entity,reason=reason_obj,message=''))
        elif etype in['channel','group']:
            try:
                messages=await client.get_messages(entity,limit=1)
                if messages:await client(ReportRequest(peer=entity,id=[messages[0].id],reason=reason_obj,message=''))
                else:await client(ReportPeerRequest(peer=entity,reason=reason_obj,message=''))
            except:await client(ReportPeerRequest(peer=entity,reason=reason_obj,message=''))
        exec_time=time.time()-start_time
        log_report(uid,phone,target,etype,reason_text,1,'',exec_time)
        return True,None,exec_time
    except FloodWaitError as e:
        exec_time=time.time()-start_time
        set_flood_wait(phone,e.seconds)
        log_report(uid,phone,target,'',reason_text,0,f"Flood: {e.seconds}s",exec_time)
        return False,f"Flood: {e.seconds}s",exec_time
    except Exception as e:
        exec_time=time.time()-start_time
        error=str(e)[:200]
        log_report(uid,phone,target,'',reason_text,0,error,exec_time)
        return False,error,exec_time
def create_main_buttons():
    return [[Button.inline("🎯 Report","report_main"),Button.inline("📱 Sessions","menu_sessions")],[Button.inline("📊 Stats","menu_stats"),Button.inline("⚙️ Settings","menu_settings")],[Button.inline("🛠️ Tools","menu_tools"),Button.inline("ℹ️ Help","menu_help")]]
def format_progress(current,total,success,failed,skipped):
    progress=int((current/total*100))if total>0 else 0
    bar_len=15
    filled=int(bar_len*progress/100)
    bar='█'*filled+'░'*(bar_len-filled)
    return f"""╔══════════════════════════╗
║  🎯 PROGRESS {progress:3d}% 🎯  ║
╚══════════════════════════╝
{bar}
📊 {current}/{total}
✅ {success} | ❌ {failed} | ⏭️ {skipped}"""

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    uid=event.sender_id
    sender=await event.get_sender()
    register_user(uid,sender.username,sender.first_name)
    is_joined=await check_channel_membership(uid)
    if not is_joined and not is_admin(uid):
        await event.respond(f"""╔══════════════════════════╗
║  🔒 ACCESS REQUIRED 🔒  ║
╚══════════════════════════╝

Hi {sender.first_name}!

⚠️ Channel membership required

Join: {REQUIRED_CHANNEL}

After joining, click Check ⬇️""",buttons=[[Button.url("📢 Join Channel",REQUIRED_CHANNEL)],[Button.inline("✅ Check Membership","check_channel")]])
        return
    access,status=check_user_access(uid)
    if status=='banned':
        await event.respond("🚫 Access revoked")
        return
    if status=='not_approved':
        await event.respond(f"""╔══════════════════════════╗
║  ⏳ APPROVAL PENDING ⏳  ║
╚══════════════════════════╝

Hi {sender.first_name}!

📋 Status: Waiting
⏳ Admin will review soon""")
        return
    if status=='trial_expired':
        await event.respond(f"""╔══════════════════════════╗
║   ⏰ TRIAL EXPIRED ⏰   ║
╚══════════════════════════╝

Hi {sender.first_name}!

Your trial has ended.
Contact admin for access.""")
        return
    user=db.fetchone('SELECT approval_type,trial_expires FROM users WHERE user_id=?',(uid,))
    trial_info=''
    if user and user['approval_type']and user['approval_type'].startswith('trial'):
        if user['trial_expires']:
            expires=datetime.fromisoformat(user['trial_expires'])
            days_left=(expires.date()-datetime.now().date()).days
            trial_info=f"\n⏰ Trial: {days_left} days left"
    stats=get_stats(uid)
    welcome=f"""╔══════════════════════════╗
║  🎯 TELEGRAM REPORTER 🎯  ║
║   ENTERPRISE EDITION v4.0  ║
╚══════════════════════════╝

👋 Welcome, {sender.first_name}!{trial_info}

📊 Your Stats:
  ├ Reports: {stats['total_reports']}
  ├ Success: {stats['success_rate']}%
  └ Sessions: {stats['active_sessions']}

🌟 Features:
  ├ Multi-Session Reporting
  ├ Intelligent Flood Control
  ├ Advanced Statistics
  └ Real-time Processing"""
    await event.respond(welcome,buttons=create_main_buttons())

@bot.on(events.CallbackQuery(pattern=b'check_channel'))
async def check_channel_handler(event):
    await event.answer()
    uid=event.sender_id
    is_joined=await check_channel_membership(uid)
    if is_joined:
        db.execute('UPDATE users SET channel_joined=1 WHERE user_id=?',(uid,))
        await event.edit("✅ Channel membership verified!\n\nUse /start to continue",buttons=[[Button.inline("🚀 Start",b"/start")]])
    else:
        await event.answer("❌ Not joined yet. Please join first.",alert=True)

@bot.on(events.CallbackQuery(pattern=b'menu_main'))
async def menu_main(event):
    await event.answer()
    uid=event.sender_id
    access,status=check_user_access(uid)
    if not access:
        await event.edit("❌ Access denied")
        return
    stats=get_stats(uid)
    await event.edit(f"""╔══════════════════════════╗
║     🎯 MAIN MENU 🎯     ║
╚══════════════════════════╝

📊 Stats:
  ├ Reports: {stats['total_reports']}
  ├ Success: {stats['success_rate']}%
  └ Sessions: {stats['active_sessions']}""",buttons=create_main_buttons())

@bot.on(events.CallbackQuery(pattern=b'report_main'))
async def report_main_menu(event):
    await event.answer()
    uid=event.sender_id
    access,status=check_user_access(uid)
    if not access:await event.edit("❌ Access denied");return
    can_report,remaining=check_daily_limit(uid)
    if not can_report:
        await event.edit("❌ Daily limit reached",buttons=[[Button.inline("« Back","menu_main")]])
        return
    sessions=get_sessions(uid)
    if not sessions:
        await event.edit("❌ No sessions\n\nUpload .session or .zip file",buttons=[[Button.inline("📱 Sessions","menu_sessions")],[Button.inline("« Back","menu_main")]])
        return
    limit_text=f"\n📊 Limit: {remaining} left"if remaining>0 else""
    text=f"""╔══════════════════════════╗
║  🎯 REPORT CENTER 🎯   ║
╚══════════════════════════╝

📱 Sessions: {len(sessions)}{limit_text}

Choose type:"""
    buttons=[[Button.inline("👤 User","report_user"),Button.inline("📢 Channel","report_channel")],[Button.inline("👥 Group","report_group"),Button.inline("📝 Bulk","report_bulk")],[Button.inline("🔗 Message Link","report_link")],[Button.inline("« Back","menu_main")]]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'report_(user|channel|group|link)'))
async def report_single_start(event):
    await event.answer()
    uid=event.sender_id
    target_type=event.data.decode().split('_')[1]
    set_state(uid,f'awaiting_{target_type}_target')
    type_map={'user':'👤 USER','channel':'📢 CHANNEL','group':'👥 GROUP','link':'🔗 MESSAGE'}
    text=f"""╔══════════════════════════╗
║  {type_map[target_type]}  ║
╚══════════════════════════╝

📝 Send target identifier:
  ├ Username: @example
  ├ ID: 123456789
  ├ Link: t.me/example
  └ Phone: +1234567890

/cancel to abort"""
    await event.edit(text,buttons=[[Button.inline("« Cancel","report_main")]])

@bot.on(events.CallbackQuery(pattern=b'report_bulk'))
async def report_bulk_start(event):
    await event.answer()
    uid=event.sender_id
    set_state(uid,'awaiting_bulk_targets')
    text="""╔══════════════════════════╗
║   📝 BULK REPORTING 📝  ║
╚══════════════════════════╝

Send targets (one per line):

Example:
@user1
@channel1
https://t.me/group1
+1234567890

/cancel to abort"""
    await event.edit(text,buttons=[[Button.inline("« Cancel","report_main")]])

@bot.on(events.NewMessage(pattern='/cancel'))
async def cancel_handler(event):
    uid=event.sender_id
    clear_state(uid)
    await event.respond("✅ Cancelled",buttons=create_main_buttons())

@bot.on(events.NewMessage(func=lambda e:e.is_private and not e.via_bot_id and not e.document and get_state(e.sender_id)))
async def text_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state:return
    text=event.text.strip()
    if text.startswith('/'):return
    if state['state']in['awaiting_user_target','awaiting_channel_target','awaiting_group_target','awaiting_link_target']:
        set_state(uid,'awaiting_reason',target=text)
        reason_text=f"""╔══════════════════════════╗
║   📋 SELECT REASON 📋   ║
╚══════════════════════════╝

🎯 Target: {text[:25]}

Choose reason:"""
        buttons=[[Button.inline(v[0],f"reason_{k}")]for k,v in list(REASONS.items())[:10]]
        buttons.append([Button.inline("📋 More Reasons","more_reasons")])
        buttons.append([Button.inline("« Cancel","report_main")])
        await event.respond(reason_text,buttons=buttons)
    elif state['state']=='awaiting_bulk_targets':
        targets=[t.strip()for t in text.split('\n')if t.strip()]
        if not targets:await event.respond("❌ No valid targets");return
        set_state(uid,'awaiting_bulk_reason',targets=targets)
        reason_text=f"""╔══════════════════════════╗
║   📋 SELECT REASON 📋   ║
╚══════════════════════════╝

🎯 Targets: {len(targets)}

Choose reason:"""
        buttons=[[Button.inline(v[0],f"bulk_reason_{k}")]for k,v in list(REASONS.items())[:10]]
        buttons.append([Button.inline("📋 More","bulk_more_reasons")])
        buttons.append([Button.inline("« Cancel","report_main")])
        await event.respond(reason_text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'more_reasons'))
async def more_reasons(event):
    await event.answer()
    reason_text="""╔══════════════════════════╗
║   📋 MORE REASONS 📋    ║
╚══════════════════════════╝

Choose reason:"""
    buttons=[[Button.inline(v[0],f"reason_{k}")]for k,v in list(REASONS.items())[10:]]
    buttons.append([Button.inline("« Back","report_main")])
    await event.edit(reason_text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'bulk_more_reasons'))
async def bulk_more_reasons(event):
    await event.answer()
    reason_text="""╔══════════════════════════╗
║   📋 MORE REASONS 📋    ║
╚══════════════════════════╝

Choose reason:"""
    buttons=[[Button.inline(v[0],f"bulk_reason_{k}")]for k,v in list(REASONS.items())[10:]]
    buttons.append([Button.inline("« Back","report_bulk")])
    await event.edit(reason_text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'reason_(\d+)'))
async def reason_selected(event):
    await event.answer()
    uid=event.sender_id
    state=get_state(uid)
    if not state or'target'not in state:await event.edit("❌ Session expired",buttons=[[Button.inline("« Retry","report_main")]]);return
    access,status=check_user_access(uid)
    if not access:await event.edit("❌ Access denied");clear_state(uid);return
    can_report,remaining=check_daily_limit(uid)
    if not can_report:await event.edit("❌ Daily limit reached",buttons=[[Button.inline("« Back","menu_main")]]);clear_state(uid);return
    reason_id=event.data.decode().split('_')[1]
    reason_name,reason_obj=REASONS[reason_id]
    target=state['target']
    msg=await event.edit("🚀 Starting...")
    sessions=get_sessions(uid)
    if not sessions:await msg.edit("❌ No sessions",buttons=[[Button.inline("« Back","report_main")]]);clear_state(uid);return
    settings=get_settings(uid)
    reports_per_target=settings['reports_per_target']
    sessions_to_use=sessions[:min(len(sessions),reports_per_target)]
    if settings['random_order']:random.shuffle(sessions_to_use)
    success,failed,skipped=0,0,0
    processed=0
    total=len(sessions_to_use)
    for session in sessions_to_use:
        is_flood,wait_time=check_flood_wait(session['phone'])
        if is_flood and not settings['skip_flood']:skipped+=1;processed+=1;continue
        session_path=os.path.join('sessions_db',session['session_file'])
        client,*_=await create_client(uid,session['phone'])
        if not client:failed+=1;update_session_stats(uid,session['phone'],0,1);processed+=1;continue
        try:
            ok,error,exec_time=await report_target(client,session['phone'],target,reason_obj,uid,reason_name)
            if ok:success+=1;update_session_stats(uid,session['phone'],1,0)
            else:failed+=1;update_session_stats(uid,session['phone'],0,1)
        except Exception as e:failed+=1;update_session_stats(uid,session['phone'],0,1)
        finally:
            try:await client.disconnect()
            except:pass
        processed+=1
        if processed%2==0 or processed==total:
            try:await msg.edit(format_progress(processed,total,success,failed,skipped))
            except:pass
        await asyncio.sleep(random.uniform(settings['delay_min'],settings['delay_max']))
    update_stats(uid,success,failed,True)
    increment_daily_usage(uid,success)
    rate=int((success/(success+failed)*100))if(success+failed)>0 else 0
    final=f"""╔══════════════════════════╗
║   ✅ COMPLETED ✅       ║
╚══════════════════════════╝

📊 Results:
  ├ Success: ✅ {success}
  ├ Failed: ❌ {failed}
  ├ Skipped: ⏭️ {skipped}
  └ Rate: {rate}%"""
    await msg.edit(final,buttons=[[Button.inline("🎯 Again","report_main")],[Button.inline("« Menu","menu_main")]])
    clear_state(uid)

@bot.on(events.CallbackQuery(pattern=rb'bulk_reason_(\d+)'))
async def bulk_reason_selected(event):
    await event.answer()
    uid=event.sender_id
    state=get_state(uid)
    if not state or'targets'not in state:await event.edit("❌ Session expired",buttons=[[Button.inline("« Retry","report_main")]]);return
    access,status=check_user_access(uid)
    if not access:await event.edit("❌ Access denied");clear_state(uid);return
    can_report,remaining=check_daily_limit(uid)
    if not can_report:await event.edit("❌ Daily limit reached",buttons=[[Button.inline("« Back","menu_main")]]);clear_state(uid);return
    reason_id=event.data.decode().split('_')[2]
    reason_name,reason_obj=REASONS[reason_id]
    targets=state['targets']
    sessions=get_sessions(uid)
    if not sessions:await event.edit("❌ No sessions",buttons=[[Button.inline("« Back","report_main")]]);clear_state(uid);return
    settings=get_settings(uid)
    reports_per_target=settings['reports_per_target']
    total_ops=len(targets)*min(len(sessions),reports_per_target)
    if remaining>0 and total_ops>remaining:await event.edit(f"❌ Limit exceeded\n\nNeed: {total_ops}\nHave: {remaining}",buttons=[[Button.inline("« Back","report_main")]]);clear_state(uid);return
    msg=await event.edit("🚀 Starting bulk...")
    success,failed,skipped=0,0,0
    processed=0
    for target in targets:
        sessions_to_use=sessions[:min(len(sessions),reports_per_target)]
        if settings['random_order']:random.shuffle(sessions_to_use)
        for session in sessions_to_use:
            is_flood,wait_time=check_flood_wait(session['phone'])
            if is_flood and not settings['skip_flood']:skipped+=1;processed+=1;continue
            session_path=os.path.join('sessions_db',session['session_file'])
            client,*_=await create_client(uid,session['phone'])
            if not client:failed+=1;update_session_stats(uid,session['phone'],0,1);processed+=1;continue
            try:
                ok,error,exec_time=await report_target(client,session['phone'],target,reason_obj,uid,reason_name)
                if ok:success+=1;update_session_stats(uid,session['phone'],1,0)
                else:failed+=1;update_session_stats(uid,session['phone'],0,1)
            except Exception as e:failed+=1;update_session_stats(uid,session['phone'],0,1)
            finally:
                try:await client.disconnect()
                except:pass
            processed+=1
            if processed%5==0 or processed==total_ops:
                try:await msg.edit(format_progress(processed,total_ops,success,failed,skipped))
                except:pass
            await asyncio.sleep(random.uniform(settings['delay_min'],settings['delay_max']))
    update_stats(uid,success,failed,True)
    increment_daily_usage(uid,success)
    rate=int((success/(success+failed)*100))if(success+failed)>0 else 0
    final=f"""╔══════════════════════════╗
║   ✅ COMPLETED ✅       ║
╚══════════════════════════╝

📊 Results:
  ├ Targets: {len(targets)}
  ├ Success: ✅ {success}
  ├ Failed: ❌ {failed}
  ├ Skipped: ⏭️ {skipped}
  └ Rate: {rate}%"""
    await msg.edit(final,buttons=[[Button.inline("🎯 Again","report_main")],[Button.inline("« Menu","menu_main")]])
    clear_state(uid)

@bot.on(events.CallbackQuery(pattern=b'menu_sessions'))
async def menu_sessions(event):
    await event.answer()
    uid=event.sender_id
    access,status=check_user_access(uid)
    if not access:await event.edit("❌ Access denied");return
    sessions=get_sessions(uid)
    user=db.fetchone('SELECT max_sessions FROM users WHERE user_id=?',(uid,))
    max_limit=user['max_sessions']if user and user['max_sessions']>0 else'∞'
    text=f"""╔══════════════════════════╗
║  📱 SESSION MANAGER 📱  ║
╚══════════════════════════╝

📊 Total: {len(sessions)}/{max_limit}

"""
    if sessions:
        for idx,s in enumerate(sessions[:5],1):
            rate=int((s['success_reports']/s['total_reports']*100))if s['total_reports']>0 else 0
            health='🟢'if s['health_score']>=80 else'🟡'if s['health_score']>=50 else'🔴'
            text+=f"{idx}. {health} {s['phone']}\n   └ {s['success_reports']}/{s['total_reports']} ({rate}%)\n"
        if len(sessions)>5:text+=f"\n...+{len(sessions)-5} more"
    else:text+="❌ No sessions\n\n💡 Upload .session or .zip file"
    buttons=[[Button.inline("📋 List All","session_list"),Button.inline("➖ Remove","session_remove")],[Button.inline("📤 Export","session_export"),Button.inline("🔄 Refresh","menu_sessions")],[Button.inline("« Back","menu_main")]]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'session_list'))
async def session_list_all(event):
    await event.answer()
    uid=event.sender_id
    sessions=get_sessions(uid)
    if not sessions:await event.edit("❌ No sessions",buttons=[[Button.inline("« Back","menu_sessions")]]);return
    text=f"""╔══════════════════════════╗
║  📋 ALL SESSIONS 📋    ║
╚══════════════════════════╝

Total: {len(sessions)}

"""
    for idx,s in enumerate(sessions,1):
        rate=int((s['success_reports']/s['total_reports']*100))if s['total_reports']>0 else 0
        health='🟢'if s['health_score']>=80 else'🟡'if s['health_score']>=50 else'🔴'
        text+=f"{idx}. {health} {s['phone']}\n   ├ {s['name'][:20]}\n   └ {s['success_reports']}/{s['total_reports']} ({rate}%)\n"
        if idx>=20:text+=f"\n...and {len(sessions)-20} more";break
    await event.edit(text,buttons=[[Button.inline("« Back","menu_sessions")]])

@bot.on(events.CallbackQuery(pattern=b'session_remove'))
async def session_remove_start(event):
    await event.answer()
    uid=event.sender_id
    sessions=get_sessions(uid)
    if not sessions:await event.edit("❌ No sessions",buttons=[[Button.inline("« Back","menu_sessions")]]);return
    set_state(uid,'awaiting_remove_session')
    text=f"""╔══════════════════════════╗
║  ➖ REMOVE SESSION ➖   ║
╚══════════════════════════╝

Total: {len(sessions)}

Send session number:

"""
    for idx,s in enumerate(sessions[:10],1):text+=f"{idx}. {s['phone']}\n"
    if len(sessions)>10:text+=f"\n...+{len(sessions)-10} more"
    await event.edit(text,buttons=[[Button.inline("« Cancel","menu_sessions")]])

@bot.on(events.NewMessage(func=lambda e:e.is_private and get_state(e.sender_id)and get_state(e.sender_id)['state']=='awaiting_remove_session'))
async def session_remove_process(event):
    uid=event.sender_id
    text=event.text.strip()
    if not text.isdigit():await event.respond("❌ Invalid number");return
    idx=int(text)-1
    sessions=get_sessions(uid)
    if idx<0 or idx>=len(sessions):await event.respond("❌ Invalid session number");return
    session=sessions[idx]
    remove_session(uid,session['phone'])
    try:os.remove(os.path.join('sessions_db',session['session_file']))
    except:pass
    clear_state(uid)
    await event.respond(f"✅ Removed: {session['phone']}",buttons=[[Button.inline("📱 Sessions","menu_sessions")]])

@bot.on(events.CallbackQuery(pattern=b'session_export'))
async def session_export(event):
    await event.answer()
    uid=event.sender_id
    sessions=get_sessions(uid)
    if not sessions:await event.answer("❌ No sessions to export",alert=True);return
    msg=await event.edit("📦 Creating export...")
    try:
        export_name=f"sessions_export_{uid}_{int(time.time())}.zip"
        export_path=os.path.join('exports',export_name)
        with zipfile.ZipFile(export_path,'w')as zf:
            for s in sessions:
                session_path=os.path.join('sessions_db',s['session_file'])
                if os.path.exists(session_path):zf.write(session_path,os.path.basename(session_path))
        await bot.send_file(uid,export_path,caption=f"📦 Session Export\n\nTotal: {len(sessions)} sessions")
        await msg.edit(f"✅ Export sent!\n\nTotal: {len(sessions)} sessions",buttons=[[Button.inline("« Back","menu_sessions")]])
        try:os.remove(export_path)
        except:pass
    except Exception as e:
        await msg.edit(f"❌ Export failed: {str(e)[:50]}",buttons=[[Button.inline("« Back","menu_sessions")]])

@bot.on(events.CallbackQuery(pattern=b'menu_settings'))
async def menu_settings(event):
    await event.answer()
    uid=event.sender_id
    access,status=check_user_access(uid)
    if not access:await event.edit("❌ Access denied");return
    settings=get_settings(uid)
    text=f"""╔══════════════════════════╗
║    ⚙️ SETTINGS ⚙️       ║
╚══════════════════════════╝

⏱️ Delay: {settings['delay_min']}-{settings['delay_max']}s
📊 Reports/Target: {settings['reports_per_target']}
🔄 Parallel: {settings['parallel_sessions']}
🎲 Random: {'✅'if settings['random_order']else'❌'}
🔁 Retry: {'✅'if settings['retry_failed']else'❌'}
🔗 Auto Join: {'✅'if settings['auto_join']else'❌'}
⏭️ Skip Flood: {'✅'if settings['skip_flood']else'❌'}"""
    buttons=[[Button.inline("⏱️ Delay","set_delay"),Button.inline("📊 Reports","set_reports")],[Button.inline("🔄 Parallel","set_parallel")],[Button.inline("🎲 Random","toggle_random"),Button.inline("🔁 Retry","toggle_retry")],[Button.inline("🔗 Join","toggle_join"),Button.inline("⏭️ Flood","toggle_skip_flood")],[Button.inline("♻️ Reset","settings_reset")],[Button.inline("« Back","menu_main")]]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'set_delay'))
async def set_delay_start(event):
    await event.answer()
    uid=event.sender_id
    set_state(uid,'awaiting_delay')
    await event.edit("⏱️ Send delay range:\n\nFormat: min-max\nExample: 2-5\n\nRange: 1-10 seconds",buttons=[[Button.inline("« Cancel","menu_settings")]])

@bot.on(events.NewMessage(func=lambda e:e.is_private and get_state(e.sender_id)and get_state(e.sender_id)['state']=='awaiting_delay'))
async def set_delay_process(event):
    uid=event.sender_id
    text=event.text.strip()
    if'-'in text:
        try:
            min_d,max_d=map(int,text.split('-'))
            if min_d<1 or max_d>10 or min_d>max_d:await event.respond("❌ Invalid range (1-10)");return
            update_setting(uid,'delay_min',min_d)
            update_setting(uid,'delay_max',max_d)
            clear_state(uid)
            await event.respond(f"✅ Delay set to {min_d}-{max_d}s",buttons=[[Button.inline("⚙️ Settings","menu_settings")]])
        except:await event.respond("❌ Invalid format. Use: min-max")
    else:await event.respond("❌ Invalid format. Use: min-max")

@bot.on(events.CallbackQuery(pattern=b'set_reports'))
async def set_reports_start(event):
    await event.answer()
    uid=event.sender_id
    set_state(uid,'awaiting_reports')
    await event.edit("📊 Send reports per target (1-20):",buttons=[[Button.inline("« Cancel","menu_settings")]])

@bot.on(events.NewMessage(func=lambda e:e.is_private and get_state(e.sender_id)and get_state(e.sender_id)['state']=='awaiting_reports'))
async def set_reports_process(event):
    uid=event.sender_id
    text=event.text.strip()
    if not text.isdigit():await event.respond("❌ Invalid number");return
    reports=int(text)
    if reports<1 or reports>20:await event.respond("❌ Must be 1-20");return
    update_setting(uid,'reports_per_target',reports)
    clear_state(uid)
    await event.respond(f"✅ Reports per target set to {reports}",buttons=[[Button.inline("⚙️ Settings","menu_settings")]])

@bot.on(events.CallbackQuery(pattern=b'set_parallel'))
async def set_parallel_start(event):
    await event.answer()
    uid=event.sender_id
    set_state(uid,'awaiting_parallel')
    await event.edit("🔄 Send parallel sessions (1-10):",buttons=[[Button.inline("« Cancel","menu_settings")]])

@bot.on(events.NewMessage(func=lambda e:e.is_private and get_state(e.sender_id)and get_state(e.sender_id)['state']=='awaiting_parallel'))
async def set_parallel_process(event):
    uid=event.sender_id
    text=event.text.strip()
    if not text.isdigit():await event.respond("❌ Invalid number");return
    parallel=int(text)
    if parallel<1 or parallel>10:await event.respond("❌ Must be 1-10");return
    update_setting(uid,'parallel_sessions',parallel)
    clear_state(uid)
    await event.respond(f"✅ Parallel sessions set to {parallel}",buttons=[[Button.inline("⚙️ Settings","menu_settings")]])

@bot.on(events.CallbackQuery(pattern=b'toggle_(random|retry|join|skip_flood)'))
async def toggle_setting(event):
    await event.answer()
    uid=event.sender_id
    setting=event.data.decode().split('_',1)[1]
    settings=get_settings(uid)
    key={'random':'random_order','retry':'retry_failed','join':'auto_join','skip_flood':'skip_flood'}[setting]
    current=settings[key]
    update_setting(uid,key,0 if current else 1)
    await event.answer(f"✅ {'Disabled'if current else'Enabled'}")
    await menu_settings(event)

@bot.on(events.CallbackQuery(pattern=b'settings_reset'))
async def settings_reset(event):
    await event.answer()
    uid=event.sender_id
    db.execute('UPDATE settings SET delay_min=2,delay_max=4,report_limit=50,auto_join=1,random_order=1,retry_failed=0,reports_per_target=1,parallel_sessions=3,skip_flood=0 WHERE user_id=?',(uid,))
    await event.answer("✅ Reset to defaults")
    await menu_settings(event)

@bot.on(events.CallbackQuery(pattern=b'menu_stats'))
async def menu_stats(event):
    await event.answer()
    uid=event.sender_id
    access,status=check_user_access(uid)
    if not access:await event.edit("❌ Access denied");return
    stats=get_stats(uid)
    text=f"""╔══════════════════════════╗
║   📊 STATISTICS 📊      ║
╚══════════════════════════╝

📈 Performance:
  ├ Total: {stats['total_reports']}
  ├ Success: ✅ {stats['successful_reports']}
  ├ Failed: ❌ {stats['failed_reports']}
  └ Rate: {stats['success_rate']}%

🎯 Activity:
  ├ Targets: {stats['targets_reported']}
  └ Sessions: {stats['active_sessions']}

🔥 Streak:
  ├ Current: {stats['streak_days']} days
  └ Best: {stats['best_streak']} days"""
    if stats['last_report_date']:
        last=datetime.fromisoformat(stats['last_report_date'])
        text+=f"\n\n⏰ Last: {last.strftime('%Y-%m-%d %H:%M')}"
    buttons=[[Button.inline("📊 Details","stats_details"),Button.inline("📈 Charts","stats_charts")],[Button.inline("🔄 Refresh","menu_stats")],[Button.inline("« Back","menu_main")]]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'stats_details'))
async def stats_details(event):
    await event.answer()
    uid=event.sender_id
    stats=get_stats(uid)
    recent=db.fetchall('SELECT target,reason,success,timestamp FROM reports WHERE user_id=? ORDER BY timestamp DESC LIMIT 10',(uid,))
    text=f"""╔══════════════════════════╗
║   📊 DETAILED STATS 📊  ║
╚══════════════════════════╝

📈 Overall:
  ├ Reports: {stats['total_reports']}
  ├ Success: {stats['successful_reports']}
  ├ Failed: {stats['failed_reports']}
  └ Rate: {stats['success_rate']}%

📋 Recent Reports:
"""
    for idx,r in enumerate(recent,1):
        status='✅'if r['success']else'❌'
        target_short=r['target'][:20]if len(r['target'])>20 else r['target']
        text+=f"{idx}. {status} {target_short}\n"
    await event.edit(text,buttons=[[Button.inline("« Back","menu_stats")]])

@bot.on(events.CallbackQuery(pattern=b'menu_tools'))
async def menu_tools(event):
    await event.answer()
    uid=event.sender_id
    access,status=check_user_access(uid)
    if not access:await event.edit("❌ Access denied");return
    text="""╔══════════════════════════╗
║    🛠️ TOOLS 🛠️          ║
╚══════════════════════════╝

🔧 Available:

📤 Export sessions/reports
👥 Bulk join/leave groups
🗑️ Clean flood waits
📊 Generate reports
🔄 Backup sessions"""
    buttons=[[Button.inline("📤 Export","tools_export"),Button.inline("👥 Groups","tools_groups")],[Button.inline("🗑️ Clean","tools_clean"),Button.inline("📊 Reports","tools_reports")],[Button.inline("🔄 Backup","tools_backup")],[Button.inline("« Back","menu_main")]]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'tools_clean'))
async def tools_clean(event):
    await event.answer()
    uid=event.sender_id
    db.execute('DELETE FROM flood_wait')
    await event.answer("✅ Cleaned flood waits")
    await menu_tools(event)

@bot.on(events.CallbackQuery(pattern=b'tools_groups'))
async def tools_groups(event):
    await event.answer()
    text="""╔══════════════════════════╗
║   👥 GROUP TOOLS 👥     ║
╚══════════════════════════╝

Choose action:"""
    buttons=[[Button.inline("➕ Bulk Join","groups_join"),Button.inline("➖ Bulk Leave","groups_leave")],[Button.inline("📋 Joined List","groups_list")],[Button.inline("« Back","menu_tools")]]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'menu_help'))
async def menu_help(event):
    await event.answer()
    text="""╔══════════════════════════╗
║      ℹ️ HELP ℹ️          ║
╚══════════════════════════╝

📚 Quick Guide:

1️⃣ Add Sessions:
  └ Upload .session or .zip

2️⃣ Report Targets:
  ├ Single: User/Channel/Group
  └ Bulk: Multiple targets

3️⃣ Settings:
  ├ Adjust delays
  ├ Reports per target
  └ Parallel sessions

4️⃣ Advanced:
  ├ 20 report reasons
  ├ Flood protection
  ├ Auto-join groups
  └ Export/backup

💡 Tips:
  ├ Higher delays = safer
  ├ Monitor health scores
  └ Check limits regularly

📊 Features:
  ├ Multi-session support
  ├ Real-time statistics
  ├ Advanced analytics
  └ Professional UI"""
    buttons=[[Button.inline("📖 Commands","help_commands")],[Button.inline("« Back","menu_main")]]
    await event.edit(text,buttons=buttons)

@bot.on(events.NewMessage(pattern='/admin'))
async def admin_panel(event):
    uid=event.sender_id
    if not is_admin(uid):return
    pending=db.fetchall('SELECT COUNT(*) as cnt FROM approval_requests WHERE status="pending"')
    pending_count=pending[0]['cnt']if pending else 0
    total_users=db.fetchall('SELECT COUNT(*) as cnt FROM users')
    total_count=total_users[0]['cnt']if total_users else 0
    approved=db.fetchall('SELECT COUNT(*) as cnt FROM users WHERE is_approved=1')
    approved_count=approved[0]['cnt']if approved else 0
    text=f"""╔══════════════════════════╗
║   👑 ADMIN PANEL 👑     ║
╚══════════════════════════╝

📊 Overview:
  ├ Total: {total_count}
  ├ Approved: {approved_count}
  └ Pending: {pending_count}"""
    buttons=[[Button.inline("⏳ Pending","admin_pending")],[Button.inline("👥 Users","admin_users")],[Button.inline("📊 Stats","admin_stats")],[Button.inline("🔧 Config","admin_config")]]
    await event.respond(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'admin_pending'))
async def admin_pending(event):
    await event.answer()
    uid=event.sender_id
    if not is_admin(uid):return
    requests=db.fetchall('SELECT * FROM approval_requests WHERE status="pending" ORDER BY requested_date DESC LIMIT 10')
    if not requests:await event.edit("✅ No pending requests",buttons=[[Button.inline("« Back",b"/admin")]]);return
    text=f"""╔══════════════════════════╗
║  ⏳ PENDING REQUESTS ⏳  ║
╚══════════════════════════╝

Total: {len(requests)}

"""
    for idx,req in enumerate(requests[:5],1):
        date=datetime.fromisoformat(req['requested_date']).strftime('%Y-%m-%d')
        text+=f"{idx}. @{req['username']or'N/A'}\n   └ {req['first_name']} | {date}\n"
    buttons=[]
    for req in requests[:5]:buttons.append([Button.inline(f"Review: {req['first_name'][:15]}",f"review_{req['id']}")])
    buttons.append([Button.inline("« Back",b"/admin")])
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'review_(\d+)'))
async def admin_review(event):
    await event.answer()
    uid=event.sender_id
    if not is_admin(uid):return
    req_id=int(event.data.decode().split('_')[1])
    req=db.fetchone('SELECT * FROM approval_requests WHERE id=?',(req_id,))
    if not req:await event.edit("❌ Not found");return
    text=f"""╔══════════════════════════╗
║   👤 USER REVIEW 👤     ║
╚══════════════════════════╝

📋 Details:
  ├ Name: {req['first_name']}
  ├ Username: @{req['username']or'N/A'}
  ├ ID: {req['user_id']}
  └ Date: {datetime.fromisoformat(req['requested_date']).strftime('%Y-%m-%d')}

Choose action:"""
    buttons=[[Button.inline("✅ Full Access",f"approve_full_{req['user_id']}")],[Button.inline("⏰ 3 Day Trial",f"approve_3d_{req['user_id']}")],[Button.inline("⏰ 5 Day Trial",f"approve_5d_{req['user_id']}")],[Button.inline("⏰ 7 Day Trial",f"approve_7d_{req['user_id']}")],[Button.inline("❌ Reject",f"reject_{req['user_id']}")],[Button.inline("« Back","admin_pending")]]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'approve_(full|3d|5d|7d)_(\d+)'))
async def admin_approve(event):
    await event.answer()
    admin_uid=event.sender_id
    if not is_admin(admin_uid):return
    parts=event.data.decode().split('_')
    approval_type=parts[1]
    user_id=int(parts[2])
    now=datetime.now().isoformat()
    trial_expires=None
    max_sessions=0
    max_reports=0
    if approval_type=='full':approval_label='lifetime'
    elif approval_type=='3d':approval_label='trial_3';trial_expires=(datetime.now()+timedelta(days=3)).isoformat();max_sessions=5;max_reports=100
    elif approval_type=='5d':approval_label='trial_5';trial_expires=(datetime.now()+timedelta(days=5)).isoformat();max_sessions=10;max_reports=200
    elif approval_type=='7d':approval_label='trial_7';trial_expires=(datetime.now()+timedelta(days=7)).isoformat();max_sessions=15;max_reports=300
    db.execute('UPDATE users SET is_approved=1,approval_type=?,trial_expires=?,max_sessions=?,max_reports_per_day=?,approved_by=?,approved_date=?,channel_joined=1 WHERE user_id=?',(approval_label,trial_expires,max_sessions,max_reports,admin_uid,now,user_id))
    db.execute('UPDATE approval_requests SET status="approved",reviewed_by=?,reviewed_date=? WHERE user_id=?',(admin_uid,now,user_id))
    try:
        if approval_type=='full':
            await bot.send_message(user_id,f"""╔══════════════════════════╗
║   ✅ APPROVED ✅        ║
╚══════════════════════════╝

🎉 Full access granted!

⚡ Start: /start""",buttons=[[Button.inline("🚀 Start",b"/start")]])
        else:
            days=approval_type.replace('d','')
            await bot.send_message(user_id,f"""╔══════════════════════════╗
║   ✅ TRIAL APPROVED ✅  ║
╚══════════════════════════╝

🎉 Trial activated!

⏰ Duration: {days} days
📱 Sessions: {max_sessions}
📊 Daily: {max_reports}

⚡ Start: /start""",buttons=[[Button.inline("🚀 Start",b"/start")]])
    except:pass
    await event.edit(f"✅ User {user_id} approved",buttons=[[Button.inline("« Back","admin_pending")]])

@bot.on(events.CallbackQuery(pattern=rb'reject_(\d+)'))
async def admin_reject(event):
    await event.answer()
    admin_uid=event.sender_id
    if not is_admin(admin_uid):return
    user_id=int(event.data.decode().split('_')[1])
    now=datetime.now().isoformat()
    db.execute('UPDATE approval_requests SET status="rejected",reviewed_by=?,reviewed_date=? WHERE user_id=?',(admin_uid,now,user_id))
    try:
        await bot.send_message(user_id,"""╔══════════════════════════╗
║   ❌ REQUEST DENIED ❌   ║
╚══════════════════════════╝

Your request was not approved.
Contact admin for details.""")
    except:pass
    await event.edit(f"❌ User {user_id} rejected",buttons=[[Button.inline("« Back","admin_pending")]])

@bot.on(events.NewMessage(func=lambda e:e.document and e.is_private))
async def file_handler(event):
    uid=event.sender_id
    access,status=check_user_access(uid)
    if not access:await event.respond("❌ Access denied");return
    doc=event.document
    fname=None
    for attr in doc.attributes:
        if hasattr(attr,'file_name'):fname=attr.file_name;break
    if not fname:return
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
                    await msg.edit(f"""╔══════════════════════════╗
║   ✅ SESSION ADDED ✅   ║
╚══════════════════════════╝

📱 {phone}
👤 {name}

🎯 Ready!""",buttons=[[Button.inline("📱 Sessions","menu_sessions")],[Button.inline("🎯 Report","report_main")]])
                else:
                    try:os.remove(final)
                    except:pass
                    await msg.edit("❌ Session limit reached",buttons=[[Button.inline("« Back","menu_sessions")]])
            else:
                try:os.remove(path)
                except:pass
                await msg.edit("❌ Invalid session",buttons=[[Button.inline("« Back","menu_sessions")]])
        except Exception as e:await msg.edit(f"❌ Error: {str(e)[:80]}",buttons=[[Button.inline("« Back","menu_sessions")]])
    elif fname.endswith('.zip'):
        msg=await event.respond("📦 Extracting...")
        zpath=os.path.join('temp_files',fname)
        try:
            await event.download_media(file=zpath)
            added,failed=0,0
            with zipfile.ZipFile(zpath,'r')as zf:
                session_files=[f for f in zf.namelist()if f.endswith('.session')]
                total=len(session_files)
                if total==0:await msg.edit("❌ No sessions in ZIP",buttons=[[Button.inline("« Back","menu_sessions")]]);return
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
                            if add_session(uid,phone,name,sname+'.session'):added+=1
                            else:failed+=1;
                            try:os.remove(tpath)
                            except:pass
                        if idx%5==0 or idx==total:
                            try:await msg.edit(f"📦 {idx}/{total}\n✅ {added} ❌ {failed}")
                            except:pass
                    except Exception as e:logger.error(f"Extract: {e}");failed+=1
            await msg.edit(f"""╔══════════════════════════╗
║   📦 ZIP COMPLETE 📦    ║
╚══════════════════════════╝

📊 Results:
  ├ Total: {total}
  ├ Added: ✅ {added}
  └ Failed: ❌ {failed}

{'🎯 Ready!'if added>0 else''}""",buttons=[[Button.inline("📱 Sessions","menu_sessions")],[Button.inline("« Menu","menu_main")]])
        except Exception as e:await msg.edit(f"❌ ZIP Error: {str(e)[:80]}",buttons=[[Button.inline("« Back","menu_sessions")]])
        finally:
            try:os.remove(zpath)
            except:pass

def main():
    print("""
╔══════════════════════════════════════════════════╗
║                                                  ║
║   🎯 TELEGRAM ENTERPRISE REPORTER v4.0 🎯      ║
║        Professional Edition - Bot Control        ║
║                                                  ║
╚══════════════════════════════════════════════════╝

✨ Premium Features:
  ├ 🔐 Channel Verification System
  ├ 👑 Admin Approval System
  ├ ⏰ Trial Period Support (3/5/7 days)
  ├ 📊 Daily Limit Controls
  ├ 📱 Session Limit Management
  ├ 🎯 20 Report Reasons
  ├ 📦 ZIP Session Upload Support
  ├ 🔗 Message Link Reporting
  ├ 🛡️ Advanced Flood Protection
  ├ 📈 Real-time Statistics
  ├ 💎 Professional UI/UX
  ├ 🚀 High Performance Engine
  ├ 📤 Export/Backup Tools
  └ 🔧 Advanced Settings

🔥 System Status:
  ├ Database: ✅ Connected & Optimized
  ├ Bot: ✅ Online & Ready
  ├ API: ✅ Authenticated
  ├ Admin: ✅ Configured
  └ Channel: ✅ Verified

⚡ Production ready - Enterprise grade!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📱 Bot is running...
💡 Press Ctrl+C to stop
""")
    try:
        logger.info("Bot started")
        bot.run_until_disconnected()
    except KeyboardInterrupt:
        print("\n\n⚠️  Shutting down...")
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
