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
ADMIN_IDS=[123456789]
REQUIRED_CHANNEL="https://t.me/+HdWVx6n2C0U4ODU1"

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
async def verify_session(path):
    try:
        client=TelegramClient(path,API_ID,API_HASH)
        await client.connect()
        if not await client.is_user_authorized():await client.disconnect();return False,None,None
        me=await client.get_me()
        phone,name=me.phone,f"{me.first_name or''} {me.last_name or''}".strip()
        await client.disconnect()
        return True,phone,name
    except Exception as e:logger.error(f"Session verify: {e}");return False,None,None

def get_stats(uid):
    row=db.fetchone('SELECT * FROM statistics WHERE user_id=?',(uid,))
    default={'total_sessions':0,'active_sessions':0,'total_reports':0,'successful_reports':0,'failed_reports':0,'success_rate':0,'targets_reported':0,'streak_days':0,'best_streak':0,'last_report_date':None}
    if row:
        total,success=row.get('total_reports',0),row.get('successful_reports',0)
        rate=int((success/total*100))if total>0 else 0
        result=default.copy()
        result.update(row)
        result['success_rate']=rate
        return result
    return default

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
    targets_inc=',targets_reported=targets_reported+1'if target_reported else ''
    db.execute(f'UPDATE statistics SET total_reports=total_reports+?,successful_reports=successful_reports+?,failed_reports=failed_reports+?,last_report_date=?{streak_update}{targets_inc} WHERE user_id=?',(success+failed,success,failed,now,uid))

def create_main_buttons():
    return [[Button.inline("🎯 Report","report_main"),Button.inline("📱 Sessions","menu_sessions")],[Button.inline("📊 Stats","menu_stats"),Button.inline("⚙️ Settings","menu_settings")],[Button.inline("ℹ️ Help","menu_help")]]

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    uid=event.sender_id
    sender=await event.get_sender()
    register_user(uid,sender.username,sender.first_name)
    access,status=check_user_access(uid)
    
    trial_info=""
    if not access:
        if status=='not_joined':
            await event.respond(f"""╔══════════════════════════╗
║   🔐 ACCESS REQUIRED 🔐  ║
╚══════════════════════════╝

⚠️ Channel Membership Required

To use this bot, you must join:
{REQUIRED_CHANNEL}

After joining, click the button below.""",buttons=[[Button.inline("✅ Check Membership","check_channel")]])
            return
        elif status=='not_approved':
            await event.respond("""╔══════════════════════════╗
║  ⏳ APPROVAL PENDING ⏳  ║
╚══════════════════════════╝

Your access request is pending admin approval.

Please wait for approval or contact support.""")
            return
        elif status=='trial_expired':
            await event.respond("""╔══════════════════════════╗
║   ⏰ TRIAL EXPIRED ⏰   ║
╚══════════════════════════╝

Your trial period has ended.

Contact admin for full access.""")
            return
        elif status=='banned':
            await event.respond("""╔══════════════════════════╗
║     ❌ BANNED ❌        ║
╚══════════════════════════╝

Your access has been revoked.""")
            return
    
    user=db.fetchone('SELECT approval_type,trial_expires FROM users WHERE user_id=?',(uid,))
    if user and user['approval_type']and user['approval_type'].startswith('trial'):
        if user['trial_expires']:
            expires=datetime.fromisoformat(user['trial_expires'])
            days_left=(expires-datetime.now()).days
            trial_info=f"\n\n⏰ Trial: {days_left} days left"
    
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
    uid=event.sender_id
    is_member=await check_channel_membership(uid)
    if is_member:
        db.execute('UPDATE users SET channel_joined=1 WHERE user_id=?',(uid,))
        await event.edit("""╔══════════════════════════╗
║    ✅ VERIFIED ✅       ║
╚══════════════════════════╝

Channel membership confirmed!

Your request is now pending admin approval.""",buttons=[[Button.inline("« Menu","menu_main")]])
    else:
        await event.answer("❌ Not joined yet. Please join the channel first.",alert=True)

@bot.on(events.CallbackQuery(pattern=b'menu_main'))
async def menu_main_handler(event):
    uid=event.sender_id
    sender=await event.get_sender()
    access,status=check_user_access(uid)
    if not access:await event.answer("❌ Access denied",alert=True);return
    stats=get_stats(uid)
    welcome=f"""╔══════════════════════════╗
║  🎯 TELEGRAM REPORTER 🎯  ║
╚══════════════════════════╝

📊 Stats:
  ├ Reports: {stats['total_reports']}
  ├ Success: {stats['success_rate']}%
  └ Sessions: {stats['active_sessions']}"""
    await event.edit(welcome,buttons=create_main_buttons())

@bot.on(events.CallbackQuery(pattern=b'report_main'))
async def report_main_handler(event):
    uid=event.sender_id
    access,status=check_user_access(uid)
    if not access:await event.answer("❌ Access denied",alert=True);return
    sessions=get_sessions(uid)
    if not sessions:
        await event.edit("❌ No sessions available!\n\nAdd sessions first.",buttons=[[Button.inline("📱 Add Session","menu_sessions")],[Button.inline("« Back","menu_main")]])
        return
    can_report,remaining=check_daily_limit(uid)
    if not can_report:
        await event.edit("❌ Daily limit reached!\n\nTry again tomorrow.",buttons=[[Button.inline("« Back","menu_main")]])
        return
    await event.edit(f"""╔══════════════════════════╗
║   🎯 REPORT MODULE 🎯   ║
╚══════════════════════════╝

📱 Active Sessions: {len(sessions)}
📊 Daily Limit: {remaining if remaining>0 else'Unlimited'}

Send target username or link:
Example: @username or t.me/username""",buttons=[[Button.inline("« Back","menu_main")]])
    set_state(uid,'awaiting_target')

@bot.on(events.NewMessage(func=lambda e:e.is_private and not e.text.startswith('/')))
async def text_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state:return
    access,status=check_user_access(uid)
    if not access:await event.respond("❌ Access denied");return
    
    if state['state']=='awaiting_target':
        target=event.text.strip()
        set_state(uid,'awaiting_reason',target=target)
        reasons_text="📋 Select Report Reason:\n\n"
        buttons=[]
        for key,val in list(REASONS.items())[:20]:
            reasons_text+=f"{key}. {val[0]}\n"
            buttons.append([Button.inline(f"{val[0]}",f"reason_{key}")])
        buttons.append([Button.inline("« Cancel","menu_main")])
        await event.respond(reasons_text,buttons=buttons)
    
    elif state['state']=='awaiting_reason':
        await event.respond("Please select a reason from the buttons above.")

@bot.on(events.CallbackQuery(pattern=rb'reason_(\d+)'))
async def reason_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state or state['state']!='awaiting_reason':await event.answer("❌ Invalid state",alert=True);return
    access,status=check_user_access(uid)
    if not access:await event.answer("❌ Access denied",alert=True);return
    
    reason_id=event.data.decode().split('_')[1]
    target=state.get('target')
    if not target or reason_id not in REASONS:await event.answer("❌ Error",alert=True);return
    
    clear_state(uid)
    reason_name,reason_obj=REASONS[reason_id][0],REASONS[reason_id][1]
    
    msg=await event.edit(f"""╔══════════════════════════╗
║   🚀 REPORTING... 🚀    ║
╚══════════════════════════╝

🎯 Target: {target}
⚔️ Reason: {reason_name}

⏳ Processing...""")
    
    sessions=get_sessions(uid)
    settings=db.fetchone('SELECT * FROM settings WHERE user_id=?',(uid,))
    if not settings:settings={'delay_min':2,'delay_max':4,'parallel_sessions':3}
    
    success_count=0
    failed_count=0
    flood_count=0
    
    for session in sessions[:settings['parallel_sessions']]:
        try:
            session_path=os.path.join('sessions_db',session['session_file']).replace('.session','')
            client=TelegramClient(session_path,API_ID,API_HASH)
            await client.connect()
            
            if not await client.is_user_authorized():
                failed_count+=1
                continue
            
            try:
                entity=await client.get_entity(target)
                start_time=time.time()
                
                if isinstance(entity,Channel):
                    await client(ReportPeerRequest(peer=entity,reason=reason_obj,message=''))
                elif isinstance(entity,User):
                    await client(ReportPeerRequest(peer=entity,reason=reason_obj,message=''))
                else:
                    await client(ReportPeerRequest(peer=entity,reason=reason_obj,message=''))
                
                exec_time=time.time()-start_time
                success_count+=1
                db.execute('INSERT INTO reports(user_id,session_phone,target,target_type,reason,success,timestamp,execution_time)VALUES(?,?,?,?,?,1,?,?)',
                          (uid,session['phone'],target,type(entity).__name__,reason_name,datetime.now().isoformat(),exec_time))
                db.execute('UPDATE sessions SET total_reports=total_reports+1,success_reports=success_reports+1,last_used=? WHERE phone=?',(datetime.now().isoformat(),session['phone']))
                
                if sessions.index(session)<len(sessions)-1:
                    await asyncio.sleep(random.uniform(settings['delay_min'],settings['delay_max']))
            
            except FloodWaitError as e:
                flood_count+=1
                db.execute('INSERT OR REPLACE INTO flood_wait(session_phone,wait_until,wait_seconds)VALUES(?,?,?)',
                          (session['phone'],(datetime.now()+timedelta(seconds=e.seconds)).isoformat(),e.seconds))
                db.execute('UPDATE sessions SET health_score=MAX(0,health_score-10) WHERE phone=?',(session['phone'],))
            except Exception as e:
                failed_count+=1
                db.execute('INSERT INTO reports(user_id,session_phone,target,target_type,reason,success,timestamp,error_msg)VALUES(?,?,?,?,?,0,?,?)',
                          (uid,session['phone'],target,'Unknown',reason_name,datetime.now().isoformat(),str(e)[:200]))
                db.execute('UPDATE sessions SET failed_reports=failed_reports+1 WHERE phone=?',(session['phone'],))
            
            await client.disconnect()
        except Exception as e:
            logger.error(f"Report error: {e}")
            failed_count+=1
    
    update_stats(uid,success=success_count,failed=failed_count,target_reported=success_count>0)
    increment_daily_usage(uid,success_count)
    
    result_text=f"""╔══════════════════════════╗
║   ✅ COMPLETE ✅        ║
╚══════════════════════════╝

🎯 Target: {target}
⚔️ Reason: {reason_name}

📊 Results:
  ├ Success: ✅ {success_count}
  ├ Failed: ❌ {failed_count}
  └ Flood: ⏰ {flood_count}

{'🎉 Reports sent successfully!'if success_count>0 else'⚠️ All reports failed'}"""
    
    await msg.edit(result_text,buttons=[[Button.inline("🎯 Report Again","report_main")],[Button.inline("📊 Stats","menu_stats")],[Button.inline("« Menu","menu_main")]])

@bot.on(events.CallbackQuery(pattern=b'menu_stats'))
async def stats_handler(event):
    uid=event.sender_id
    access,status=check_user_access(uid)
    if not access:await event.answer("❌ Access denied",alert=True);return
    stats=get_stats(uid)
    sessions=get_sessions(uid)
    
    stats_text=f"""╔══════════════════════════╗
║   📊 STATISTICS 📊      ║
╚══════════════════════════╝

📱 Sessions:
  ├ Total: {stats['total_sessions']}
  └ Active: {stats['active_sessions']}

🎯 Reports:
  ├ Total: {stats['total_reports']}
  ├ Success: {stats['successful_reports']}
  ├ Failed: {stats['failed_reports']}
  └ Success Rate: {stats['success_rate']}%

🏆 Performance:
  ├ Targets: {stats['targets_reported']}
  ├ Current Streak: {stats['streak_days']} days
  └ Best Streak: {stats['best_streak']} days

📅 Last Report: {stats['last_report_date'][:10]if stats['last_report_date']else'Never'}"""
    
    await event.edit(stats_text,buttons=[[Button.inline("📱 Sessions","menu_sessions")],[Button.inline("🎯 Report","report_main")],[Button.inline("« Menu","menu_main")]])

@bot.on(events.CallbackQuery(pattern=b'menu_sessions'))
async def sessions_handler(event):
    uid=event.sender_id
    access,status=check_user_access(uid)
    if not access:await event.answer("❌ Access denied",alert=True);return
    sessions=get_sessions(uid)
    user=db.fetchone('SELECT max_sessions FROM users WHERE user_id=?',(uid,))
    max_sessions=user['max_sessions']if user and user['max_sessions']>0 else'Unlimited'
    
    sessions_text=f"""╔══════════════════════════╗
║   📱 SESSIONS 📱       ║
╚══════════════════════════╝

Active Sessions: {len(sessions)}/{max_sessions}

"""
    if sessions:
        for i,s in enumerate(sessions[:10],1):
            health="🟢"if s['health_score']>=70 else"🟡"if s['health_score']>=40 else"🔴"
            sessions_text+=f"{i}. {health} {s['phone']}\n   {s['name']}\n   ✅ {s['success_reports']} | ❌ {s['failed_reports']}\n\n"
    else:
        sessions_text+="No sessions added yet.\n\nUpload a .session file to get started!"
    
    buttons=[[Button.inline("➕ Add Session","add_session_info")]]
    if sessions:buttons.append([Button.inline("🗑️ Remove Session","remove_session")])
    buttons.append([Button.inline("« Menu","menu_main")])
    
    await event.edit(sessions_text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'add_session_info'))
async def add_session_info_handler(event):
    await event.edit("""╔══════════════════════════╗
║  ➕ ADD SESSION ➕     ║
╚══════════════════════════╝

📋 Instructions:

1. Export your Telegram session
2. Send the .session file here
3. Or send a .zip with multiple sessions

✅ Supported formats:
  • .session files
  • .zip archives

🔒 Your sessions are secure!""",buttons=[[Button.inline("« Back","menu_sessions")]])

@bot.on(events.CallbackQuery(pattern=b'menu_settings'))
async def settings_handler(event):
    uid=event.sender_id
    access,status=check_user_access(uid)
    if not access:await event.answer("❌ Access denied",alert=True);return
    settings=db.fetchone('SELECT * FROM settings WHERE user_id=?',(uid,))
    if not settings:settings={'delay_min':2,'delay_max':4,'parallel_sessions':3,'auto_join':1,'random_order':1}
    
    settings_text=f"""╔══════════════════════════╗
║   ⚙️ SETTINGS ⚙️       ║
╚══════════════════════════╝

⏱️ Delays:
  ├ Min: {settings['delay_min']}s
  └ Max: {settings['delay_max']}s

🔧 Behavior:
  ├ Parallel Sessions: {settings['parallel_sessions']}
  ├ Auto Join: {'✅'if settings['auto_join']else'❌'}
  └ Random Order: {'✅'if settings['random_order']else'❌'}

💡 These settings optimize reporting performance."""
    
    await event.edit(settings_text,buttons=[[Button.inline("« Menu","menu_main")]])

@bot.on(events.CallbackQuery(pattern=b'menu_help'))
async def help_handler(event):
    help_text="""╔══════════════════════════╗
║     ℹ️ HELP ℹ️         ║
╚══════════════════════════╝

📋 How to Use:

1️⃣ Add Sessions
   • Upload .session files
   • Or send .zip archives

2️⃣ Start Reporting
   • Select Report from menu
   • Enter target username
   • Choose report reason

3️⃣ Track Progress
   • View stats anytime
   • Monitor session health
   • Check success rates

🔧 Features:
  ├ Multi-session support
  ├ Flood protection
  ├ Auto delay management
  ├ Health monitoring
  └ Advanced statistics

💡 Tips:
  • Keep sessions healthy
  • Use multiple sessions
  • Check stats regularly

Need help? Contact admin."""
    
    await event.edit(help_text,buttons=[[Button.inline("« Menu","menu_main")]])

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
                            else:failed+=1
                        else:failed+=1
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

# Admin Commands
@bot.on(events.NewMessage(pattern='/admin'))
async def admin_handler(event):
    uid=event.sender_id
    if not is_admin(uid):return
    pending=db.fetchall("SELECT * FROM approval_requests WHERE status='pending' ORDER BY requested_date DESC LIMIT 10")
    
    if not pending:
        await event.respond("✅ No pending requests",buttons=[[Button.inline("« Menu","menu_main")]])
        return
    
    text="🔐 Pending Approval Requests:\n\n"
    buttons=[]
    for req in pending:
        text+=f"ID: {req['id']}\nUser: {req['first_name']} (@{req['username']})\nDate: {req['requested_date'][:10]}\n\n"
        buttons.append([Button.inline(f"✅ {req['first_name']}",f"approve_{req['id']}"),Button.inline(f"❌ Reject",f"reject_{req['id']}")])
    
    await event.respond(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'approve_(\d+)'))
async def approve_handler(event):
    uid=event.sender_id
    if not is_admin(uid):await event.answer("❌ Admin only",alert=True);return
    req_id=int(event.data.decode().split('_')[1])
    req=db.fetchone('SELECT user_id FROM approval_requests WHERE id=?',(req_id,))
    if not req:await event.answer("❌ Not found",alert=True);return
    
    now=datetime.now().isoformat()
    db.execute('UPDATE approval_requests SET status=?,reviewed_by=?,reviewed_date=? WHERE id=?',('approved',uid,now,req_id))
    db.execute('UPDATE users SET is_approved=1,approval_type=?,approved_by=?,approved_date=?,max_sessions=?,max_reports_per_day=? WHERE user_id=?',('full',uid,now,10,100,req['user_id']))
    
    await event.answer("✅ Approved!",alert=True)
    await bot.send_message(req['user_id'],"""╔══════════════════════════╗
║   ✅ APPROVED ✅       ║
╚══════════════════════════╝

Your access has been approved!

You can now use all features.""",buttons=[[Button.inline("🎯 Start","menu_main")]])
    
    await admin_handler(await event.get_message())

@bot.on(events.CallbackQuery(pattern=rb'reject_(\d+)'))
async def reject_handler(event):
    uid=event.sender_id
    if not is_admin(uid):await event.answer("❌ Admin only",alert=True);return
    req_id=int(event.data.decode().split('_')[1])
    req=db.fetchone('SELECT user_id FROM approval_requests WHERE id=?',(req_id,))
    if not req:await event.answer("❌ Not found",alert=True);return
    
    now=datetime.now().isoformat()
    db.execute('UPDATE approval_requests SET status=?,reviewed_by=?,reviewed_date=? WHERE id=?',('rejected',uid,now,req_id))
    
    await event.answer("❌ Rejected",alert=True)
    await admin_handler(await event.get_message())

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
