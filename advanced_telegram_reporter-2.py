#!/usr/bin/env python3
import os,sys,json,asyncio,zipfile,shutil,time,random,logging,sqlite3,hashlib
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
ADMIN_IDS=[123456789]

for d in ['sessions_db','temp_files','data','backups','logs','exports','cache','media']:
    os.makedirs(d,exist_ok=True)

logging.basicConfig(level=logging.INFO,format='%(asctime)s [%(levelname)s] %(message)s',handlers=[logging.FileHandler(f'logs/bot_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),logging.StreamHandler()])
logger=logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.conn=sqlite3.connect('data/advanced_reporter.db',check_same_thread=False,timeout=30)
        self.conn.row_factory=sqlite3.Row
        self._init_tables()
        self._migrate()
        self._optimize()
    
    def _init_tables(self):
        c=self.conn.cursor()
        c.executescript('''
            CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                phone TEXT,
                language TEXT DEFAULT 'en',
                is_premium INTEGER DEFAULT 0,
                is_approved INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                approval_type TEXT,
                trial_expires TEXT,
                joined_date TEXT,
                last_active TEXT,
                total_usage INTEGER DEFAULT 0,
                max_sessions INTEGER DEFAULT 0,
                max_reports_per_day INTEGER DEFAULT 0,
                approved_by INTEGER,
                approved_date TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                phone TEXT UNIQUE,
                name TEXT,
                username TEXT,
                session_file TEXT,
                session_hash TEXT,
                verified INTEGER DEFAULT 0,
                added_date TEXT,
                total_reports INTEGER DEFAULT 0,
                success_reports INTEGER DEFAULT 0,
                failed_reports INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                last_used TEXT,
                flood_wait_until TEXT,
                health_score INTEGER DEFAULT 100,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS reports(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                session_phone TEXT,
                target TEXT,
                target_id TEXT,
                target_type TEXT,
                reason TEXT,
                reason_text TEXT,
                success INTEGER,
                timestamp TEXT,
                execution_time REAL,
                error_msg TEXT,
                retry_count INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS settings(
                user_id INTEGER PRIMARY KEY,
                delay_min INTEGER DEFAULT 2,
                delay_max INTEGER DEFAULT 4,
                report_limit INTEGER DEFAULT 100,
                auto_join INTEGER DEFAULT 1,
                random_order INTEGER DEFAULT 1,
                retry_failed INTEGER DEFAULT 1,
                reports_per_target INTEGER DEFAULT 1,
                parallel_sessions INTEGER DEFAULT 3,
                skip_flood_wait INTEGER DEFAULT 0,
                notification_level INTEGER DEFAULT 1,
                auto_backup INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS statistics(
                user_id INTEGER PRIMARY KEY,
                total_sessions INTEGER DEFAULT 0,
                active_sessions INTEGER DEFAULT 0,
                total_reports INTEGER DEFAULT 0,
                successful_reports INTEGER DEFAULT 0,
                failed_reports INTEGER DEFAULT 0,
                targets_reported INTEGER DEFAULT 0,
                groups_joined INTEGER DEFAULT 0,
                groups_left INTEGER DEFAULT 0,
                total_retries INTEGER DEFAULT 0,
                last_report_date TEXT,
                streak_days INTEGER DEFAULT 0,
                best_streak INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS flood_wait(
                session_phone TEXT PRIMARY KEY,
                wait_until TEXT,
                wait_seconds INTEGER,
                occurrence_count INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS targets_cache(
                target TEXT PRIMARY KEY,
                entity_id TEXT,
                entity_type TEXT,
                entity_title TEXT,
                cached_date TEXT,
                access_hash TEXT,
                is_verified INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS activity_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                details TEXT,
                timestamp TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS groups_joined(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                session_phone TEXT,
                group_link TEXT,
                group_id TEXT,
                group_title TEXT,
                joined_date TEXT,
                is_left INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS approval_requests(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                first_name TEXT,
                request_type TEXT,
                requested_date TEXT,
                status TEXT DEFAULT 'pending',
                reviewed_by INTEGER,
                reviewed_date TEXT,
                notes TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS user_limits(
                user_id INTEGER PRIMARY KEY,
                daily_reports_used INTEGER DEFAULT 0,
                last_reset_date TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id,timestamp);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id,is_active);
            CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_log(user_id,timestamp);
            CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status,requested_date);
        ''')
        self.conn.commit()
    
    def _migrate(self):
        c=self.conn.cursor()
        migrations=[
            ("session_hash","sessions","ALTER TABLE sessions ADD COLUMN session_hash TEXT"),
            ("health_score","sessions","ALTER TABLE sessions ADD COLUMN health_score INTEGER DEFAULT 100"),
            ("retry_count","reports","ALTER TABLE reports ADD COLUMN retry_count INTEGER DEFAULT 0"),
            ("execution_time","reports","ALTER TABLE reports ADD COLUMN execution_time REAL"),
            ("parallel_sessions","settings","ALTER TABLE settings ADD COLUMN parallel_sessions INTEGER DEFAULT 3"),
            ("notification_level","settings","ALTER TABLE settings ADD COLUMN notification_level INTEGER DEFAULT 1"),
            ("streak_days","statistics","ALTER TABLE statistics ADD COLUMN streak_days INTEGER DEFAULT 0"),
            ("best_streak","statistics","ALTER TABLE statistics ADD COLUMN best_streak INTEGER DEFAULT 0"),
            ("targets_reported","statistics","ALTER TABLE statistics ADD COLUMN targets_reported INTEGER DEFAULT 0"),
            ("is_approved","users","ALTER TABLE users ADD COLUMN is_approved INTEGER DEFAULT 0"),
            ("approval_type","users","ALTER TABLE users ADD COLUMN approval_type TEXT"),
            ("trial_expires","users","ALTER TABLE users ADD COLUMN trial_expires TEXT"),
            ("max_sessions","users","ALTER TABLE users ADD COLUMN max_sessions INTEGER DEFAULT 0"),
            ("max_reports_per_day","users","ALTER TABLE users ADD COLUMN max_reports_per_day INTEGER DEFAULT 0"),
            ("approved_by","users","ALTER TABLE users ADD COLUMN approved_by INTEGER"),
            ("approved_date","users","ALTER TABLE users ADD COLUMN approved_date TEXT")
        ]
        for col,table,sql in migrations:
            try:
                c.execute(f"SELECT {col} FROM {table} LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    c.execute(sql)
                    self.conn.commit()
                except:pass
    
    def _optimize(self):
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

REASONS={
    "1":("📧 Spam",InputReportReasonSpam()),
    "2":("⚔️ Violence",InputReportReasonViolence()),
    "3":("🔞 Pornography",InputReportReasonPornography()),
    "4":("👶 Child Abuse",InputReportReasonChildAbuse()),
    "5":("© Copyright",InputReportReasonCopyright()),
    "6":("🎭 Fake Account",InputReportReasonFake()),
    "7":("💊 Illegal Drugs",InputReportReasonIllegalDrugs()),
    "8":("🔐 Personal Info",InputReportReasonPersonalDetails()),
    "9":("🌍 Geo Irrelevant",InputReportReasonGeoIrrelevant()),
    "10":("❓ Other",InputReportReasonOther())
}

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
            except:pass
        del user_states[uid]

def is_admin(uid):
    return uid in ADMIN_IDS

def check_user_access(uid):
    user=db.fetchone('SELECT is_approved,is_banned,trial_expires,approval_type FROM users WHERE user_id=?',(uid,))
    if not user:
        return False,'not_registered'
    if user['is_banned']:
        return False,'banned'
    if is_admin(uid):
        return True,'admin'
    if not user['is_approved']:
        return False,'not_approved'
    if user['approval_type']in['trial_3','trial_5','trial_7']:
        if user['trial_expires']:
            expires=datetime.fromisoformat(user['trial_expires'])
            if datetime.now()>expires:
                db.execute('UPDATE users SET is_approved=0,approval_type=NULL WHERE user_id=?',(uid,))
                return False,'trial_expired'
    return True,'approved'

def check_daily_limit(uid):
    user=db.fetchone('SELECT max_reports_per_day FROM users WHERE user_id=?',(uid,))
    if not user or user['max_reports_per_day']==0:
        return True,0
    
    limit_data=db.fetchone('SELECT daily_reports_used,last_reset_date FROM user_limits WHERE user_id=?',(uid,))
    today=datetime.now().date().isoformat()
    
    if not limit_data:
        db.execute('INSERT INTO user_limits(user_id,last_reset_date)VALUES(?,?)',(uid,today))
        return True,user['max_reports_per_day']
    
    if limit_data['last_reset_date']!=today:
        db.execute('UPDATE user_limits SET daily_reports_used=0,last_reset_date=? WHERE user_id=?',(today,uid))
        return True,user['max_reports_per_day']
    
    if limit_data['daily_reports_used']>=user['max_reports_per_day']:
        return False,0
    
    return True,user['max_reports_per_day']-limit_data['daily_reports_used']

def increment_daily_usage(uid,count=1):
    db.execute('UPDATE user_limits SET daily_reports_used=daily_reports_used+? WHERE user_id=?',(count,uid))

def register_user(uid,username,first_name,last_name='',phone=''):
    existing=db.fetchone('SELECT user_id FROM users WHERE user_id=?',(uid,))
    now=datetime.now().isoformat()
    if not existing:
        db.execute('''INSERT INTO users(user_id,username,first_name,last_name,phone,joined_date,last_active)
                      VALUES(?,?,?,?,?,?,?)''',(uid,username,first_name,last_name,phone,now,now))
        db.execute('INSERT INTO settings(user_id)VALUES(?)',(uid,))
        db.execute('INSERT INTO statistics(user_id)VALUES(?)',(uid,))
        db.execute('INSERT INTO user_limits(user_id,last_reset_date)VALUES(?,?)',(uid,datetime.now().date().isoformat()))
        log_activity(uid,'user_registered','New user registered')
        if not is_admin(uid):
            db.execute('''INSERT INTO approval_requests(user_id,username,first_name,request_type,requested_date)
                         VALUES(?,?,?,?,?)''',(uid,username,first_name,'access',now))
    else:
        db.execute('UPDATE users SET last_active=?,total_usage=total_usage+1 WHERE user_id=?',(now,uid))

def log_activity(uid,action,details=''):
    now=datetime.now().isoformat()
    db.execute('INSERT INTO activity_log(user_id,action,details,timestamp)VALUES(?,?,?,?)',(uid,action,details,now))

def get_sessions(uid):
    return db.fetchall('''SELECT * FROM sessions WHERE user_id=? AND is_active=1 
                          ORDER BY health_score DESC,success_reports DESC''',(uid,))

def add_session(uid,phone,name,username,session_file):
    user=db.fetchone('SELECT max_sessions FROM users WHERE user_id=?',(uid,))
    if user and user['max_sessions']>0:
        current_count=len(get_sessions(uid))
        if current_count>=user['max_sessions']:
            return False
    
    now=datetime.now().isoformat()
    session_hash=hashlib.md5(f"{phone}{name}".encode()).hexdigest()
    existing=db.fetchone('SELECT id FROM sessions WHERE user_id=? AND phone=?',(uid,phone))
    if existing:
        db.execute('''UPDATE sessions SET is_active=1,name=?,username=?,session_file=?,
                      session_hash=?,verified=1,last_used=? WHERE user_id=? AND phone=?''',
                   (name,username,session_file,session_hash,now,uid,phone))
    else:
        db.execute('''INSERT INTO sessions(user_id,phone,name,username,session_file,session_hash,
                      verified,added_date,last_used)VALUES(?,?,?,?,?,?,1,?,?)''',
                   (uid,phone,name,username,session_file,session_hash,now,now))
        db.execute('UPDATE statistics SET total_sessions=total_sessions+1,active_sessions=active_sessions+1 WHERE user_id=?',(uid,))
    log_activity(uid,'session_added',f'Phone: {phone}')
    return True

def remove_session(uid,phone):
    db.execute('UPDATE sessions SET is_active=0 WHERE user_id=? AND phone=?',(uid,phone))
    db.execute('UPDATE statistics SET active_sessions=active_sessions-1 WHERE user_id=? AND active_sessions>0',(uid,))
    log_activity(uid,'session_removed',f'Phone: {phone}')

def update_session_stats(uid,phone,success=0,failed=0):
    now=datetime.now().isoformat()
    health_change=-5 if failed else 2 if success else 0
    db.execute('''UPDATE sessions SET total_reports=total_reports+?,success_reports=success_reports+?,
                  failed_reports=failed_reports+?,last_used=?,health_score=MIN(100,MAX(0,health_score+?))
                  WHERE user_id=? AND phone=?''',
               (success+failed,success,failed,now,health_change,uid,phone))

def get_settings(uid):
    row=db.fetchone('SELECT * FROM settings WHERE user_id=?',(uid,))
    if row:
        return row
    return {'delay_min':2,'delay_max':4,'report_limit':100,'auto_join':1,'random_order':1,
            'retry_failed':1,'reports_per_target':1,'parallel_sessions':3,'skip_flood_wait':0,
            'notification_level':1,'auto_backup':0}

def update_setting(uid,key,val):
    db.execute(f'UPDATE settings SET {key}=? WHERE user_id=?',(val,uid))
    log_activity(uid,'setting_changed',f'{key}={val}')

def get_stats(uid):
    row=db.fetchone('SELECT * FROM statistics WHERE user_id=?',(uid,))
    if row:
        total,success=row['total_reports'],row['successful_reports']
        rate=int((success/total*100))if total>0 else 0
        return {**row,'success_rate':rate}
    return {'total_sessions':0,'active_sessions':0,'total_reports':0,'successful_reports':0,
            'failed_reports':0,'success_rate':0,'targets_reported':0,'groups_joined':0,
            'groups_left':0,'total_retries':0,'streak_days':0,'best_streak':0,'last_report_date':None}

def update_stats(uid,success=0,failed=0,target_reported=False,retries=0):
    now=datetime.now().isoformat()
    last_date=db.fetchone('SELECT last_report_date FROM statistics WHERE user_id=?',(uid,))
    streak_update=''
    if last_date and last_date['last_report_date']:
        last=datetime.fromisoformat(last_date['last_report_date']).date()
        today=datetime.now().date()
        if(today-last).days==1:
            streak_update=',streak_days=streak_days+1,best_streak=MAX(best_streak,streak_days+1)'
        elif(today-last).days>1:
            streak_update=',streak_days=1'
    else:
        streak_update=',streak_days=1'
    
    target_inc=1 if target_reported else 0
    db.execute(f'''UPDATE statistics SET total_reports=total_reports+?,successful_reports=successful_reports+?,
                   failed_reports=failed_reports+?,last_report_date=?,targets_reported=targets_reported+?,
                   total_retries=total_retries+?{streak_update} WHERE user_id=?''',
               (success+failed,success,failed,now,target_inc,retries,uid))

def log_report(uid,phone,target,target_id,target_type,reason,reason_text,success,exec_time=0,error='',retry=0):
    now=datetime.now().isoformat()
    db.execute('''INSERT INTO reports(user_id,session_phone,target,target_id,target_type,reason,reason_text,
                  success,timestamp,execution_time,error_msg,retry_count)VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
               (uid,phone,target,target_id,target_type,reason,reason_text,success,now,exec_time,error,retry))

def check_flood_wait(phone):
    row=db.fetchone('SELECT wait_until,wait_seconds FROM flood_wait WHERE session_phone=?',(phone,))
    if row:
        wait_until=datetime.fromisoformat(row['wait_until'])
        if datetime.now()<wait_until:
            return True,(wait_until-datetime.now()).seconds
    return False,0

def set_flood_wait(phone,seconds):
    wait_until=(datetime.now()+timedelta(seconds=seconds)).isoformat()
    db.execute('''INSERT OR REPLACE INTO flood_wait(session_phone,wait_until,wait_seconds,occurrence_count)
                  VALUES(?,?,?,COALESCE((SELECT occurrence_count FROM flood_wait WHERE session_phone=?)+1,1))''',
               (phone,wait_until,seconds,phone))

def clear_flood_wait(phone):
    db.execute('DELETE FROM flood_wait WHERE session_phone=?',(phone,))

def cache_target(target,entity_id,entity_type,entity_title,access_hash='',verified=0):
    now=datetime.now().isoformat()
    db.execute('''INSERT OR REPLACE INTO targets_cache(target,entity_id,entity_type,entity_title,
                  cached_date,access_hash,is_verified)VALUES(?,?,?,?,?,?,?)''',
               (target,entity_id,entity_type,entity_title,now,access_hash,verified))

def get_cached_target(target):
    row=db.fetchone('SELECT * FROM targets_cache WHERE target=?',(target,))
    if row:
        cached=datetime.fromisoformat(row['cached_date'])
        if datetime.now()-cached<timedelta(hours=24):
            return row
    return None

async def create_client(session_path):
    try:
        client=TelegramClient(session_path,API_ID,API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            return None,None,None,None
        me=await client.get_me()
        return client,me.phone,f"{me.first_name or ''} {me.last_name or ''}".strip(),me.username or ''
    except Exception as e:
        logger.error(f"Client error: {e}")
        return None,None,None,None

async def verify_session(session_path):
    client=TelegramClient(session_path,API_ID,API_HASH)
    try:
        await client.connect()
        if await client.is_user_authorized():
            me=await client.get_me()
            await client.disconnect()
            return True,me.phone,f"{me.first_name or ''} {me.last_name or ''}".strip(),me.username or ''
        await client.disconnect()
        return False,'','',''
    except Exception as e:
        logger.error(f"Verify error: {e}")
        try:
            await client.disconnect()
        except:pass
        return False,'','',''

async def get_entity_smart(client,target):
    cached=get_cached_target(target)
    if cached:
        try:
            entity=await client.get_entity(int(cached['entity_id']))
            return entity,cached['entity_type']
        except:pass
    
    try:
        entity=await client.get_entity(target)
        if isinstance(entity,User):
            etype='user'
        elif isinstance(entity,Channel):
            etype='channel' if entity.broadcast else 'group'
        elif isinstance(entity,Chat):
            etype='group'
        else:
            etype='unknown'
        
        title=getattr(entity,'title',None)or getattr(entity,'first_name',None)or ''
        cache_target(target,str(entity.id),etype,title,str(getattr(entity,'access_hash','')),
                    int(getattr(entity,'verified',False)))
        return entity,etype
    except Exception as e:
        logger.error(f"Entity error: {e}")
        return None,None

async def report_target(client,phone,target,reason_obj,uid,reason_text,retry=0):
    start_time=time.time()
    try:
        entity,etype=await get_entity_smart(client,target)
        if not entity:
            return False,"Entity not found",0,0
        
        if etype=='user':
            await client(ReportPeerRequest(peer=entity,reason=reason_obj,message=''))
        elif etype in['channel','group']:
            try:
                messages=await client.get_messages(entity,limit=1)
                if messages:
                    await client(ReportRequest(peer=entity,id=[messages[0].id],reason=reason_obj,message=''))
                else:
                    await client(ReportPeerRequest(peer=entity,reason=reason_obj,message=''))
            except:
                await client(ReportPeerRequest(peer=entity,reason=reason_obj,message=''))
        
        exec_time=time.time()-start_time
        log_report(uid,phone,target,str(entity.id),etype,reason_text,reason_obj.__class__.__name__,
                  1,exec_time,'',retry)
        return True,None,exec_time,entity.id
    
    except FloodWaitError as e:
        exec_time=time.time()-start_time
        set_flood_wait(phone,e.seconds)
        log_report(uid,phone,target,'','',reason_text,reason_obj.__class__.__name__,
                  0,exec_time,f"Flood: {e.seconds}s",retry)
        return False,f"Flood: {e.seconds}s",exec_time,0
    
    except Exception as e:
        exec_time=time.time()-start_time
        error=str(e)[:200]
        log_report(uid,phone,target,'','',reason_text,reason_obj.__class__.__name__,
                  0,exec_time,error,retry)
        return False,error,exec_time,0

def create_main_menu_buttons():
    return [
        [Button.inline("🎯 Report","report_main"),Button.inline("📱 Sessions","menu_sessions")],
        [Button.inline("📊 Stats","menu_stats"),Button.inline("⚙️ Settings","menu_settings")],
        [Button.inline("🛠️ Tools","menu_tools"),Button.inline("ℹ️ Help","menu_help")]
    ]

def format_report_progress(current,total,success,failed,skipped,elapsed):
    progress=int((current/total*100))if total>0 else 0
    bar_length=20
    filled=int(bar_length*progress/100)
    bar='█'*filled+'░'*(bar_length-filled)
    
    return f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   🎯 REPORTING PROGRESS   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📊 Progress: {current}/{total} ({progress}%)
{bar}

✅ Success: {success}
❌ Failed: {failed}
⏭️ Skipped: {skipped}
⏱️ Time: {elapsed}s"""

def format_report_complete(success,failed,skipped,total_time,targets,sessions):
    success_rate=int((success/(success+failed)*100))if(success+failed)>0 else 0
    avg_time=total_time/(success+failed)if(success+failed)>0 else 0
    
    return f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   ✅ REPORT COMPLETED     ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📊 Results:
  ├ Total: {success+failed+skipped}
  ├ Success: ✅ {success}
  ├ Failed: ❌ {failed}
  ├ Skipped: ⏭️ {skipped}
  └ Rate: {success_rate}%

⚡ Performance:
  ├ Time: {total_time:.1f}s
  ├ Avg: {avg_time:.2f}s/op
  └ Speed: {((success+failed)/total_time if total_time>0 else 0):.2f} ops/s

🎯 Scope: {targets} targets × {sessions} sessions"""

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    uid=event.sender_id
    sender=await event.get_sender()
    register_user(uid,sender.username,sender.first_name,sender.last_name or '')
    
    access,status=check_user_access(uid)
    
    if status=='banned':
        await event.respond("🚫 Your access has been revoked.\n\nContact admin for details.")
        return
    
    if status=='not_approved':
        await event.respond(f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   ⏳ APPROVAL PENDING     ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

Hi {sender.first_name}!

Your account needs admin approval.

📋 Status: Waiting for approval
⏳ We'll notify you once approved

💡 Admin will review your request soon.""")
        return
    
    if status=='trial_expired':
        await event.respond(f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   ⏰ TRIAL EXPIRED        ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

Hi {sender.first_name}!

Your trial period has ended.

💡 Contact admin for extended access.""")
        return
    
    user=db.fetchone('SELECT approval_type,trial_expires FROM users WHERE user_id=?',(uid,))
    trial_info=''
    if user and user['approval_type']and user['approval_type'].startswith('trial'):
        if user['trial_expires']:
            expires=datetime.fromisoformat(user['trial_expires'])
            days_left=(expires.date()-datetime.now().date()).days
            trial_info=f"\n⏰ Trial: {days_left} days left"
    
    welcome=f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  🎯 TELEGRAM REPORTER 🎯   ┃
┃     Professional Edition     ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

👋 Welcome, {sender.first_name}!{trial_info}

🌟 Features:
  ├ Multi-Session Management
  ├ Bulk Reporting
  ├ Smart Flood Protection
  ├ Real-time Statistics
  └ Advanced Tools

💡 Select an option below:"""
    
    await event.respond(welcome,buttons=create_main_menu_buttons())

@bot.on(events.CallbackQuery(pattern=b'menu_main'))
async def menu_main(event):
    await event.answer()
    uid=event.sender_id
    
    access,status=check_user_access(uid)
    if not access:
        await event.edit("❌ Access denied. Contact admin.")
        return
    
    stats=get_stats(uid)
    user=db.fetchone('SELECT approval_type,trial_expires FROM users WHERE user_id=?',(uid,))
    trial_info=''
    if user and user['approval_type']and user['approval_type'].startswith('trial'):
        if user['trial_expires']:
            expires=datetime.fromisoformat(user['trial_expires'])
            days_left=(expires.date()-datetime.now().date()).days
            trial_info=f"\n⏰ Trial: {days_left} days"
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃      🎯 MAIN MENU 🎯      ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📊 Your Stats:{trial_info}
  ├ Sessions: {stats['active_sessions']}
  ├ Reports: {stats['total_reports']}
  ├ Success: {stats['success_rate']}%
  └ Streak: {stats['streak_days']} days

💡 Select an option:"""
    
    await event.edit(text,buttons=create_main_menu_buttons())

@bot.on(events.CallbackQuery(pattern=b'report_main'))
async def report_main_menu(event):
    await event.answer()
    uid=event.sender_id
    
    access,status=check_user_access(uid)
    if not access:
        await event.edit("❌ Access denied")
        return
    
    can_report,remaining=check_daily_limit(uid)
    if not can_report:
        await event.edit("❌ Daily limit reached\n\nTry again tomorrow",
                        buttons=[[Button.inline("« Back","menu_main")]])
        return
    
    sessions=get_sessions(uid)
    if not sessions:
        await event.edit("❌ No sessions\n\nAdd sessions first",
                        buttons=[[Button.inline("📱 Add","menu_sessions")],[Button.inline("« Back","menu_main")]])
        return
    
    limit_text=f"\n📊 Daily limit: {remaining} left"if remaining>0 else""
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   🎯 REPORTING CENTER 🎯  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📱 Sessions: {len(sessions)} active{limit_text}

💡 Choose report type:"""
    
    buttons=[
        [Button.inline("👤 User","report_user"),Button.inline("📢 Channel","report_channel")],
        [Button.inline("👥 Group","report_group"),Button.inline("📝 Bulk","report_bulk")],
        [Button.inline("« Back","menu_main")]
    ]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'report_(user|channel|group)'))
async def report_single_start(event):
    await event.answer()
    uid=event.sender_id
    target_type=event.data.decode().split('_')[1]
    
    set_state(uid,f'awaiting_{target_type}_target')
    
    type_emoji={'user':'👤','channel':'📢','group':'👥'}[target_type]
    type_name=target_type.upper()
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  {type_emoji} REPORT {type_name} {type_emoji}  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📝 Send target identifier:
  ├ Username: @example
  ├ ID: 123456789
  ├ Link: t.me/example
  └ Phone: +1234567890

💡 /cancel to abort"""
    
    await event.edit(text,buttons=[[Button.inline("« Cancel","report_main")]])

@bot.on(events.CallbackQuery(pattern=b'report_bulk'))
async def report_bulk_start(event):
    await event.answer()
    uid=event.sender_id
    set_state(uid,'awaiting_bulk_targets')
    
    text="""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   📝 BULK REPORTING 📝    ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📝 Send targets (one per line):

Example:
@user1
@channel1
https://t.me/group1
+1234567890

⚡ Auto type detection
💡 /cancel to abort"""
    
    await event.edit(text,buttons=[[Button.inline("« Cancel","report_main")]])

@bot.on(events.NewMessage(pattern='/cancel'))
async def cancel_handler(event):
    uid=event.sender_id
    clear_state(uid)
    await event.respond("✅ Cancelled",buttons=create_main_menu_buttons())

@bot.on(events.NewMessage(func=lambda e:e.is_private and not e.via_bot_id and not e.document and get_state(e.sender_id)))
async def text_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state:
        return
    
    text=event.text.strip()
    if text.startswith('/'):
        return
    
    if state['state']in['awaiting_user_target','awaiting_channel_target','awaiting_group_target']:
        set_state(uid,'awaiting_reason',target=text,target_type=state['state'].replace('awaiting_','').replace('_target',''))
        
        reason_text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   📋 SELECT REASON 📋     ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

🎯 Target: {text[:30]}

🔍 Choose reason:"""
        
        buttons=[[Button.inline(f"{v[0]}",f"reason_{k}")]for k,v in REASONS.items()]
        buttons.append([Button.inline("« Cancel","report_main")])
        
        await event.respond(reason_text,buttons=buttons)
    
    elif state['state']=='awaiting_bulk_targets':
        targets=[t.strip()for t in text.split('\n')if t.strip()]
        if not targets:
            await event.respond("❌ No valid targets")
            return
        
        set_state(uid,'awaiting_bulk_reason',targets=targets)
        
        reason_text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   📋 SELECT REASON 📋     ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

🎯 Targets: {len(targets)}

🔍 Choose reason:"""
        
        buttons=[[Button.inline(f"{v[0]}",f"bulk_reason_{k}")]for k,v in REASONS.items()]
        buttons.append([Button.inline("« Cancel","report_main")])
        
        await event.respond(reason_text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'reason_(\d+)'))
async def reason_selected(event):
    await event.answer()
    uid=event.sender_id
    state=get_state(uid)
    if not state or'target'not in state:
        await event.edit("❌ Session expired",buttons=[[Button.inline("« Retry","report_main")]])
        return
    
    access,status=check_user_access(uid)
    if not access:
        await event.edit("❌ Access denied")
        clear_state(uid)
        return
    
    can_report,remaining=check_daily_limit(uid)
    if not can_report:
        await event.edit("❌ Daily limit reached",buttons=[[Button.inline("« Back","menu_main")]])
        clear_state(uid)
        return
    
    reason_id=event.data.decode().split('_')[1]
    reason_name,reason_obj=REASONS[reason_id]
    target=state['target']
    
    msg=await event.edit(f"🚀 Initializing...")
    
    sessions=get_sessions(uid)
    if not sessions:
        await msg.edit("❌ No sessions",buttons=[[Button.inline("« Back","report_main")]])
        clear_state(uid)
        return
    
    settings=get_settings(uid)
    reports_per_target=settings['reports_per_target']
    
    sessions_to_use=sessions[:min(len(sessions),reports_per_target)]
    if settings['random_order']:
        random.shuffle(sessions_to_use)
    
    success,failed,skipped=0,0,0
    start_time=time.time()
    processed=0
    total=len(sessions_to_use)
    
    for session in sessions_to_use:
        is_flood,wait_time=check_flood_wait(session['phone'])
        if is_flood and not settings['skip_flood_wait']:
            skipped+=1
            processed+=1
            continue
        
        session_path=os.path.join('sessions_db',session['session_file'])
        client,*_=await create_client(session_path)
        
        if not client:
            failed+=1
            update_session_stats(uid,session['phone'],0,1)
            processed+=1
            continue
        
        try:
            ok,error,exec_time,entity_id=await report_target(client,session['phone'],target,
                                                             reason_obj,uid,reason_name)
            if ok:
                success+=1
                update_session_stats(uid,session['phone'],1,0)
            else:
                failed+=1
                update_session_stats(uid,session['phone'],0,1)
        except Exception as e:
            failed+=1
            update_session_stats(uid,session['phone'],0,1)
        finally:
            try:
                await client.disconnect()
            except:pass
        
        processed+=1
        elapsed=int(time.time()-start_time)
        
        if processed%2==0 or processed==total:
            try:
                await msg.edit(format_report_progress(processed,total,success,failed,skipped,elapsed))
            except:pass
        
        delay=random.uniform(settings['delay_min'],settings['delay_max'])
        await asyncio.sleep(delay)
    
    total_time=time.time()-start_time
    update_stats(uid,success,failed,True,0)
    increment_daily_usage(uid,success)
    
    final_text=format_report_complete(success,failed,skipped,total_time,1,len(sessions_to_use))
    await msg.edit(final_text,buttons=[[Button.inline("🎯 Again","report_main")],
                                       [Button.inline("« Menu","menu_main")]])
    clear_state(uid)

@bot.on(events.CallbackQuery(pattern=rb'bulk_reason_(\d+)'))
async def bulk_reason_selected(event):
    await event.answer()
    uid=event.sender_id
    state=get_state(uid)
    if not state or'targets'not in state:
        await event.edit("❌ Session expired",buttons=[[Button.inline("« Retry","report_main")]])
        return
    
    access,status=check_user_access(uid)
    if not access:
        await event.edit("❌ Access denied")
        clear_state(uid)
        return
    
    can_report,remaining=check_daily_limit(uid)
    if not can_report:
        await event.edit("❌ Daily limit reached",buttons=[[Button.inline("« Back","menu_main")]])
        clear_state(uid)
        return
    
    reason_id=event.data.decode().split('_')[2]
    reason_name,reason_obj=REASONS[reason_id]
    targets=state['targets']
    
    sessions=get_sessions(uid)
    if not sessions:
        await event.edit("❌ No sessions",buttons=[[Button.inline("« Back","report_main")]])
        clear_state(uid)
        return
    
    settings=get_settings(uid)
    reports_per_target=settings['reports_per_target']
    
    total_operations=len(targets)*min(len(sessions),reports_per_target)
    
    if remaining>0 and total_operations>remaining:
        await event.edit(f"❌ Limit exceeded\n\nRequests: {total_operations}\nRemaining: {remaining}",
                        buttons=[[Button.inline("« Back","report_main")]])
        clear_state(uid)
        return
    
    msg=await event.edit("🚀 Starting bulk report...")
    
    success,failed,skipped=0,0,0
    start_time=time.time()
    processed=0
    
    for target in targets:
        sessions_to_use=sessions[:min(len(sessions),reports_per_target)]
        if settings['random_order']:
            random.shuffle(sessions_to_use)
        
        for session in sessions_to_use:
            is_flood,wait_time=check_flood_wait(session['phone'])
            if is_flood and not settings['skip_flood_wait']:
                skipped+=1
                processed+=1
                continue
            
            session_path=os.path.join('sessions_db',session['session_file'])
            client,*_=await create_client(session_path)
            
            if not client:
                failed+=1
                update_session_stats(uid,session['phone'],0,1)
                processed+=1
                continue
            
            try:
                ok,error,exec_time,entity_id=await report_target(client,session['phone'],target,
                                                                 reason_obj,uid,reason_name)
                if ok:
                    success+=1
                    update_session_stats(uid,session['phone'],1,0)
                else:
                    failed+=1
                    update_session_stats(uid,session['phone'],0,1)
            except Exception as e:
                failed+=1
                update_session_stats(uid,session['phone'],0,1)
            finally:
                try:
                    await client.disconnect()
                except:pass
            
            processed+=1
            elapsed=int(time.time()-start_time)
            
            if processed%5==0 or processed==total_operations:
                try:
                    await msg.edit(format_report_progress(processed,total_operations,success,
                                                         failed,skipped,elapsed))
                except:pass
            
            delay=random.uniform(settings['delay_min'],settings['delay_max'])
            await asyncio.sleep(delay)
    
    total_time=time.time()-start_time
    update_stats(uid,success,failed,True,0)
    increment_daily_usage(uid,success)
    
    final_text=format_report_complete(success,failed,skipped,total_time,len(targets),
                                      min(len(sessions),reports_per_target))
    await msg.edit(final_text,buttons=[[Button.inline("🎯 Again","report_main")],
                                       [Button.inline("« Menu","menu_main")]])
    clear_state(uid)

@bot.on(events.CallbackQuery(pattern=b'menu_sessions'))
async def menu_sessions(event):
    await event.answer()
    uid=event.sender_id
    
    access,status=check_user_access(uid)
    if not access:
        await event.edit("❌ Access denied")
        return
    
    sessions=get_sessions(uid)
    user=db.fetchone('SELECT max_sessions FROM users WHERE user_id=?',(uid,))
    max_limit=user['max_sessions']if user and user['max_sessions']>0 else'Unlimited'
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  📱 SESSION MANAGER 📱   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📊 Sessions: {len(sessions)}/{max_limit}

"""
    
    if sessions:
        for idx,s in enumerate(sessions[:5],1):
            health='🟢'if s['health_score']>=80 else'🟡'if s['health_score']>=50 else'🔴'
            text+=f"{idx}. {health} {s['phone']}\n"
            text+=f"   └ {s['success_reports']}/{s['total_reports']} reports\n"
        if len(sessions)>5:
            text+=f"\n...+{len(sessions)-5} more"
    else:
        text+="❌ No sessions\n\n💡 Upload .session or .zip file"
    
    buttons=[
        [Button.inline("➕ Add","session_add"),Button.inline("➖ Remove","session_remove")],
        [Button.inline("📋 List","session_list"),Button.inline("🔄 Refresh","menu_sessions")],
        [Button.inline("« Back","menu_main")]
    ]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'menu_settings'))
async def menu_settings(event):
    await event.answer()
    uid=event.sender_id
    
    access,status=check_user_access(uid)
    if not access:
        await event.edit("❌ Access denied")
        return
    
    settings=get_settings(uid)
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃    ⚙️ SETTINGS ⚙️         ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

⏱️ Delay: {settings['delay_min']}-{settings['delay_max']}s
📊 Reports/Target: {settings['reports_per_target']}
🔄 Parallel: {settings['parallel_sessions']}
🎲 Random: {'✅'if settings['random_order']else'❌'}
🔁 Retry: {'✅'if settings['retry_failed']else'❌'}
⏭️ Skip Flood: {'✅'if settings['skip_flood_wait']else'❌'}"""
    
    buttons=[
        [Button.inline("⏱️ Delay","set_delay"),Button.inline("📊 Reports","set_reports")],
        [Button.inline("🔄 Parallel","set_parallel"),Button.inline("🎲 Random","toggle_random")],
        [Button.inline("🔁 Retry","toggle_retry"),Button.inline("⏭️ Skip","toggle_skip")],
        [Button.inline("« Back","menu_main")]
    ]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'menu_stats'))
async def menu_stats(event):
    await event.answer()
    uid=event.sender_id
    
    access,status=check_user_access(uid)
    if not access:
        await event.edit("❌ Access denied")
        return
    
    stats=get_stats(uid)
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   📊 STATISTICS 📊        ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📈 Performance:
  ├ Reports: {stats['total_reports']}
  ├ Success: ✅ {stats['successful_reports']}
  ├ Failed: ❌ {stats['failed_reports']}
  └ Rate: {stats['success_rate']}%

🎯 Activity:
  ├ Targets: {stats['targets_reported']}
  ├ Groups Joined: {stats['groups_joined']}
  └ Groups Left: {stats['groups_left']}

📱 Sessions:
  ├ Total: {stats['total_sessions']}
  └ Active: {stats['active_sessions']}

🔥 Streak:
  ├ Current: {stats['streak_days']} days
  └ Best: {stats['best_streak']} days"""
    
    if stats['last_report_date']:
        last=datetime.fromisoformat(stats['last_report_date'])
        text+=f"\n\n⏰ Last: {last.strftime('%Y-%m-%d %H:%M')}"
    
    buttons=[
        [Button.inline("🔄 Refresh","menu_stats")],
        [Button.inline("« Back","menu_main")]
    ]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'menu_tools'))
async def menu_tools(event):
    await event.answer()
    uid=event.sender_id
    
    access,status=check_user_access(uid)
    if not access:
        await event.edit("❌ Access denied")
        return
    
    text="""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃    🛠️ TOOLS 🛠️            ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

🔧 Available Tools:

📤 Export:
  └ Export sessions/logs

👥 Groups:
  ├ Bulk join
  └ Bulk leave

🗑️ Maintenance:
  ├ Clear cache
  └ Clean flood waits"""
    
    buttons=[
        [Button.inline("📤 Export","tools_export"),Button.inline("👥 Groups","tools_groups")],
        [Button.inline("🗑️ Clean","tools_clean")],
        [Button.inline("« Back","menu_main")]
    ]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'menu_help'))
async def menu_help(event):
    await event.answer()
    
    text="""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃      ℹ️ HELP ℹ️            ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📚 Quick Guide:

1️⃣ Add Sessions:
  └ Upload .session/.zip files

2️⃣ Report Targets:
  ├ Single: User/Channel/Group
  └ Bulk: Multiple targets

3️⃣ Settings:
  ├ Adjust delays
  ├ Reports per target
  └ Parallel sessions

💡 Tips:
  ├ Higher delays = safer
  ├ Monitor health scores
  └ Check limits regularly"""
    
    buttons=[[Button.inline("« Back","menu_main")]]
    await event.edit(text,buttons=buttons)

@bot.on(events.NewMessage(pattern='/admin'))
async def admin_panel(event):
    uid=event.sender_id
    if not is_admin(uid):
        return
    
    pending=db.fetchall('SELECT COUNT(*) as cnt FROM approval_requests WHERE status="pending"')
    pending_count=pending[0]['cnt']if pending else 0
    total_users=db.fetchall('SELECT COUNT(*) as cnt FROM users')
    total_count=total_users[0]['cnt']if total_users else 0
    approved=db.fetchall('SELECT COUNT(*) as cnt FROM users WHERE is_approved=1')
    approved_count=approved[0]['cnt']if approved else 0
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   👑 ADMIN PANEL 👑       ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📊 Overview:
  ├ Total Users: {total_count}
  ├ Approved: {approved_count}
  └ Pending: {pending_count}

💡 Select action:"""
    
    buttons=[
        [Button.inline("⏳ Pending Requests","admin_pending")],
        [Button.inline("👥 Manage Users","admin_users")],
        [Button.inline("📊 Stats","admin_stats")],
        [Button.inline("« Close","delete_msg")]
    ]
    await event.respond(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b'admin_pending'))
async def admin_pending_requests(event):
    await event.answer()
    uid=event.sender_id
    if not is_admin(uid):
        return
    
    requests=db.fetchall('''SELECT * FROM approval_requests WHERE status="pending" 
                           ORDER BY requested_date DESC LIMIT 10''')
    
    if not requests:
        await event.edit("✅ No pending requests",buttons=[[Button.inline("« Back",b"/admin")]])
        return
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  ⏳ PENDING APPROVALS ⏳  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📋 {len(requests)} requests:

"""
    
    for idx,req in enumerate(requests[:5],1):
        date=datetime.fromisoformat(req['requested_date']).strftime('%Y-%m-%d')
        text+=f"{idx}. @{req['username']or'N/A'}\n"
        text+=f"   └ {req['first_name']} | {date}\n"
    
    buttons=[]
    for req in requests[:5]:
        buttons.append([Button.inline(f"Review: {req['first_name'][:15]}",f"admin_review_{req['id']}")])
    buttons.append([Button.inline("« Back",b"admin_panel")])
    
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'admin_review_(\d+)'))
async def admin_review_request(event):
    await event.answer()
    uid=event.sender_id
    if not is_admin(uid):
        return
    
    req_id=int(event.data.decode().split('_')[2])
    req=db.fetchone('SELECT * FROM approval_requests WHERE id=?',(req_id,))
    
    if not req:
        await event.edit("❌ Request not found")
        return
    
    text=f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   👤 USER REVIEW 👤       ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📋 Details:
  ├ Name: {req['first_name']}
  ├ Username: @{req['username']or'N/A'}
  ├ ID: {req['user_id']}
  └ Date: {datetime.fromisoformat(req['requested_date']).strftime('%Y-%m-%d')}

💡 Choose action:"""
    
    buttons=[
        [Button.inline("✅ Full Access",f"approve_full_{req['user_id']}")],
        [Button.inline("⏰ 3 Days Trial",f"approve_trial3_{req['user_id']}")],
        [Button.inline("⏰ 5 Days Trial",f"approve_trial5_{req['user_id']}")],
        [Button.inline("⏰ 7 Days Trial",f"approve_trial7_{req['user_id']}")],
        [Button.inline("❌ Reject",f"reject_{req['user_id']}")],
        [Button.inline("« Back","admin_pending")]
    ]
    await event.edit(text,buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'approve_(full|trial3|trial5|trial7)_(\d+)'))
async def admin_approve_user(event):
    await event.answer()
    admin_uid=event.sender_id
    if not is_admin(admin_uid):
        return
    
    parts=event.data.decode().split('_')
    approval_type=parts[1]
    user_id=int(parts[2])
    
    now=datetime.now().isoformat()
    trial_expires=None
    max_sessions=0
    max_reports=0
    
    if approval_type=='full':
        approval_label='lifetime'
        max_sessions=0
        max_reports=0
    elif approval_type=='trial3':
        approval_label='trial_3'
        trial_expires=(datetime.now()+timedelta(days=3)).isoformat()
        max_sessions=5
        max_reports=100
    elif approval_type=='trial5':
        approval_label='trial_5'
        trial_expires=(datetime.now()+timedelta(days=5)).isoformat()
        max_sessions=10
        max_reports=200
    elif approval_type=='trial7':
        approval_label='trial_7'
        trial_expires=(datetime.now()+timedelta(days=7)).isoformat()
        max_sessions=15
        max_reports=300
    
    db.execute('''UPDATE users SET is_approved=1,approval_type=?,trial_expires=?,
                  max_sessions=?,max_reports_per_day=?,approved_by=?,approved_date=? 
                  WHERE user_id=?''',
               (approval_label,trial_expires,max_sessions,max_reports,admin_uid,now,user_id))
    
    db.execute('UPDATE approval_requests SET status="approved",reviewed_by=?,reviewed_date=? WHERE user_id=?',
               (admin_uid,now,user_id))
    
    try:
        if approval_type=='full':
            await bot.send_message(user_id,f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   ✅ APPROVED ✅          ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

🎉 Congratulations!

Your account has been approved with full access!

🌟 Unlimited features
⚡ Start using /start""",buttons=[[Button.inline("🚀 Start",b"/start")]])
        else:
            days=approval_type.replace('trial','')
            await bot.send_message(user_id,f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   ✅ TRIAL APPROVED ✅    ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

🎉 Trial activated!

⏰ Duration: {days} days
📱 Max Sessions: {max_sessions}
📊 Daily Reports: {max_reports}

⚡ Start now with /start""",buttons=[[Button.inline("🚀 Start",b"/start")]])
    except:pass
    
    await event.edit(f"✅ User {user_id} approved with {approval_label}",
                    buttons=[[Button.inline("« Back","admin_pending")]])

@bot.on(events.CallbackQuery(pattern=rb'reject_(\d+)'))
async def admin_reject_user(event):
    await event.answer()
    admin_uid=event.sender_id
    if not is_admin(admin_uid):
        return
    
    user_id=int(event.data.decode().split('_')[1])
    now=datetime.now().isoformat()
    
    db.execute('UPDATE approval_requests SET status="rejected",reviewed_by=?,reviewed_date=? WHERE user_id=?',
               (admin_uid,now,user_id))
    
    try:
        await bot.send_message(user_id,"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   ❌ REQUEST DENIED ❌    ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

Your access request was not approved.

💡 Contact admin for details.""")
    except:pass
    
    await event.edit(f"❌ User {user_id} rejected",buttons=[[Button.inline("« Back","admin_pending")]])

@bot.on(events.CallbackQuery(pattern=b'delete_msg'))
async def delete_message(event):
    await event.delete()

@bot.on(events.NewMessage(func=lambda e:e.document and e.is_private))
async def file_handler(event):
    uid=event.sender_id
    
    access,status=check_user_access(uid)
    if not access:
        await event.respond("❌ Access denied. Request approval first.")
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
            ok,phone,name,username=await verify_session(path.replace('.session',''))
            if ok:
                sname=f"{uid}_{phone.replace('+','').replace(' ','')}"
                final=os.path.join('sessions_db',sname+'.session')
                shutil.move(path,final)
                
                added=add_session(uid,phone,name,username or'',sname+'.session')
                if added:
                    await msg.edit(f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   ✅ SESSION ADDED ✅     ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📱 {phone}
👤 {name}
@{username or'N/A'}

🎯 Ready to use!""",buttons=[[Button.inline("📱 Sessions","menu_sessions")],
                                                       [Button.inline("🎯 Report","report_main")]])
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
                
                await msg.edit(f"📦 Found {total} sessions\n⏳ Verifying...")
                
                for idx,f in enumerate(session_files,1):
                    try:
                        zf.extract(f,'temp_files')
                        tpath=os.path.join('temp_files',f)
                        ok,phone,name,username=await verify_session(tpath.replace('.session',''))
                        if ok:
                            sname=f"{uid}_{phone.replace('+','').replace(' ','')}"
                            final=os.path.join('sessions_db',sname+'.session')
                            shutil.move(tpath,final)
                            if add_session(uid,phone,name,username or'',sname+'.session'):
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
                            except:pass
                    except Exception as e:
                        logger.error(f"Extract: {e}")
                        failed+=1
            
            await msg.edit(f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   📦 ZIP COMPLETE 📦      ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📊 Results:
  ├ Total: {total}
  ├ Added: ✅ {added}
  └ Failed: ❌ {failed}

{'🎯 Sessions ready!'if added>0 else''}""",buttons=[[Button.inline("📱 Sessions","menu_sessions")],
                                                [Button.inline("« Menu","menu_main")]])
        except Exception as e:
            await msg.edit(f"❌ ZIP Error: {str(e)[:80]}",buttons=[[Button.inline("« Back","menu_sessions")]])
        finally:
            try:
                os.remove(zpath)
            except:pass

def main():
    banner="""
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                                   ┃
┃       🎯 TELEGRAM REPORTER PROFESSIONAL 🎯      ┃
┃              Advanced Edition v2.0                ┃
┃                                                   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

✨ Features:
  ├ 🔐 Admin Approval System
  ├ ⏰ Trial Period Support (3/5/7 days)
  ├ 📊 Daily Limit Controls
  ├ 📱 Session Limit Management
  ├ 🎯 Smart Reporting Engine
  ├ 🛡️ Flood Protection
  ├ 📈 Advanced Statistics
  ├ 💎 Professional UI/UX
  └ 🚀 High Performance

🔥 System Status:
  ├ Database: ✅ Connected
  ├ Bot: ✅ Online
  ├ API: ✅ Ready
  └ Admin: ✅ Configured

⚡ Production ready!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📱 Press Ctrl+C to stop
💡 All features operational
"""
    print(banner)
    
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
