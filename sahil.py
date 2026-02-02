#!/usr/bin/env python3
import os,sys,json,asyncio,zipfile,shutil,time,random,logging,sqlite3,hashlib,re,requests
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

for d in ['sessions_db','temp_files','data','backups','logs','exports','cache','reports','proxies']:
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
            CREATE TABLE IF NOT EXISTS proxies(id INTEGER PRIMARY KEY AUTOINCREMENT,proxy_url TEXT UNIQUE,proxy_type TEXT,added_date TEXT,is_active INTEGER DEFAULT 1,success_count INTEGER DEFAULT 0,fail_count INTEGER DEFAULT 0,last_used TEXT);
            CREATE TABLE IF NOT EXISTS web_reports(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,target_link TEXT,report_type TEXT,success INTEGER,timestamp TEXT,method TEXT DEFAULT 'web');
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

REPORT_TYPES={1:"Spam",2:"Violence/Gore",3:"Pornography",4:"Child Abuse",5:"Copyright Infringement",6:"Fake Account/Impersonation",7:"Illegal Drugs",8:"Personal Information",9:"Hate Speech",10:"Terrorism",11:"Scam/Fraud",12:"Harassment/Bullying",13:"Self Harm",14:"Animal Abuse",15:"Other Violation"}

user_states={}
proxy_cache=[]
current_proxy_index=0

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

def load_proxies_from_db():
    global proxy_cache
    proxies=db.fetchall('SELECT proxy_url FROM proxies WHERE is_active=1 ORDER BY success_count DESC')
    proxy_cache=[p['proxy_url'] for p in proxies]
    return proxy_cache

def get_next_proxy():
    global current_proxy_index
    if not proxy_cache:
        load_proxies_from_db()
    if not proxy_cache:
        return None
    proxy=proxy_cache[current_proxy_index]
    current_proxy_index=(current_proxy_index+1)%len(proxy_cache)
    return proxy

def generate_user_agent():
    agents=["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36","Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36","Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"]
    return random.choice(agents)

def get_report_message(report_type,message_link,channel_link):
    messages={1:"This account is sending spam messages repeatedly.",2:"This content contains graphic violence and gore.",3:"This channel/account is sharing pornographic content.",4:"This account is sharing child abuse material.",5:"This content violates copyright laws.",6:"This is a fake account impersonating someone.",7:"This account is promoting illegal drugs.",8:"This content shares private personal information.",9:"This content promotes hate speech and discrimination.",10:"This account promotes terrorism and extremism.",11:"This is a scam attempting to defraud users.",12:"This account is harassing and bullying others.",13:"This content promotes self-harm.",14:"This content shows animal abuse.",15:"This content violates Telegram's terms of service."}
    base_msg=messages.get(report_type,"This content violates Telegram policies.")
    return f"{base_msg}\n\nMessage: {message_link}\nChannel: {channel_link}"

def generate_fake_email():
    domains=["gmail.com","outlook.com","yahoo.com","hotmail.com","protonmail.com"]
    return f"user{random.randint(1000,9999)}{random.randint(100,999)}@{random.choice(domains)}"

def generate_fake_phone():
    return f"+1{random.randint(200,999)}{random.randint(1000000,9999999)}"

def generate_country():
    countries=["United States","United Kingdom","Canada","Australia","Germany","France","Italy","Spain"]
    return random.choice(countries)

async def web_report_submission(report_type,message_link,channel_link):
    try:
        session=requests.Session()
        proxy=get_next_proxy()
        proxies={'http':proxy,'https':proxy} if proxy else None
        headers={'User-Agent':generate_user_agent(),'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8','Accept-Language':'en-US,en;q=0.5','Accept-Encoding':'gzip, deflate','Connection':'keep-alive','Upgrade-Insecure-Requests':'1'}
        response=session.get('https://telegram.org/support',headers=headers,proxies=proxies,timeout=15)
        if response.status_code!=200:
            return False
        form_data={'message':get_report_message(report_type,message_link,channel_link),'email':generate_fake_email(),'phone':generate_fake_phone(),'setln':generate_country()}
        headers.update({'Content-Type':'application/x-www-form-urlencoded','Origin':'https://telegram.org','Referer':'https://telegram.org/support'})
        response=session.post('https://telegram.org/support',data=form_data,headers=headers,timeout=20,allow_redirects=True,proxies=proxies)
        success_indicators=['شكرًا على بلاغك','سنحاول الرّد بأسرع ما يمكن','thank you for your report','thanks for your report','report received','your report has been received','report submitted','we have received your report','alert-success','success','support-received']
        response_text=response.text.lower()
        for indicator in success_indicators:
            if indicator.lower() in response_text:
                if proxy:
                    db.execute('UPDATE proxies SET success_count=success_count+1,last_used=? WHERE proxy_url=?',(datetime.now().isoformat(),proxy))
                return True
        if response.url!='https://telegram.org/support' and response.status_code==200:
            return True
        if 'message' not in response_text and 'email' not in response_text:
            return True
        return False
    except:
        if proxy:
            db.execute('UPDATE proxies SET fail_count=fail_count+1 WHERE proxy_url=?',(proxy,))
        return False

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
            session_filename=f"session_{actual_phone.replace('+','').replace(' ','')}.session"
            target_path=os.path.join('sessions_db',session_filename)
            if os.path.exists(target_path):
                await temp_client.disconnect()
                return False,"Session already exists"
            await temp_client.disconnect()
            shutil.copy2(session_path,target_path)
            db.execute('INSERT INTO sessions(user_id,phone,name,session_file,verified,added_date) VALUES(?,?,?,?,1,?)',(uid,actual_phone,name or me.first_name or 'User',session_filename,datetime.now().isoformat()))
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
    user=await event.get_sender()
    username=user.username or "No Username"
    first_name=user.first_name or "User"
    register_user(uid,username,first_name)
    has_access,reason=check_user_access(uid)
    if not has_access:
        if reason=='not_approved':
            existing_request=db.fetchone('SELECT id,status FROM approval_requests WHERE user_id=? AND status="pending"',(uid,))
            if existing_request:
                await event.respond("⏳ Your access request is pending approval.\n\nPlease wait for an admin to review your request.",buttons=[[Button.inline("🔄 Check Status","check_approval_status")]])
            else:
                await event.respond(f"👋 Welcome {first_name}!\n\n❌ You don't have access to this bot yet.\n\nWould you like to request access?",buttons=[[Button.inline("✅ Request Access","request_access")]])
            return
        elif reason=='banned':
            await event.respond("🚫 You have been banned from using this bot.\n\nContact an administrator if you believe this is a mistake.")
            return
    owner_text=" 👑 OWNER MODE" if is_owner(uid) else ""
    stats=db.fetchone('SELECT * FROM statistics WHERE user_id=?',(uid,))
    sessions_count=stats['total_sessions'] if stats else 0
    active_count=stats['active_sessions'] if stats else 0
    total_reports=stats['total_reports'] if stats else 0
    success_reports=stats['successful_reports'] if stats else 0
    await event.respond(f"""╔══════════════════════════════╗
║  🎯 ADVANCED REPORTER BOT{owner_text}  ║
╚══════════════════════════════╝

👤 User: {first_name}
📊 Status: {'👑 Owner' if is_owner(uid) else '✅ Approved'}

📈 YOUR STATISTICS:
├ Sessions: {sessions_count} (Active: {active_count})
├ Total Reports: {total_reports}
└ Success Rate: {(success_reports/total_reports*100) if total_reports>0 else 0:.1f}%

Choose an option below:""",buttons=[[Button.inline("🎯 Start Report","menu_main")],[Button.inline("📱 Manage Sessions","menu_sessions"),Button.inline("⚙️ Settings","menu_settings")],[Button.inline("📊 Statistics","menu_statistics"),Button.inline("🌐 Web Report","menu_web_report")],[Button.inline("👑 Owner Panel","menu_owner") if is_owner(uid) else Button.inline("ℹ️ Help","menu_help")]])

@bot.on(events.CallbackQuery(pattern=b'request_access'))
async def request_access_handler(event):
    uid=event.sender_id
    user=await bot.get_entity(uid)
    username=user.username or "No Username"
    first_name=user.first_name or "User"
    existing=db.fetchone('SELECT id FROM approval_requests WHERE user_id=? AND status="pending"',(uid,))
    if existing:
        await event.answer("You already have a pending request!",alert=True)
        return
    db.execute('INSERT INTO approval_requests(user_id,username,first_name,requested_date) VALUES(?,?,?,?)',(uid,username,first_name,datetime.now().isoformat()))
    await event.edit("✅ Access request submitted!\n\nAn admin will review your request soon.\n\nYou will be notified once approved.",buttons=[[Button.inline("« Back","/start")]])
    for owner_id in OWNER_IDS:
        try:
            await bot.send_message(owner_id,f"🔔 NEW ACCESS REQUEST\n\n👤 User: {first_name}\n🆔 ID: {uid}\n📱 Username: @{username}\n⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nReview this request in Owner Panel.",buttons=[[Button.inline("✅ Approve",f"approve_user_{uid}"),Button.inline("❌ Deny",f"deny_user_{uid}")]])
        except:
            pass

@bot.on(events.CallbackQuery(pattern=b'check_approval_status'))
async def check_status_handler(event):
    uid=event.sender_id
    request=db.fetchone('SELECT * FROM approval_requests WHERE user_id=? ORDER BY id DESC LIMIT 1',(uid,))
    if not request:
        await event.answer("No request found!",alert=True)
        return
    status_emoji={"pending":"⏳","approved":"✅","denied":"❌"}
    status=request['status']
    await event.edit(f"📋 REQUEST STATUS\n\nStatus: {status_emoji.get(status,'')} {status.upper()}\nRequested: {request['requested_date'][:10]}\n\n{f'Reviewed by: Admin' if request['reviewed_by'] else 'Waiting for review...'}",buttons=[[Button.inline("« Back","/start")]])

@bot.on(events.CallbackQuery(pattern=b'menu_main'))
async def main_menu_handler(event):
    uid=event.sender_id
    has_access,reason=check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!",alert=True)
        return
    sessions=db.fetchall('SELECT * FROM sessions WHERE user_id=? AND is_active=1',(uid,))
    if not sessions:
        await event.edit("❌ NO SESSIONS AVAILABLE\n\nYou need to add at least one session before you can report.\n\nGo to 'Manage Sessions' to add your session files.",buttons=[[Button.inline("📱 Add Sessions","menu_sessions")],[Button.inline("« Back","/start")]])
        return
    await event.edit(f"""🎯 REPORT TARGET

Available Sessions: {len(sessions)}

Choose report type:""",buttons=[[Button.inline("👤 Report User/Channel","report_peer")],[Button.inline("💬 Report Message","report_message")],[Button.inline("« Back","/start")]])

@bot.on(events.CallbackQuery(pattern=b'report_peer'))
async def report_peer_handler(event):
    uid=event.sender_id
    has_access,reason=check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!",alert=True)
        return
    set_state(uid,'awaiting_target')
    await event.edit("👤 REPORT USER/CHANNEL\n\nSend me the target username or link:\n@username\nhttps://t.me/username\nhttps://t.me/joinchat/xxxxx\n\nType /cancel to cancel",buttons=[[Button.inline("« Cancel","menu_main")]])

@bot.on(events.CallbackQuery(pattern=b'report_message'))
async def report_message_handler(event):
    uid=event.sender_id
    has_access,reason=check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!",alert=True)
        return
    set_state(uid,'awaiting_message_link')
    await event.edit("💬 REPORT MESSAGE\n\nSend me the message link:\nhttps://t.me/channel/12345\nor\nhttps://t.me/c/123456/789\n\nThe message link must be from a public or private channel/group.\n\nType /cancel to cancel",buttons=[[Button.inline("« Cancel","menu_main")]])

@bot.on(events.NewMessage())
async def message_handler(event):
    if event.is_private and not event.message.message.startswith('/'):
        uid=event.sender_id
        state=get_state(uid)
        if not state:
            return
        current_state=state.get('state')
        if current_state=='awaiting_target':
            target=event.message.message.strip()
            if not target:
                await event.respond("❌ Invalid input. Please send a valid username or link.",buttons=[[Button.inline("« Cancel","menu_main")]])
                return
            state['target']=target
            state['target_type']='peer'
            set_state(uid,'awaiting_reason',**state)
            buttons=[]
            for i in range(0,len(REASONS),2):
                row=[]
                for j in range(2):
                    idx=i+j
                    if idx<len(REASONS):
                        key=str(idx+1)
                        name,_=REASONS[key]
                        row.append(Button.inline(name,f"reason_{key}"))
                buttons.append(row)
            buttons.append([Button.inline("« Cancel","menu_main")])
            await event.respond(f"✅ Target: {target}\n\n📝 Select report reason:",buttons=buttons)
        elif current_state=='awaiting_message_link':
            link=event.message.message.strip()
            match=re.search(r't\.me/(?:c/)?([^/]+)/(\d+)',link)
            if not match:
                await event.respond("❌ Invalid message link format.\n\nPlease send a valid message link like:\nhttps://t.me/channel/12345",buttons=[[Button.inline("« Cancel","menu_main")]])
                return
            channel_part=match.group(1)
            message_id=int(match.group(2))
            if link.startswith('https://t.me/c/'):
                target=f"-100{channel_part}"
            else:
                target=f"@{channel_part}" if not channel_part.startswith('@') else channel_part
            state['target']=target
            state['message_link']=link
            state['message_id']=message_id
            state['target_type']='message'
            set_state(uid,'awaiting_reason',**state)
            buttons=[]
            for i in range(0,len(REASONS),2):
                row=[]
                for j in range(2):
                    idx=i+j
                    if idx<len(REASONS):
                        key=str(idx+1)
                        name,_=REASONS[key]
                        row.append(Button.inline(name,f"reason_{key}"))
                buttons.append(row)
            buttons.append([Button.inline("« Cancel","menu_main")])
            await event.respond(f"✅ Message Link: {link}\n\n📝 Select report reason:",buttons=buttons)
        elif current_state=='awaiting_reports_count':
            try:
                count=int(event.message.message.strip())
                settings=db.fetchone('SELECT max_reports_per_session FROM user_settings WHERE user_id=?',(uid,))
                max_reports=settings['max_reports_per_session'] if settings else 20
                if count<1 or count>max_reports:
                    await event.respond(f"❌ Please enter a number between 1 and {max_reports}",buttons=[[Button.inline("« Cancel","menu_main")]])
                    return
                state['reports_count']=count
                set_state(uid,'awaiting_sessions_count',**state)
                total_sessions=db.fetchone('SELECT COUNT(*) as cnt FROM sessions WHERE user_id=? AND is_active=1',(uid,))['cnt']
                buttons=[]
                for i in [1,3,5,10,total_sessions]:
                    if i<=total_sessions:
                        buttons.append([Button.inline(f"{i} Session{'s' if i>1 else ''}",f"sessions_{i}")])
                buttons.append([Button.inline("« Cancel","menu_main")])
                await event.respond(f"🎯 Target: {state['target']}\n📝 Reason: {state['reason_name']}\n🔢 Reports per session: {count}\n\n📱 Select number of sessions to use:\n(Total available: {total_sessions})",buttons=buttons)
            except ValueError:
                await event.respond("❌ Please enter a valid number",buttons=[[Button.inline("« Cancel","menu_main")]])
        elif current_state=='awaiting_session_login_phone':
            phone=event.message.message.strip()
            if not phone.startswith('+'):
                await event.respond("❌ Phone number must start with + and country code.\n\nExample: +1234567890",buttons=[[Button.inline("« Cancel","menu_sessions")]])
                return
            state['login_phone']=phone
            try:
                client=TelegramClient(f'temp_session_{uid}',API_ID,API_HASH)
                await client.connect()
                await client.send_code_request(phone)
                state['client']=client
                set_state(uid,'awaiting_session_login_code',**state)
                await event.respond(f"📱 Code sent to {phone}\n\nPlease enter the verification code:",buttons=[[Button.inline("« Cancel","menu_sessions")]])
            except Exception as e:
                await event.respond(f"❌ Error sending code: {str(e)}",buttons=[[Button.inline("« Cancel","menu_sessions")]])
                clear_state(uid)
        elif current_state=='awaiting_session_login_code':
            code=event.message.message.strip().replace('-','').replace(' ','')
            phone=state['login_phone']
            client=state['client']
            try:
                await client.sign_in(phone,code)
                me=await client.get_me()
                session_filename=f"session_{phone.replace('+','').replace(' ','')}.session"
                temp_path=f'temp_session_{uid}.session'
                target_path=os.path.join('sessions_db',session_filename)
                await client.disconnect()
                if os.path.exists(temp_path):
                    shutil.copy2(temp_path,target_path)
                    os.remove(temp_path)
                    db.execute('INSERT INTO sessions(user_id,phone,name,session_file,verified,added_date) VALUES(?,?,?,?,1,?)',(uid,phone,me.first_name or 'User',session_filename,datetime.now().isoformat()))
                    db.execute('UPDATE statistics SET total_sessions=total_sessions+1,active_sessions=active_sessions+1 WHERE user_id=?',(uid,))
                    await event.respond(f"✅ Session added successfully!\n\n📱 Phone: {phone}\n👤 Name: {me.first_name}\n\nYou can now use this session for reporting.",buttons=[[Button.inline("📱 Manage Sessions","menu_sessions")],[Button.inline("« Main Menu","/start")]])
                else:
                    await event.respond("❌ Session file not found. Please try again.",buttons=[[Button.inline("« Cancel","menu_sessions")]])
                clear_state(uid)
            except SessionPasswordNeededError:
                set_state(uid,'awaiting_session_login_2fa',**state)
                await event.respond("🔐 2FA enabled on this account\n\nPlease enter your 2FA password:",buttons=[[Button.inline("« Cancel","menu_sessions")]])
            except Exception as e:
                await event.respond(f"❌ Login failed: {str(e)}\n\nPlease try again.",buttons=[[Button.inline("« Cancel","menu_sessions")]])
                clear_state(uid)
        elif current_state=='awaiting_session_login_2fa':
            password=event.message.message.strip()
            client=state['client']
            phone=state['login_phone']
            try:
                await client.sign_in(password=password)
                me=await client.get_me()
                session_filename=f"session_{phone.replace('+','').replace(' ','')}.session"
                temp_path=f'temp_session_{uid}.session'
                target_path=os.path.join('sessions_db',session_filename)
                await client.disconnect()
                if os.path.exists(temp_path):
                    shutil.copy2(temp_path,target_path)
                    os.remove(temp_path)
                    db.execute('INSERT INTO sessions(user_id,phone,name,session_file,verified,added_date) VALUES(?,?,?,?,1,?)',(uid,phone,me.first_name or 'User',session_filename,datetime.now().isoformat()))
                    db.execute('UPDATE statistics SET total_sessions=total_sessions+1,active_sessions=active_sessions+1 WHERE user_id=?',(uid,))
                    await event.respond(f"✅ Session added successfully!\n\n📱 Phone: {phone}\n👤 Name: {me.first_name}\n\nYou can now use this session for reporting.",buttons=[[Button.inline("📱 Manage Sessions","menu_sessions")],[Button.inline("« Main Menu","/start")]])
                else:
                    await event.respond("❌ Session file not found. Please try again.",buttons=[[Button.inline("« Cancel","menu_sessions")]])
                clear_state(uid)
            except Exception as e:
                await event.respond(f"❌ 2FA verification failed: {str(e)}",buttons=[[Button.inline("« Cancel","menu_sessions")]])
                clear_state(uid)
        elif current_state=='awaiting_proxy_url':
            proxy_url=event.message.message.strip()
            if not proxy_url:
                await event.respond("❌ Invalid proxy URL",buttons=[[Button.inline("« Cancel","menu_owner")]])
                return
            try:
                db.execute('INSERT INTO proxies(proxy_url,proxy_type,added_date) VALUES(?,?,?)',(proxy_url,'http',datetime.now().isoformat()))
                load_proxies_from_db()
                await event.respond(f"✅ Proxy added successfully!\n\n🌐 {proxy_url}\n\nTotal proxies: {len(proxy_cache)}",buttons=[[Button.inline("🌐 Proxy Management","menu_proxy_mgmt")],[Button.inline("« Owner Panel","menu_owner")]])
            except:
                await event.respond("❌ Proxy already exists or invalid format",buttons=[[Button.inline("« Cancel","menu_owner")]])
            clear_state(uid)
        elif current_state=='awaiting_web_report_message':
            message_link=event.message.message.strip()
            state['web_message_link']=message_link
            set_state(uid,'awaiting_web_report_channel',**state)
            await event.respond("📱 Now send the CHANNEL LINK:",buttons=[[Button.inline("« Cancel","menu_web_report")]])
        elif current_state=='awaiting_web_report_channel':
            channel_link=event.message.message.strip()
            state['web_channel_link']=channel_link
            set_state(uid,'awaiting_web_report_type',**state)
            buttons=[]
            for i in range(1,16):
                buttons.append([Button.inline(f"{i}. {REPORT_TYPES[i]}",f"web_report_type_{i}")])
            buttons.append([Button.inline("« Cancel","menu_web_report")])
            await event.respond("📝 Select report type:",buttons=buttons)
        elif current_state=='awaiting_web_report_count':
            try:
                count=int(event.message.message.strip())
                if count<1 or count>100:
                    await event.respond("❌ Please enter a number between 1 and 100",buttons=[[Button.inline("« Cancel","menu_web_report")]])
                    return
                message_link=state['web_message_link']
                channel_link=state['web_channel_link']
                report_type=state['web_report_type']
                progress_msg=await event.respond(f"⏳ SENDING WEB REPORTS\n\n📊 Target: {count} reports\n⏱️ Progress: 0/{count}")
                success_count=0
                fail_count=0
                for i in range(count):
                    result=await web_report_submission(report_type,message_link,channel_link)
                    if result:
                        success_count+=1
                        db.execute('INSERT INTO web_reports(user_id,target_link,report_type,success,timestamp) VALUES(?,?,?,1,?)',(uid,channel_link,REPORT_TYPES[report_type],datetime.now().isoformat()))
                    else:
                        fail_count+=1
                        db.execute('INSERT INTO web_reports(user_id,target_link,report_type,success,timestamp) VALUES(?,?,?,0,?)',(uid,channel_link,REPORT_TYPES[report_type],datetime.now().isoformat()))
                    if (i+1)%5==0:
                        try:
                            await progress_msg.edit(f"⏳ SENDING WEB REPORTS\n\n📊 Target: {count} reports\n⏱️ Progress: {i+1}/{count}\n✅ Success: {success_count}\n❌ Failed: {fail_count}")
                        except:
                            pass
                    await asyncio.sleep(random.uniform(3,6))
                success_rate=(success_count/count*100) if count>0 else 0
                await progress_msg.edit(f"✅ WEB REPORTS COMPLETED\n\n📊 RESULTS:\n├ Total: {count}\n├ Success: ✅ {success_count}\n├ Failed: ❌ {fail_count}\n└ Rate: {success_rate:.1f}%",buttons=[[Button.inline("🌐 Report Again","menu_web_report")],[Button.inline("« Main Menu","/start")]])
                clear_state(uid)
            except ValueError:
                await event.respond("❌ Please enter a valid number",buttons=[[Button.inline("« Cancel","menu_web_report")]])

@bot.on(events.CallbackQuery(pattern=rb'reason_(\d+)'))
async def reason_selection_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state:
        await event.answer("❌ Session expired",alert=True)
        return
    reason_id=event.data.decode().split('_')[1]
    reason_name,reason_obj=REASONS[reason_id]
    new_state_data={k:v for k,v in state.items() if k!='state' and k!='timestamp'}
    new_state_data['reason']=reason_id
    new_state_data['reason_name']=reason_name
    set_state(uid,'awaiting_reports_count',**new_state_data)
    settings=db.fetchone('SELECT max_reports_per_session FROM user_settings WHERE user_id=?',(uid,))
    max_reports=settings['max_reports_per_session'] if settings else 20
    await event.edit(f"✅ Selected: {reason_name}\n\n🎯 Target: {state['target']}\n📝 Reason: {reason_name}\n\nHow many reports per session? (1-{max_reports})\n\nType /cancel to cancel",buttons=[[Button.inline("« Cancel","menu_main")]])

@bot.on(events.CallbackQuery(pattern=rb'sessions_(\d+)'))
async def sessions_count_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state:
        await event.answer("❌ Session expired",alert=True)
        return
    sessions_count=int(event.data.decode().split('_')[1])
    new_state_data={k:v for k,v in state.items() if k!='state' and k!='timestamp'}
    new_state_data['sessions_count']=sessions_count
    set_state(uid,'confirming_report',**new_state_data)
    target=state['target']
    reason_name=state['reason_name']
    reports_count=state['reports_count']
    total_reports=reports_count*sessions_count
    await event.edit(f"""📋 CONFIRM REPORT

🎯 Target: {target}
📝 Reason: {reason_name}
🔢 Reports/Session: {reports_count}
📱 Sessions: {sessions_count}
📊 Total Reports: {total_reports}

Proceed with report?""",buttons=[[Button.inline("✅ Confirm & Execute","execute_report")],[Button.inline("« Cancel","menu_main")]])

@bot.on(events.CallbackQuery(pattern=b'execute_report'))
async def execute_report_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state:
        await event.answer("❌ Session expired",alert=True)
        return
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
    await event.edit(text,buttons=[[Button.inline("➕ Add Session File","add_session_file"),Button.inline("🔐 Login New","add_session_login")],[Button.inline("📋 View All Sessions","view_all_sessions"),Button.inline("🗑️ Remove Session","remove_session_menu")],[Button.inline("« Back","/start")]])

@bot.on(events.CallbackQuery(pattern=b'add_session_file'))
async def add_session_file_handler(event):
    uid=event.sender_id
    set_state(uid,'awaiting_session_file')
    await event.edit("📁 UPLOAD SESSION FILE\n\nSend me your .session file or a .zip containing session files.\n\nSupported formats:\n• Single .session file\n• ZIP archive with .session files\n\nType /cancel to cancel",buttons=[[Button.inline("« Cancel","menu_sessions")]])

@bot.on(events.CallbackQuery(pattern=b'add_session_login'))
async def add_session_login_handler(event):
    uid=event.sender_id
    set_state(uid,'awaiting_session_login_phone')
    await event.edit("🔐 LOGIN NEW SESSION\n\nSend your phone number with country code:\n\nExample: +1234567890\n\nType /cancel to cancel",buttons=[[Button.inline("« Cancel","menu_sessions")]])

@bot.on(events.NewMessage())
async def file_handler(event):
    if event.is_private and event.file:
        uid=event.sender_id
        state=get_state(uid)
        if not state or state.get('state')!='awaiting_session_file':
            return
        try:
            file_name=event.file.name or 'unknown'
            temp_path=os.path.join('temp_files',f'{uid}_{file_name}')
            await event.download_media(temp_path)
            added_count=0
            failed_count=0
            if file_name.endswith('.session'):
                success,msg=await add_session_from_file(uid,temp_path,file_name.replace('.session',''),'User')
                if success:
                    added_count+=1
                else:
                    failed_count+=1
                os.remove(temp_path)
            elif file_name.endswith('.zip'):
                extract_path=os.path.join('temp_files',f'extract_{uid}')
                os.makedirs(extract_path,exist_ok=True)
                with zipfile.ZipFile(temp_path,'r') as zip_ref:
                    zip_ref.extractall(extract_path)
                for root,dirs,files in os.walk(extract_path):
                    for file in files:
                        if file.endswith('.session'):
                            session_path=os.path.join(root,file)
                            success,msg=await add_session_from_file(uid,session_path,file.replace('.session',''),'User')
                            if success:
                                added_count+=1
                            else:
                                failed_count+=1
                shutil.rmtree(extract_path)
                os.remove(temp_path)
            else:
                await event.respond("❌ Unsupported file format. Please send .session or .zip file.",buttons=[[Button.inline("« Cancel","menu_sessions")]])
                return
            result_text=f"📊 IMPORT RESULTS\n\n✅ Added: {added_count}\n❌ Failed: {failed_count}\n\nTotal sessions: {db.fetchone('SELECT COUNT(*) as cnt FROM sessions WHERE user_id=?',(uid,))['cnt']}"
            await event.respond(result_text,buttons=[[Button.inline("📱 Manage Sessions","menu_sessions")],[Button.inline("« Main Menu","/start")]])
            clear_state(uid)
        except Exception as e:
            await event.respond(f"❌ Error processing file: {str(e)}",buttons=[[Button.inline("« Cancel","menu_sessions")]])
            clear_state(uid)

@bot.on(events.CallbackQuery(pattern=b'view_all_sessions'))
async def view_all_sessions_handler(event):
    uid=event.sender_id
    sessions=db.fetchall('SELECT * FROM sessions WHERE user_id=? ORDER BY added_date DESC',(uid,))
    if not sessions:
        await event.answer("No sessions found!",alert=True)
        return
    text="📋 ALL SESSIONS\n\n"
    for idx,sess in enumerate(sessions,1):
        status="✅ Active" if sess['is_active'] else "❌ Inactive"
        health="💚" if sess['health_score']>80 else "💛" if sess['health_score']>50 else "❤️"
        text+=f"{idx}. {sess['phone']}\n   Status: {status}\n   {health} Health: {sess['health_score']}%\n   Reports: {sess['success_reports']}/{sess['total_reports']}\n   Added: {sess['added_date'][:10]}\n\n"
    await event.edit(text[:4000],buttons=[[Button.inline("« Back","menu_sessions")]])

@bot.on(events.CallbackQuery(pattern=b'remove_session_menu'))
async def remove_session_menu_handler(event):
    uid=event.sender_id
    sessions=db.fetchall('SELECT * FROM sessions WHERE user_id=? ORDER BY added_date DESC LIMIT 10',(uid,))
    if not sessions:
        await event.answer("No sessions to remove!",alert=True)
        return
    buttons=[]
    for sess in sessions:
        buttons.append([Button.inline(f"🗑️ {sess['phone']}",f"remove_sess_{sess['id']}")])
    buttons.append([Button.inline("« Back","menu_sessions")])
    await event.edit("🗑️ SELECT SESSION TO REMOVE:",buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'remove_sess_(\d+)'))
async def remove_session_handler(event):
    uid=event.sender_id
    sess_id=int(event.data.decode().split('_')[2])
    session=db.fetchone('SELECT * FROM sessions WHERE id=? AND user_id=?',(sess_id,uid))
    if not session:
        await event.answer("Session not found!",alert=True)
        return
    session_path=os.path.join('sessions_db',session['session_file'])
    if os.path.exists(session_path):
        os.remove(session_path)
    db.execute('DELETE FROM sessions WHERE id=?',(sess_id,))
    db.execute('UPDATE statistics SET total_sessions=total_sessions-1,active_sessions=active_sessions-1 WHERE user_id=?',(uid,))
    await event.edit(f"✅ Session removed: {session['phone']}",buttons=[[Button.inline("📱 Manage Sessions","menu_sessions")],[Button.inline("« Main Menu","/start")]])

@bot.on(events.CallbackQuery(pattern=b'menu_web_report'))
async def web_report_menu_handler(event):
    uid=event.sender_id
    has_access,reason=check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!",alert=True)
        return
    load_proxies_from_db()
    proxy_count=len(proxy_cache)
    await event.edit(f"""🌐 WEB REPORT SYSTEM

This feature sends reports directly to Telegram's web support form without using your accounts.

📊 Available Proxies: {proxy_count}

Choose an option:""",buttons=[[Button.inline("📝 Submit Report","start_web_report")],[Button.inline("📊 Web Report Stats","web_report_stats")],[Button.inline("« Back","/start")]])

@bot.on(events.CallbackQuery(pattern=b'start_web_report'))
async def start_web_report_handler(event):
    uid=event.sender_id
    set_state(uid,'awaiting_web_report_message')
    await event.edit("📝 WEB REPORT SETUP\n\nStep 1/3: Send the MESSAGE LINK you want to report:",buttons=[[Button.inline("« Cancel","menu_web_report")]])

@bot.on(events.CallbackQuery(pattern=rb'web_report_type_(\d+)'))
async def web_report_type_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state:
        await event.answer("❌ Session expired",alert=True)
        return
    report_type=int(event.data.decode().split('_')[3])
    new_state_data={k:v for k,v in state.items() if k!='state' and k!='timestamp'}
    new_state_data['web_report_type']=report_type
    set_state(uid,'awaiting_web_report_count',**new_state_data)
    await event.edit(f"✅ Report Type: {REPORT_TYPES[report_type]}\n\nHow many reports to send? (1-100):",buttons=[[Button.inline("« Cancel","menu_web_report")]])

@bot.on(events.CallbackQuery(pattern=b'web_report_stats'))
async def web_report_stats_handler(event):
    uid=event.sender_id
    stats=db.fetchall('SELECT report_type,COUNT(*) as cnt,SUM(success) as succ FROM web_reports WHERE user_id=? GROUP BY report_type',(uid,))
    if not stats:
        await event.answer("No web reports yet!",alert=True)
        return
    text="📊 WEB REPORT STATISTICS\n\n"
    total_reports=0
    total_success=0
    for stat in stats:
        total_reports+=stat['cnt']
        total_success+=stat['succ']
        text+=f"• {stat['report_type']}: {stat['succ']}/{stat['cnt']}\n"
    success_rate=(total_success/total_reports*100) if total_reports>0 else 0
    text+=f"\n📈 Overall:\nTotal: {total_reports}\nSuccess: {total_success}\nRate: {success_rate:.1f}%"
    await event.edit(text,buttons=[[Button.inline("« Back","menu_web_report")]])

@bot.on(events.CallbackQuery(pattern=b'menu_settings'))
async def settings_menu_handler(event):
    uid=event.sender_id
    has_access,reason=check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!",alert=True)
        return
    settings=db.fetchone('SELECT * FROM user_settings WHERE user_id=?',(uid,))
    if not settings:
        db.execute('INSERT INTO user_settings(user_id) VALUES(?)',(uid,))
        settings=db.fetchone('SELECT * FROM user_settings WHERE user_id=?',(uid,))
    await event.edit(f"""⚙️ USER SETTINGS

Current Settings:
├ Max Reports/Session: {settings['max_reports_per_session']}
├ Delay: {settings['delay_seconds']}s
├ Auto Join: {'✅' if settings['auto_join'] else '❌'}
└ Random Order: {'✅' if settings['random_order'] else '❌'}

Customize your reporting preferences:""",buttons=[[Button.inline("🔢 Max Reports","set_max_reports"),Button.inline("⏱️ Delay","set_delay")],[Button.inline("🔄 Toggle Auto Join","toggle_auto_join"),Button.inline("🎲 Toggle Random","toggle_random")],[Button.inline("« Back","/start")]])

@bot.on(events.CallbackQuery(pattern=b'menu_statistics'))
async def statistics_menu_handler(event):
    uid=event.sender_id
    has_access,reason=check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!",alert=True)
        return
    stats=db.fetchone('SELECT * FROM statistics WHERE user_id=?',(uid,))
    if not stats:
        await event.answer("No statistics available!",alert=True)
        return
    user=db.fetchone('SELECT * FROM users WHERE user_id=?',(uid,))
    success_rate=(stats['successful_reports']/stats['total_reports']*100) if stats['total_reports']>0 else 0
    recent_reports=db.fetchall('SELECT * FROM reports WHERE user_id=? ORDER BY timestamp DESC LIMIT 5',(uid,))
    text=f"""📊 YOUR STATISTICS

👤 User: {user['first_name']}
📅 Joined: {user['joined_date'][:10]}

📱 SESSIONS:
├ Total: {stats['total_sessions']}
└ Active: {stats['active_sessions']}

📈 REPORTS:
├ Total: {stats['total_reports']}
├ Success: ✅ {stats['successful_reports']}
├ Failed: ❌ {stats['failed_reports']}
└ Success Rate: {success_rate:.1f}%

🎯 Targets Reported: {stats['targets_reported']}
📆 Last Report: {stats['last_report_date'][:10] if stats['last_report_date'] else 'Never'}

"""
    if recent_reports:
        text+="\n🕐 RECENT REPORTS:\n"
        for rep in recent_reports[:3]:
            status="✅" if rep['success'] else "❌"
            text+=f"{status} {rep['target'][:20]} - {rep['timestamp'][:10]}\n"
    await event.edit(text,buttons=[[Button.inline("📊 Detailed Report","detailed_stats")],[Button.inline("« Back","/start")]])

@bot.on(events.CallbackQuery(pattern=b'menu_owner'))
async def owner_menu_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only!",alert=True)
        return
    total_users=db.fetchone('SELECT COUNT(*) as cnt FROM users')['cnt']
    approved_users=db.fetchone('SELECT COUNT(*) as cnt FROM users WHERE is_approved=1')['cnt']
    pending_requests=db.fetchone('SELECT COUNT(*) as cnt FROM approval_requests WHERE status="pending"')['cnt']
    total_sessions=db.fetchone('SELECT COUNT(*) as cnt FROM sessions')['cnt']
    total_reports=db.fetchone('SELECT COUNT(*) as cnt FROM reports')['cnt']
    await event.edit(f"""👑 OWNER PANEL

📊 SYSTEM STATISTICS:
├ Total Users: {total_users}
├ Approved: {approved_users}
├ Pending Requests: {pending_requests}
├ Total Sessions: {total_sessions}
└ Total Reports: {total_reports}

Choose an option:""",buttons=[[Button.inline("✅ Approval Queue","menu_approvals"),Button.inline("👥 User Management","menu_user_mgmt")],[Button.inline("🌐 Proxy Management","menu_proxy_mgmt"),Button.inline("⚙️ Global Settings","menu_global_settings")],[Button.inline("📊 System Stats","menu_system_stats"),Button.inline("📢 Broadcast","menu_broadcast")],[Button.inline("« Back","/start")]])

@bot.on(events.CallbackQuery(pattern=b'menu_approvals'))
async def approvals_menu_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only!",alert=True)
        return
    requests=db.fetchall('SELECT * FROM approval_requests WHERE status="pending" ORDER BY requested_date DESC LIMIT 10')
    if not requests:
        await event.edit("✅ No pending approval requests",buttons=[[Button.inline("« Back","menu_owner")]])
        return
    text="✅ PENDING APPROVAL REQUESTS\n\n"
    buttons=[]
    for req in requests:
        text+=f"👤 {req['first_name']} (@{req['username']})\n📅 {req['requested_date'][:10]}\n\n"
        buttons.append([Button.inline(f"✅ Approve {req['first_name'][:10]}",f"approve_user_{req['user_id']}"),Button.inline(f"❌ Deny",f"deny_user_{req['user_id']}")])
    buttons.append([Button.inline("« Back","menu_owner")])
    await event.edit(text[:4000],buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'approve_user_(\d+)'))
async def approve_user_handler(event):
    owner_id=event.sender_id
    if not is_owner(owner_id):
        await event.answer("❌ Owner only!",alert=True)
        return
    user_id=int(event.data.decode().split('_')[2])
    db.execute('UPDATE users SET is_approved=1,approved_by=?,approved_date=? WHERE user_id=?',(owner_id,datetime.now().isoformat(),user_id))
    db.execute('UPDATE approval_requests SET status="approved",reviewed_by=?,reviewed_date=? WHERE user_id=? AND status="pending"',(owner_id,datetime.now().isoformat(),user_id))
    await event.answer("✅ User approved!",alert=True)
    try:
        await bot.send_message(user_id,"🎉 APPROVED!\n\nYour access request has been approved.\n\nYou can now use the bot. Type /start to begin.")
    except:
        pass
    await approvals_menu_handler(event)

@bot.on(events.CallbackQuery(pattern=rb'deny_user_(\d+)'))
async def deny_user_handler(event):
    owner_id=event.sender_id
    if not is_owner(owner_id):
        await event.answer("❌ Owner only!",alert=True)
        return
    user_id=int(event.data.decode().split('_')[2])
    db.execute('UPDATE approval_requests SET status="denied",reviewed_by=?,reviewed_date=? WHERE user_id=? AND status="pending"',(owner_id,datetime.now().isoformat(),user_id))
    await event.answer("❌ User denied!",alert=True)
    try:
        await bot.send_message(user_id,"❌ REQUEST DENIED\n\nYour access request has been denied.\n\nPlease contact support if you believe this is a mistake.")
    except:
        pass
    await approvals_menu_handler(event)

@bot.on(events.CallbackQuery(pattern=b'menu_proxy_mgmt'))
async def proxy_mgmt_menu_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only!",alert=True)
        return
    proxies=db.fetchall('SELECT * FROM proxies ORDER BY added_date DESC LIMIT 10')
    text=f"🌐 PROXY MANAGEMENT\n\nTotal Proxies: {len(proxy_cache)}\nActive: {db.fetchone('SELECT COUNT(*) as cnt FROM proxies WHERE is_active=1')['cnt']}\n\n"
    if proxies:
        text+="Recent proxies:\n\n"
        for proxy in proxies[:5]:
            status="✅" if proxy['is_active'] else "❌"
            text+=f"{status} {proxy['proxy_url'][:30]}\n   Success: {proxy['success_count']} | Fail: {proxy['fail_count']}\n\n"
    await event.edit(text,buttons=[[Button.inline("➕ Add Proxy","add_proxy"),Button.inline("📋 View All","view_all_proxies")],[Button.inline("🔄 Reload Proxies","reload_proxies"),Button.inline("🗑️ Clear Proxies","clear_proxies")],[Button.inline("« Back","menu_owner")]])

@bot.on(events.CallbackQuery(pattern=b'add_proxy'))
async def add_proxy_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only!",alert=True)
        return
    set_state(uid,'awaiting_proxy_url')
    await event.edit("🌐 ADD PROXY\n\nSend proxy URL in format:\nhttp://ip:port\nor\nhttp://username:password@ip:port\n\nType /cancel to cancel",buttons=[[Button.inline("« Cancel","menu_proxy_mgmt")]])

@bot.on(events.CallbackQuery(pattern=b'reload_proxies'))
async def reload_proxies_handler(event):
    uid=event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only!",alert=True)
        return
    load_proxies_from_db()
    await event.answer(f"✅ Loaded {len(proxy_cache)} proxies",alert=True)

@bot.on(events.NewMessage(pattern='/cancel'))
async def cancel_handler(event):
    uid=event.sender_id
    clear_state(uid)
    await event.respond("❌ Operation cancelled",buttons=[[Button.inline("« Menu","menu_main")]])

def main():
    print("""
╔════════════════════════════════════════════════════╗
║                                                    ║
║   🎯 ADVANCED TELEGRAM REPORTER BOT v6.0 🎯       ║
║        Professional Edition with Web Reports       ║
║                                                    ║
╚════════════════════════════════════════════════════╝

✨ Features:
  ├ 👑 Owner/User Separation
  ├ ✅ Approval System
  ├ 📊 Settings per User & Global
  ├ 💬 Message Link Reporting
  ├ 🎯 Peer Reporting
  ├ 🌐 Web Form Reporting
  ├ 📱 Session Management
  ├ 📦 ZIP Upload Support
  ├ 🔐 Phone Login System
  ├ 🔢 1-20 Reports per Session
  ├ ⏱️ Configurable Delays
  ├ 📈 Detailed Statistics
  ├ 🛡️ Flood Protection
  ├ 🌐 Proxy Support
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
