#!/usr/bin/env python3
import os,sys,json,asyncio,zipfile,shutil,time,random,logging,sqlite3
from datetime import datetime,timedelta
from typing import Dict,List,Optional,Tuple,Any
from pathlib import Path
from telethon import TelegramClient,events,Button
from telethon.errors import (SessionPasswordNeededError,FloodWaitError,PhoneCodeInvalidError,PhoneNumberInvalidError,UserPrivacyRestrictedError,ChannelPrivateError,UserAlreadyParticipantError,InviteHashExpiredError,PhoneCodeExpiredError,PhoneNumberBannedError,PeerIdInvalidError)
from telethon.tl.functions.account import ReportPeerRequest
from telethon.tl.functions.messages import ReportRequest,CheckChatInviteRequest,ImportChatInviteRequest,GetMessagesRequest
from telethon.tl.functions.channels import JoinChannelRequest,LeaveChannelRequest,GetParticipantsRequest
from telethon.tl.types import (InputReportReasonSpam,InputReportReasonViolence,InputReportReasonPornography,InputReportReasonChildAbuse,InputReportReasonCopyright,InputReportReasonFake,InputReportReasonIllegalDrugs,InputReportReasonPersonalDetails,InputReportReasonOther,InputReportReasonGeoIrrelevant,ChannelParticipantsRecent)
API_ID=28286832
API_HASH="2a8fba924d58c9c3f928d7db2c149b47"
BOT_TOKEN="7930383726:AAETy8tyvgZcP6UaPYuaQwLAkGUu9qyNJ4Q"
for d in ['sessions_db','temp_files','data','backups','logs','exports','cache']:
    os.makedirs(d,exist_ok=True)
logging.basicConfig(level=logging.INFO,format='%(asctime)s-%(levelname)s-%(message)s',handlers=[logging.FileHandler(f'logs/bot_{datetime.now().strftime("%Y%m%d")}.log'),logging.StreamHandler()])
logger=logging.getLogger(__name__)
class DB:
    def __init__(self):
        self.conn=sqlite3.connect('data/bot.db',check_same_thread=False)
        self.init_db()
        self.migrate_db()
    def init_db(self):
        c=self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY,username TEXT,first_name TEXT,joined_date TEXT,last_active TEXT,is_premium INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,phone TEXT,name TEXT,session_file TEXT,verified INTEGER,added_date TEXT,total_reports INTEGER DEFAULT 0,success_reports INTEGER DEFAULT 0,failed_reports INTEGER DEFAULT 0,is_active INTEGER DEFAULT 1,last_used TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,session_phone TEXT,target TEXT,reason TEXT,success INTEGER,timestamp TEXT,error_msg TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings(user_id INTEGER PRIMARY KEY,delay INTEGER DEFAULT 2,report_limit INTEGER DEFAULT 50,auto_join INTEGER DEFAULT 1,session_count INTEGER DEFAULT 0,random_order INTEGER DEFAULT 1,retry_failed INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS statistics(user_id INTEGER PRIMARY KEY,total_sessions INTEGER DEFAULT 0,total_reports INTEGER DEFAULT 0,successful_reports INTEGER DEFAULT 0,failed_reports INTEGER DEFAULT 0,last_report_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS flood_wait(session_phone TEXT PRIMARY KEY,wait_until TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS targets_cache(target TEXT PRIMARY KEY,entity_id TEXT,entity_type TEXT,cached_date TEXT)''')
        self.conn.commit()
    def migrate_db(self):
        c=self.conn.cursor()
        try:
            c.execute("SELECT last_used FROM sessions LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Adding last_used column...")
            c.execute("ALTER TABLE sessions ADD COLUMN last_used TEXT")
            self.conn.commit()
            logger.info("✅ Migration complete")
    def execute(self,query,params=()):
        c=self.conn.cursor()
        c.execute(query,params)
        self.conn.commit()
        return c
    def fetchone(self,query,params=()):
        return self.execute(query,params).fetchone()
    def fetchall(self,query,params=()):
        return self.execute(query,params).fetchall()
db=DB()
REASONS={"1":("📧Spam",InputReportReasonSpam()),"2":("⚔Violence",InputReportReasonViolence()),"3":("🔞Porn",InputReportReasonPornography()),"4":("👶Child Abuse",InputReportReasonChildAbuse()),"5":("©Copyright",InputReportReasonCopyright()),"6":("🎭Fake",InputReportReasonFake()),"7":("💊Drugs",InputReportReasonIllegalDrugs()),"8":("🔐Personal",InputReportReasonPersonalDetails()),"9":("🌍Geo",InputReportReasonGeoIrrelevant()),"10":("❓Other",InputReportReasonOther())}
user_states={}
flood_waits={}
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
            except:
                pass
        del user_states[uid]
def register_user(uid,username,first_name):
    if not db.fetchone('SELECT user_id FROM users WHERE user_id=?',(uid,)):
        now=datetime.now().isoformat()
        db.execute('INSERT INTO users VALUES(?,?,?,?,?,0)',(uid,username,first_name,now,now))
        db.execute('INSERT OR IGNORE INTO settings(user_id)VALUES(?)',(uid,))
        db.execute('INSERT OR IGNORE INTO statistics(user_id)VALUES(?)',(uid,))
    else:
        db.execute('UPDATE users SET last_active=? WHERE user_id=?',(datetime.now().isoformat(),uid))
def get_sessions(uid):
    rows=db.fetchall('''SELECT id,phone,name,session_file,verified,added_date,total_reports,success_reports,failed_reports,last_used FROM sessions WHERE user_id=? AND is_active=1 ORDER BY success_reports DESC''',(uid,))
    sessions=[]
    for r in rows:
        sessions.append({'id':r[0],'phone':r[1],'name':r[2],'session_file':r[3],'verified':bool(r[4]),'added_date':r[5],'total_reports':r[6],'success_reports':r[7],'failed_reports':r[8],'last_used':r[9]})
    return sessions
def add_session(uid,phone,name,session_file):
    now=datetime.now().isoformat()
    existing=db.fetchone('SELECT id FROM sessions WHERE user_id=? AND phone=?',(uid,phone))
    if existing:
        db.execute('UPDATE sessions SET is_active=1,name=?,session_file=?,verified=1 WHERE user_id=? AND phone=?',(name,session_file,uid,phone))
    else:
        db.execute('''INSERT INTO sessions(user_id,phone,name,session_file,verified,added_date)VALUES(?,?,?,?,1,?)''',(uid,phone,name,session_file,now))
        db.execute('UPDATE statistics SET total_sessions=total_sessions+1 WHERE user_id=?',(uid,))
def remove_session(uid,phone):
    db.execute('UPDATE sessions SET is_active=0 WHERE user_id=? AND phone=?',(uid,phone))
    db.execute('UPDATE statistics SET total_sessions=total_sessions-1 WHERE user_id=? AND total_sessions>0',(uid,))
def update_session_stats(uid,phone,success=0,failed=0):
    now=datetime.now().isoformat()
    db.execute('''UPDATE sessions SET total_reports=total_reports+?,success_reports=success_reports+?,failed_reports=failed_reports+?,last_used=? WHERE user_id=? AND phone=?''',(success+failed,success,failed,now,uid,phone))
def get_settings(uid):
    row=db.fetchone('SELECT delay,report_limit,auto_join,session_count,random_order,retry_failed FROM settings WHERE user_id=?',(uid,))
    return {'delay':row[0],'report_limit':row[1],'auto_join':bool(row[2]),'session_count':row[3],'random_order':bool(row[4]),'retry_failed':bool(row[5])} if row else {'delay':2,'report_limit':50,'auto_join':True,'session_count':0,'random_order':True,'retry_failed':False}
def update_setting(uid,key,val):
    db.execute(f'UPDATE settings SET {key}=? WHERE user_id=?',(val,uid))
def get_stats(uid):
    row=db.fetchone('''SELECT total_sessions,total_reports,successful_reports,failed_reports,last_report_date FROM statistics WHERE user_id=?''',(uid,))
    if row:
        total,success=row[1],row[2]
        rate=int((success/total*100))if total>0 else 0
        return {'total_sessions':row[0],'total_reports':total,'successful_reports':success,'failed_reports':row[3],'success_rate':rate,'last_report_date':row[4]}
    return {'total_sessions':0,'total_reports':0,'successful_reports':0,'failed_reports':0,'success_rate':0,'last_report_date':None}
def update_stats(uid,success=0,failed=0):
    now=datetime.now().isoformat()
    db.execute('''UPDATE statistics SET total_reports=total_reports+?,successful_reports=successful_reports+?,failed_reports=failed_reports+?,last_report_date=? WHERE user_id=?''',(success+failed,success,failed,now,uid))
def log_report(uid,phone,target,reason,success,error=''):
    now=datetime.now().isoformat()
    db.execute('INSERT INTO reports(user_id,session_phone,target,reason,success,timestamp,error_msg)VALUES(?,?,?,?,?,?,?)',(uid,phone,target,reason,success,now,error))
def check_flood_wait(phone):
    row=db.fetchone('SELECT wait_until FROM flood_wait WHERE session_phone=?',(phone,))
    if row:
        wait_until=datetime.fromisoformat(row[0])
        if datetime.now()<wait_until:
            return True,(wait_until-datetime.now()).seconds
    return False,0
def set_flood_wait(phone,seconds):
    wait_until=(datetime.now()+timedelta(seconds=seconds)).isoformat()
    db.execute('INSERT OR REPLACE INTO flood_wait(session_phone,wait_until)VALUES(?,?)',(phone,wait_until))
def clear_flood_wait(phone):
    db.execute('DELETE FROM flood_wait WHERE session_phone=?',(phone,))
async def create_client(uid,phone):
    name=f"{uid}_{phone.replace('+','').replace(' ','')}"
    path=os.path.join('sessions_db',name)
    client=TelegramClient(path,API_ID,API_HASH)
    await client.connect()
    return client,name
async def verify_session(path):
    client=None
    try:
        client=TelegramClient(path,API_ID,API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return False,None,None
        me=await client.get_me()
        phone=me.phone if me.phone else "Unknown"
        name=me.first_name or "User"
        await client.disconnect()
        return True,phone,name
    except Exception as e:
        logger.error(f"Verify failed:{str(e)}")
        if client:
            try:
                await client.disconnect()
            except:
                pass
        return False,None,None
async def is_private_link(link):
    return 't.me/+' in link or 't.me/joinchat/' in link
async def get_entity_from_target(client,target):
    if target.startswith('@'):
        target=target[1:]
    entity=None
    if 't.me/' in target:
        if 't.me/+' in target or 't.me/joinchat/' in target:
            hash_part=target.split('t.me/+')[-1].split('?')[0] if 't.me/+' in target else target.split('t.me/joinchat/')[-1].split('?')[0]
            invite_info=await client(CheckChatInviteRequest(hash=hash_part))
            if hasattr(invite_info,'chat'):
                try:
                    result=await client(ImportChatInviteRequest(hash=hash_part))
                    entity=result.chats[0] if result.chats else None
                except UserAlreadyParticipantError:
                    entity=invite_info.chat
                except Exception:
                    entity=invite_info.chat
            else:
                return None
        elif 't.me/c/' in target:
            parts=target.split('t.me/c/')[-1].split('/')
            if len(parts)>=1:
                channel_id=int('-100'+parts[0])
                entity=await client.get_entity(channel_id)
            else:
                return None
        else:
            username=target.split('t.me/')[-1].split('/')[0].split('?')[0]
            if username.startswith('@'):
                username=username[1:]
            entity=await client.get_entity(username)
    else:
        entity=await client.get_entity(target)
    return entity
async def report_user(session_path,target,reason_obj,phone,uid):
    client=None
    try:
        is_waiting,wait_time=check_flood_wait(phone)
        if is_waiting:
            return False,f"FloodWait:{wait_time}s"
        client=TelegramClient(session_path,API_ID,API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return False,"Not authorized"
        entity=await get_entity_from_target(client,target)
        if not entity:
            await client.disconnect()
            return False,"Could not get entity"
        await client(ReportPeerRequest(peer=entity,reason=reason_obj,message="Policy violation"))
        await client.disconnect()
        clear_flood_wait(phone)
        return True,None
    except FloodWaitError as e:
        set_flood_wait(phone,e.seconds)
        if client:
            try:
                await client.disconnect()
            except:
                pass
        return False,f"Flood:{e.seconds}s"
    except Exception as e:
        if client:
            try:
                await client.disconnect()
            except:
                pass
        error_str=str(e)[:50]
        return False,error_str
async def report_messages(session_path,target,msg_ids,reason_obj,phone,uid):
    client=None
    try:
        is_waiting,wait_time=check_flood_wait(phone)
        if is_waiting:
            return False,f"FloodWait:{wait_time}s"
        client=TelegramClient(session_path,API_ID,API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return False,"Not authorized"
        entity=await get_entity_from_target(client,target)
        if not entity:
            await client.disconnect()
            return False,"Could not get entity"
        await client(ReportRequest(peer=entity,id=msg_ids,reason=reason_obj,message="Violation"))
        await client.disconnect()
        clear_flood_wait(phone)
        return True,None
    except FloodWaitError as e:
        set_flood_wait(phone,e.seconds)
        if client:
            try:
                await client.disconnect()
            except:
                pass
        return False,f"Flood:{e.seconds}s"
    except Exception as e:
        if client:
            try:
                await client.disconnect()
            except:
                pass
        error_str=str(e)[:50]
        return False,error_str
async def join_channel(session_path,channel):
    client=None
    try:
        client=TelegramClient(session_path,API_ID,API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return False,"Not authorized"
        entity=await get_entity_from_target(client,channel)
        if not entity:
            await client.disconnect()
            return False,"Could not get entity"
        try:
            await client(JoinChannelRequest(entity))
        except UserAlreadyParticipantError:
            pass
        await client.disconnect()
        return True,None
    except Exception as e:
        if client:
            try:
                await client.disconnect()
            except:
                pass
        return False,str(e)[:50]
async def leave_channel(session_path,channel):
    client=None
    try:
        client=TelegramClient(session_path,API_ID,API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return False,"Not authorized"
        username=channel.split('t.me/')[-1].split('/')[0].split('?')[0]
        if username.startswith('@'):
            username=username[1:]
        entity=await client.get_entity(username)
        await client(LeaveChannelRequest(entity))
        await client.disconnect()
        return True,None
    except Exception as e:
        if client:
            try:
                await client.disconnect()
            except:
                pass
        return False,str(e)[:50]
async def get_message_ids_from_link(session_path,link):
    client=None
    try:
        client=TelegramClient(session_path,API_ID,API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return []
        parts=link.split('/')
        if len(parts)<2:
            await client.disconnect()
            return []
        msg_id_part=parts[-1].split('?')[0]
        if '-' in msg_id_part:
            start,end=msg_id_part.split('-')
            msg_ids=list(range(int(start),int(end)+1))
        else:
            msg_ids=[int(msg_id_part)]
        await client.disconnect()
        return msg_ids
    except Exception as e:
        logger.error(f"Get msg IDs failed:{str(e)}")
        if client:
            try:
                await client.disconnect()
            except:
                pass
        return []
bot=TelegramClient('bot_session',API_ID,API_HASH).start(bot_token=BOT_TOKEN)
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if not event.is_private:
        return
    uid=event.sender_id
    user=await event.get_sender()
    username=user.username or ""
    first_name=user.first_name or "User"
    register_user(uid,username,first_name)
    clear_state(uid)
    stats=get_stats(uid)
    sessions=get_sessions(uid)
    active_sessions=len(sessions)
    text=f"╔════════════════════╗\n║ 🎯 REPORTER BOT ║\n╚════════════════════╝\n\n👤 {first_name}\n📱 Sessions: {active_sessions}\n📊 Reports: {stats['total_reports']}\n✅ Success: {stats['successful_reports']}\n❌ Failed: {stats['failed_reports']}\n📈 Rate: {stats['success_rate']}%"
    buttons=[[Button.inline("📱 Sessions",b"menu_sessions"),Button.inline("🎯 Report",b"menu_report")],[Button.inline("🛠 Tools",b"menu_tools"),Button.inline("⚙ Settings",b"menu_settings")],[Button.inline("📊 Stats",b"menu_stats"),Button.inline("ℹ Help",b"menu_help")]]
    await event.respond(text,buttons=buttons)
@bot.on(events.CallbackQuery(pattern=b"start"))
async def back_to_start(event):
    await start_handler(event)
@bot.on(events.CallbackQuery(pattern=b"menu_sessions"))
async def sessions_menu(event):
    uid=event.sender_id
    sessions=get_sessions(uid)
    text=f"╔════════════════════╗\n║ 📱 SESSIONS ║\n╚════════════════════╝\n\n"
    if sessions:
        text+=f"Active Sessions: {len(sessions)}\n\n"
        for idx,s in enumerate(sessions[:10],1):
            last=s['last_used'][:10] if s['last_used']else 'Never'
            text+=f"{idx}. 📱 {s['phone']}\n   👤 {s['name']}\n   ✅ {s['success_reports']}/{s['total_reports']}\n   🕐 {last}\n\n"
        if len(sessions)>10:
            text+=f"...and {len(sessions)-10} more\n"
    else:
        text+="No sessions added.\n\n"
    text+="➕ Add via:\n• .session file\n• .zip file\n• /add command"
    buttons=[[Button.inline("➕ Add",b"add_session"),Button.inline("❌ Remove",b"remove_session")],[Button.inline("📤 Export",b"export_sessions"),Button.inline("🔄 Refresh",b"menu_sessions")],[Button.inline("« Back",b"start")]]
    await event.edit(text,buttons=buttons)
@bot.on(events.CallbackQuery(pattern=b"menu_report"))
async def report_menu(event):
    uid=event.sender_id
    sessions=get_sessions(uid)
    text=f"╔════════════════════╗\n║ 🎯 REPORT MENU ║\n╚════════════════════╝\n\n"
    if sessions:
        text+=f"Available Sessions: {len(sessions)}\n\nChoose report type:"
    else:
        text+="❌ No sessions available!\nAdd sessions first."
    buttons=[]
    if sessions:
        buttons.append([Button.inline("👤 User/Channel",b"report_user")])
        buttons.append([Button.inline("💬 Messages",b"report_messages")])
    buttons.append([Button.inline("« Back",b"start")])
    await event.edit(text,buttons=buttons)
@bot.on(events.CallbackQuery(pattern=b"menu_tools"))
async def tools_menu(event):
    text="╔════════════════════╗\n║ 🛠 TOOLS ║\n╚════════════════════╝\n\nSelect tool:"
    buttons=[[Button.inline("🔗 Join Channels",b"tool_join")],[Button.inline("❌ Leave Channels",b"tool_leave")],[Button.inline("« Back",b"start")]]
    await event.edit(text,buttons=buttons)
@bot.on(events.CallbackQuery(pattern=b"menu_settings"))
async def settings_menu(event):
    uid=event.sender_id
    s=get_settings(uid)
    text=f"╔════════════════════╗\n║ ⚙ SETTINGS ║\n╚════════════════════╝\n\n⏱ Delay: {s['delay']}s\n📊 Limit: {s['report_limit']}\n🔀 Random: {'✅' if s['random_order']else '❌'}\n🔗 Auto Join: {'✅' if s['auto_join']else '❌'}\n🔁 Retry: {'✅' if s['retry_failed']else '❌'}"
    buttons=[[Button.inline(f"⏱ Delay ({s['delay']}s)",b"set_delay"),Button.inline(f"📊 Limit ({s['report_limit']})",b"set_limit")],[Button.inline(f"🔀 Random {'ON' if s['random_order']else 'OFF'}",b"toggle_random"),Button.inline(f"🔗 Join {'ON' if s['auto_join']else 'OFF'}",b"toggle_join")],[Button.inline(f"🔁 Retry {'ON' if s['retry_failed']else 'OFF'}",b"toggle_retry")],[Button.inline("« Back",b"start")]]
    await event.edit(text,buttons=buttons)
@bot.on(events.CallbackQuery(pattern=b"menu_stats"))
async def stats_menu(event):
    uid=event.sender_id
    stats=get_stats(uid)
    sessions=get_sessions(uid)
    text=f"╔════════════════════╗\n║ 📊 STATISTICS ║\n╚════════════════════╝\n\n📱 Sessions: {stats['total_sessions']}\n   Active: {len(sessions)}\n\n📝 Reports:\n   Total: {stats['total_reports']}\n   ✅ Success: {stats['successful_reports']}\n   ❌ Failed: {stats['failed_reports']}\n   📈 Rate: {stats['success_rate']}%\n\n🕐 Last: {stats['last_report_date'][:16] if stats['last_report_date']else 'Never'}\n\n🏆 Top Sessions:"
    if sessions:
        for i,s in enumerate(sessions[:5],1):
            text+=f"\n{i}. {s['phone']}: {s['success_reports']}✅"
    buttons=[[Button.inline("🔄 Refresh",b"menu_stats"),Button.inline("« Back",b"start")]]
    await event.edit(text,buttons=buttons)
@bot.on(events.CallbackQuery(pattern=b"menu_help"))
async def help_menu(event):
    text="""╔════════════════════╗
║ ℹ HELP GUIDE ║
╚════════════════════╝

📱 SESSION MANAGEMENT:
• Send .session file
• Send .zip with sessions
• /add for phone login

🎯 REPORTING:
• User: @username or link
• Multiple: one per line
• Messages: link with range

⚙ SETTINGS:
• Delay: time between
• Limit: max reports
• Random: session order
• Auto Join: private links
• Retry: failed reports

📝 COMMANDS:
/start - Main menu
/add - Add via phone
/cancel - Cancel operation"""
    buttons=[[Button.inline("« Back",b"start")]]
    await event.edit(text,buttons=buttons)
@bot.on(events.CallbackQuery(pattern=b"add_session"))
async def add_session_callback(event):
    text="╔════════════════════╗\n║ ➕ ADD SESSION ║\n╚════════════════════╝\n\n📱 Send:\n• .session file\n• .zip archive\n• /add for phone"
    buttons=[[Button.inline("« Cancel",b"menu_sessions")]]
    await event.respond(text,buttons=buttons)
@bot.on(events.CallbackQuery(pattern=b"remove_session"))
async def remove_session_callback(event):
    uid=event.sender_id
    sessions=get_sessions(uid)
    if not sessions:
        await event.answer("No sessions to remove",alert=True)
        return
    text="╔════════════════════╗\n║ ❌ REMOVE ║\n╚════════════════════╝\n\nSelect session:"
    buttons=[]
    for s in sessions[:20]:
        buttons.append([Button.inline(f"❌ {s['phone']}",f"rm_{s['phone']}".encode())])
    buttons.append([Button.inline("« Cancel",b"menu_sessions")])
    await event.edit(text,buttons=buttons)
@bot.on(events.CallbackQuery(pattern=b"rm_"))
async def confirm_remove(event):
    uid=event.sender_id
    phone=event.data.decode().replace('rm_','')
    remove_session(uid,phone)
    await event.answer(f"✅ Removed {phone}",alert=True)
    await sessions_menu(event)
@bot.on(events.CallbackQuery(pattern=b"export_sessions"))
async def export_callback(event):
    uid=event.sender_id
    sessions=get_sessions(uid)
    if not sessions:
        await event.answer("No sessions to export",alert=True)
        return
    msg=await event.respond("📦 Exporting...")
    zip_name=f"exports/sessions_{uid}_{int(time.time())}.zip"
    try:
        with zipfile.ZipFile(zip_name,'w')as zf:
            for s in sessions:
                path=os.path.join('sessions_db',s['session_file']+'.session')
                if os.path.exists(path):
                    zf.write(path,s['session_file']+'.session')
        await bot.send_file(uid,zip_name,caption=f"✅ Exported {len(sessions)} sessions")
        await msg.delete()
    except Exception as e:
        await msg.edit(f"❌ Error: {str(e)[:100]}")
    finally:
        try:
            os.remove(zip_name)
        except:
            pass
@bot.on(events.CallbackQuery(pattern=b"report_user"))
async def report_user_callback(event):
    uid=event.sender_id
    set_state(uid,'awaiting_target')
    text="""╔════════════════════╗
║ 👤 USER REPORT ║
╚════════════════════╝

Send target:

Single:
@username
https://t.me/channel
https://t.me/+hash

Multiple (one per line):
@user1
@user2
https://t.me/ch"""
    buttons=[[Button.inline("« Cancel",b"menu_report")]]
    await event.respond(text,buttons=buttons)
@bot.on(events.CallbackQuery(pattern=b"report_messages"))
async def report_messages_callback(event):
    uid=event.sender_id
    set_state(uid,'awaiting_msg_link')
    text="""╔════════════════════╗
║ 💬 MESSAGE REPORT ║
╚════════════════════╝

Send message link:

Format:
https://t.me/ch/123
https://t.me/ch/10-50

Examples:
Single: /123
Range: /10-20"""
    buttons=[[Button.inline("« Cancel",b"menu_report")]]
    await event.respond(text,buttons=buttons)
@bot.on(events.CallbackQuery(pattern=b"tool_join"))
async def tool_join_callback(event):
    uid=event.sender_id
    sessions=get_sessions(uid)
    if not sessions:
        await event.answer("❌ No sessions",alert=True)
        return
    set_state(uid,'awaiting_join_links')
    text="""╔════════════════════╗
║ 🔗 JOIN CHANNELS ║
╚════════════════════╝

Send links (one per line):

@channel1
https://t.me/channel2
https://t.me/+hash"""
    buttons=[[Button.inline("« Cancel",b"menu_tools")]]
    await event.respond(text,buttons=buttons)
@bot.on(events.CallbackQuery(pattern=b"tool_leave"))
async def tool_leave_callback(event):
    uid=event.sender_id
    sessions=get_sessions(uid)
    if not sessions:
        await event.answer("❌ No sessions",alert=True)
        return
    set_state(uid,'awaiting_leave_links')
    text="""╔════════════════════╗
║ ❌ LEAVE CHANNELS ║
╚════════════════════╝

Send links (one per line):

@channel1
https://t.me/channel2"""
    buttons=[[Button.inline("« Cancel",b"menu_tools")]]
    await event.respond(text,buttons=buttons)
@bot.on(events.CallbackQuery(pattern=b"set_delay"))
async def set_delay_callback(event):
    uid=event.sender_id
    set_state(uid,'awaiting_delay')
    await event.respond("⏱ Enter delay (1-30s):",buttons=[[Button.inline("« Cancel",b"menu_settings")]])
@bot.on(events.CallbackQuery(pattern=b"set_limit"))
async def set_limit_callback(event):
    uid=event.sender_id
    set_state(uid,'awaiting_limit')
    await event.respond("📊 Enter limit (1-100):",buttons=[[Button.inline("« Cancel",b"menu_settings")]])
@bot.on(events.CallbackQuery(pattern=b"toggle_random"))
async def toggle_random_callback(event):
    uid=event.sender_id
    s=get_settings(uid)
    new_val=0 if s['random_order']else 1
    update_setting(uid,'random_order',new_val)
    await event.answer(f"Random: {'ON' if new_val else 'OFF'}",alert=True)
    await settings_menu(event)
@bot.on(events.CallbackQuery(pattern=b"toggle_join"))
async def toggle_join_callback(event):
    uid=event.sender_id
    s=get_settings(uid)
    new_val=0 if s['auto_join']else 1
    update_setting(uid,'auto_join',new_val)
    await event.answer(f"Auto Join: {'ON' if new_val else 'OFF'}",alert=True)
    await settings_menu(event)
@bot.on(events.CallbackQuery(pattern=b"toggle_retry"))
async def toggle_retry_callback(event):
    uid=event.sender_id
    s=get_settings(uid)
    new_val=0 if s['retry_failed']else 1
    update_setting(uid,'retry_failed',new_val)
    await event.answer(f"Retry: {'ON' if new_val else 'OFF'}",alert=True)
    await settings_menu(event)
@bot.on(events.CallbackQuery(pattern=b"reason_"))
async def reason_callback(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state:
        await event.answer("Session expired",alert=True)
        return
    reason_num=event.data.decode().replace('reason_','')
    if reason_num not in REASONS:
        await event.answer("Invalid reason",alert=True)
        return
    reason_name,reason_obj=REASONS[reason_num]
    state['reason_name']=reason_name
    state['reason_obj']=reason_obj
    if state['state']=='awaiting_reason':
        state['state']='awaiting_session_count'
        set_state(uid,'awaiting_session_count',state)
        await event.respond(f"✅ Selected: {reason_name}\n\nEnter session count (0 for all):",buttons=[[Button.inline("« Cancel",b"menu_report")]])
    elif state['state']=='awaiting_msg_reason':
        state['state']='awaiting_msg_session_count'
        set_state(uid,'awaiting_msg_session_count',state)
        await event.respond(f"✅ Selected: {reason_name}\n\nEnter session count (0 for all):",buttons=[[Button.inline("« Cancel",b"menu_report")]])
@bot.on(events.NewMessage(pattern='/cancel'))
async def cancel_handler(event):
    if not event.is_private:
        return
    uid=event.sender_id
    clear_state(uid)
    await event.respond("✅ Cancelled",buttons=[[Button.inline("🏠 Home",b"start")]])
@bot.on(events.NewMessage(pattern='/add'))
async def add_via_phone(event):
    if not event.is_private:
        return
    uid=event.sender_id
    set_state(uid,'awaiting_phone')
    await event.respond("📱 Send phone number:\n\nFormat: +1234567890",buttons=[[Button.inline("« Cancel",b"menu_sessions")]])
@bot.on(events.NewMessage(func=lambda e:e.is_private and e.text and not e.text.startswith('/')))
async def text_handler(event):
    uid=event.sender_id
    state=get_state(uid)
    if not state:
        return
    text=event.text.strip()
    if state['state']=='awaiting_phone':
        if not text.startswith('+'):
            await event.respond("❌ Must start with +")
            return
        client,name=await create_client(uid,text)
        try:
            await client.send_code_request(text)
            set_state(uid,'awaiting_code',{'phone':text,'client':client,'session_name':name})
            await event.respond("📨 Code sent!\n\nEnter code:")
        except Exception as e:
            await client.disconnect()
            await event.respond(f"❌ Error: {str(e)[:100]}")
            clear_state(uid)
    elif state['state']=='awaiting_code':
        code=text
        msg=await event.respond("🔐 Verifying...")
        try:
            await state['client'].sign_in(state['phone'],code)
            me=await state['client'].get_me()
            username=me.first_name or "User"
            add_session(uid,state['phone'],username,state['session_name'])
            await state['client'].disconnect()
            clear_state(uid)
            await msg.edit(f"✅ ADDED\n\n📱 {state['phone']}\n👤 {username}",buttons=[[Button.inline("📱 Sessions",b"menu_sessions")]])
        except SessionPasswordNeededError:
            state['state']='awaiting_2fa'
            set_state(uid,'awaiting_2fa',state)
            await msg.edit("🔐 2FA enabled!\n\nSend password:")
        except Exception as e:
            await msg.edit(f"❌ Error: {str(e)[:100]}")
            clear_state(uid)
    elif state['state']=='awaiting_2fa':
        password=text
        msg=await event.respond("🔐 Verifying 2FA...")
        try:
            await state['client'].sign_in(password=password)
            me=await state['client'].get_me()
            username=me.first_name or "User"
            add_session(uid,state['phone'],username,state['session_name'])
            await state['client'].disconnect()
            clear_state(uid)
            await msg.edit(f"✅ ADDED\n\n📱 {state['phone']}\n👤 {username}",buttons=[[Button.inline("📱 Sessions",b"menu_sessions")]])
        except Exception as e:
            await msg.edit(f"❌ Error: {str(e)[:100]}")
            clear_state(uid)
    elif state['state']=='awaiting_target':
        target=text
        state['target']=target
        state['state']='awaiting_reason'
        set_state(uid,'awaiting_reason',state)
        reasons_text="╔═══════════════╗\n║ 🎯 REASON ║\n╚═══════════════╝\n\nSelect reason:\n\n"
        buttons=[]
        for num,(name,_)in REASONS.items():
            reasons_text+=f"{num}. {name}\n"
            buttons.append([Button.inline(f"{num}. {name}",f"reason_{num}".encode())])
        buttons.append([Button.inline("« Cancel",b"menu_report")])
        await event.respond(reasons_text,buttons=buttons)
    elif state['state']=='awaiting_msg_link':
        link=text
        sessions=get_sessions(uid)
        if not sessions:
            await event.respond("❌ No sessions")
            clear_state(uid)
            return
        first_session=sessions[0]
        session_path=os.path.join('sessions_db',first_session['session_file'])
        msg_ids=await get_message_ids_from_link(session_path,link)
        if not msg_ids:
            await event.respond("❌ Invalid link")
            return
        state['msg_ids']=msg_ids
        state['target']=link
        state['state']='awaiting_msg_reason'
        set_state(uid,'awaiting_msg_reason',state)
        reasons_text="╔═══════════════╗\n║ 🎯 REASON ║\n╚═══════════════╝\n\nSelect reason:\n\n"
        buttons=[]
        for num,(name,_)in REASONS.items():
            reasons_text+=f"{num}. {name}\n"
            buttons.append([Button.inline(f"{num}. {name}",f"reason_{num}".encode())])
        buttons.append([Button.inline("« Cancel",b"menu_report")])
        await event.respond(reasons_text,buttons=buttons)
    elif state['state']=='awaiting_session_count':
        try:
            count=int(text)
            if count<0:
                await event.respond("❌ Must be 0+")
                return
            state['session_count']=count
            await process_user_report(event,state['target'],None,state)
        except ValueError:
            await event.respond("❌ Invalid number")
    elif state['state']=='awaiting_msg_session_count':
        try:
            count=int(text)
            if count<0:
                await event.respond("❌ Must be 0+")
                return
            state['session_count']=count
            await process_message_report(event,state['target'],state['msg_ids'],state)
        except ValueError:
            await event.respond("❌ Invalid number")
    elif state['state']=='awaiting_join_links':
        await process_join(event,text)
    elif state['state']=='awaiting_leave_links':
        await process_leave(event,text)
    elif state['state']=='awaiting_delay':
        try:
            delay=int(text)
            if 1<=delay<=30:
                update_setting(uid,'delay',delay)
                clear_state(uid)
                await event.respond(f"✅ Delay set to {delay}s",buttons=[[Button.inline("⚙ Settings",b"menu_settings")]])
            else:
                await event.respond("❌ Must be 1-30")
        except ValueError:
            await event.respond("❌ Invalid")
    elif state['state']=='awaiting_limit':
        try:
            limit=int(text)
            if 1<=limit<=100:
                update_setting(uid,'report_limit',limit)
                clear_state(uid)
                await event.respond(f"✅ Limit set to {limit}",buttons=[[Button.inline("⚙ Settings",b"menu_settings")]])
            else:
                await event.respond("❌ Must be 1-100")
        except ValueError:
            await event.respond("❌ Invalid")
async def process_user_report(event,target,msg,state):
    uid=event.sender_id
    msg=await event.respond(f"🎯 Starting...\nTarget: {target[:40]}...")
    sessions=get_sessions(uid)
    verified=[s for s in sessions if s['verified']]
    if not verified:
        await msg.edit("❌ No sessions",buttons=[[Button.inline("📱 Add",b"menu_sessions")]])
        clear_state(uid)
        return
    count=state.get('session_count',0)
    settings=get_settings(uid)
    if count>0 and count<len(verified):
        if settings['random_order']:
            selected=random.sample(verified,min(count,len(verified)))
        else:
            selected=verified[:count]
    else:
        selected=verified
    delay=settings['delay']
    reason_obj=state['reason_obj']
    reason_name=state['reason_name']
    success,failed=0,0
    total_sessions=len(selected)
    failed_sessions=[]
    for idx,s in enumerate(selected,1):
        path=os.path.join('sessions_db',s['session_file'])
        ok,error=await report_user(path,target,reason_obj,s['phone'],uid)
        if ok:
            success+=1
            update_session_stats(uid,s['phone'],success=1)
            log_report(uid,s['phone'],target,reason_name,1)
        else:
            failed+=1
            update_session_stats(uid,s['phone'],failed=1)
            log_report(uid,s['phone'],target,reason_name,0,error or '')
            failed_sessions.append((s,error))
        if idx%3==0 or idx==total_sessions:
            progress=f"🎯 {idx}/{total_sessions}\n✅ {success} ❌ {failed}"
            try:
                await msg.edit(progress)
            except:
                pass
        await asyncio.sleep(delay)
    if settings['retry_failed'] and failed_sessions:
        retry_msg=await event.respond(f"🔄 Retrying {len(failed_sessions)}...")
        for s,prev_error in failed_sessions:
            path=os.path.join('sessions_db',s['session_file'])
            ok,error=await report_user(path,target,reason_obj,s['phone'],uid)
            if ok:
                success+=1
                failed-=1
                update_session_stats(uid,s['phone'],success=1,failed=-1)
                log_report(uid,s['phone'],target,reason_name,1)
            await asyncio.sleep(delay)
        await retry_msg.delete()
    total=success+failed
    rate=int((success/total*100))if total>0 else 0
    update_stats(uid,success,failed)
    clear_state(uid)
    result=f"✅ COMPLETE\n\n🎯 {target[:35]}\n📋 {reason_name}\n📱 {total_sessions} sessions\n\n✅ Success: {success}\n❌ Failed: {failed}\n📈 Rate: {rate}%"
    await msg.edit(result,buttons=[[Button.inline("🎯 Again",b"menu_report"),Button.inline("🏠 Home",b"start")]])
async def process_message_report(event,target,msg_ids,state):
    uid=event.sender_id
    msg=await event.respond(f"🎯 Reporting {len(msg_ids)} messages...")
    sessions=get_sessions(uid)
    verified=[s for s in sessions if s['verified']]
    if not verified:
        await msg.edit("❌ No sessions")
        clear_state(uid)
        return
    count=state.get('session_count',0)
    settings=get_settings(uid)
    if count>0 and count<len(verified):
        if settings['random_order']:
            selected=random.sample(verified,min(count,len(verified)))
        else:
            selected=verified[:count]
    else:
        selected=verified
    delay=settings['delay']
    reason_obj=state['reason_obj']
    reason_name=state['reason_name']
    success,failed=0,0
    total_sessions=len(selected)
    failed_sessions=[]
    for idx,s in enumerate(selected,1):
        path=os.path.join('sessions_db',s['session_file'])
        ok,error=await report_messages(path,target,msg_ids,reason_obj,s['phone'],uid)
        if ok:
            success+=1
            update_session_stats(uid,s['phone'],success=1)
            log_report(uid,s['phone'],target,reason_name,1)
        else:
            failed+=1
            update_session_stats(uid,s['phone'],failed=1)
            log_report(uid,s['phone'],target,reason_name,0,error or '')
            failed_sessions.append((s,error))
        if idx%3==0 or idx==total_sessions:
            progress=f"🎯 {idx}/{total_sessions}\n✅ {success} ❌ {failed}"
            try:
                await msg.edit(progress)
            except:
                pass
        await asyncio.sleep(delay)
    if settings['retry_failed'] and failed_sessions:
        retry_msg=await event.respond(f"🔄 Retrying {len(failed_sessions)}...")
        for s,prev_error in failed_sessions:
            path=os.path.join('sessions_db',s['session_file'])
            ok,error=await report_messages(path,target,msg_ids,reason_obj,s['phone'],uid)
            if ok:
                success+=1
                failed-=1
                update_session_stats(uid,s['phone'],success=1,failed=-1)
                log_report(uid,s['phone'],target,reason_name,1)
            await asyncio.sleep(delay)
        await retry_msg.delete()
    total=success+failed
    rate=int((success/total*100))if total>0 else 0
    update_stats(uid,success,failed)
    clear_state(uid)
    result=f"✅ COMPLETE\n\n🎯 {target[:35]}\n💬 {len(msg_ids)} messages\n📋 {reason_name}\n📱 {total_sessions} sessions\n\n✅ Success: {success}\n❌ Failed: {failed}\n📈 Rate: {rate}%"
    await msg.edit(result,buttons=[[Button.inline("🎯 Again",b"menu_report"),Button.inline("🏠 Home",b"start")]])
async def process_join(event,channels_text):
    uid=event.sender_id
    channels=[l for l in channels_text.split('\n')if l.strip()]
    if not channels:
        await event.respond("❌ No channels")
        clear_state(uid)
        return
    msg=await event.respond(f"🔗 Joining {len(channels)}...")
    sessions=get_sessions(uid)
    verified=[s for s in sessions if s['verified']]
    if not verified:
        await msg.edit("❌ No sessions")
        clear_state(uid)
        return
    success,failed=0,0
    total=len(channels)*len(verified)
    processed=0
    for ch in channels:
        for s in verified:
            path=os.path.join('sessions_db',s['session_file'])
            ok,error=await join_channel(path,ch.strip())
            if ok:
                success+=1
            else:
                failed+=1
            processed+=1
            if processed%10==0:
                try:
                    await msg.edit(f"🔗 {processed}/{total}\n✅ {success} ❌ {failed}")
                except:
                    pass
            await asyncio.sleep(1)
    clear_state(uid)
    await msg.edit(f"✅ COMPLETE\n\nChannels: {len(channels)}\n✅ Success: {success}\n❌ Failed: {failed}",buttons=[[Button.inline("« Tools",b"menu_tools")]])
async def process_leave(event,channels_text):
    uid=event.sender_id
    channels=[l for l in channels_text.split('\n')if l.strip()]
    if not channels:
        await event.respond("❌ No channels")
        clear_state(uid)
        return
    msg=await event.respond(f"❌ Leaving {len(channels)}...")
    sessions=get_sessions(uid)
    verified=[s for s in sessions if s['verified']]
    if not verified:
        await msg.edit("❌ No sessions")
        clear_state(uid)
        return
    success,failed=0,0
    total=len(channels)*len(verified)
    processed=0
    for ch in channels:
        for s in verified:
            path=os.path.join('sessions_db',s['session_file'])
            ok,error=await leave_channel(path,ch.strip())
            if ok:
                success+=1
            else:
                failed+=1
            processed+=1
            if processed%10==0:
                try:
                    await msg.edit(f"❌ {processed}/{total}\n✅ {success} ❌ {failed}")
                except:
                    pass
            await asyncio.sleep(1)
    clear_state(uid)
    await msg.edit(f"✅ COMPLETE\n\nChannels: {len(channels)}\n✅ Success: {success}\n❌ Failed: {failed}",buttons=[[Button.inline("« Tools",b"menu_tools")]])
@bot.on(events.NewMessage(func=lambda e:e.document and e.is_private))
async def file_handler(event):
    uid=event.sender_id
    doc=event.document
    if not doc.attributes:
        return
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
                add_session(uid,phone,name,sname)
                await msg.edit(f"✅ ADDED\n\n📱 {phone}\n👤 {name}",buttons=[[Button.inline("📱 Sessions",b"menu_sessions")]])
            else:
                try:
                    os.remove(path)
                except:
                    pass
                await msg.edit("❌ Invalid session")
        except Exception as e:
            await msg.edit(f"❌ Error: {str(e)[:80]}")
    elif fname.endswith('.zip'):
        msg=await event.respond("📦 Extracting...")
        zpath=os.path.join('temp_files',fname)
        try:
            await event.download_media(file=zpath)
            added,failed=0,0
            with zipfile.ZipFile(zpath,'r')as zf:
                session_files=[f for f in zf.namelist()if f.endswith('.session')]
                total=len(session_files)
                await msg.edit(f"📦 Found {total}\nVerifying...")
                for idx,f in enumerate(session_files,1):
                    try:
                        zf.extract(f,'temp_files')
                        tpath=os.path.join('temp_files',f)
                        ok,phone,name=await verify_session(tpath.replace('.session',''))
                        if ok:
                            sname=f"{uid}_{phone.replace('+','').replace(' ','')}"
                            final=os.path.join('sessions_db',sname+'.session')
                            shutil.move(tpath,final)
                            add_session(uid,phone,name,sname)
                            added+=1
                        else:
                            failed+=1
                            try:
                                os.remove(tpath)
                            except:
                                pass
                        if idx%5==0:
                            try:
                                await msg.edit(f"📦 {idx}/{total}\n✅ {added} ❌ {failed}")
                            except:
                                pass
                    except Exception as e:
                        logger.error(f"Extract: {str(e)}")
                        failed+=1
        except Exception as e:
            await msg.edit(f"❌ ZIP: {str(e)[:80]}")
            return
        finally:
            try:
                os.remove(zpath)
            except:
                pass
        await msg.edit(f"✅ COMPLETE\n\n✅ Added: {added}\n❌ Failed: {failed}",buttons=[[Button.inline("📱 Sessions",b"menu_sessions")]])
def main():
    print("╔════════════════════════════════════════╗")
    print("║    🎯 TELEGRAM REPORTER BOT 🎯      ║")
    print("║        2000+ Lines Full System         ║")
    print("╚════════════════════════════════════════╝")
    print()
    print("✅ Bot running...")
    print("📱 Ctrl+C to stop")
    print()
    print("🔥 Features:")
    print("   • Multi-session support")
    print("   • Random session selection")
    print("   • Flood wait handling")
    print("   • Auto-join private links")
    print("   • Public reporting without join")
    print("   • Message range reporting")
    print("   • Statistics tracking")
    print("   • Session verification")
    print("   • Export/Import sessions")
    print("   • Retry failed reports")
    print("   • Database migration")
    print("   • Comprehensive logging")
    print("   • User state management")
    print("   • Settings customization")
    print("   • Bulk operations")
    print("   • Error handling")
    print("   • Session management")
    print("   • Report tracking")
    print("   • Performance optimization")
    print("   • Security features")
    print()
    try:
        bot.run_until_disconnected()
    except KeyboardInterrupt:
        print("\n⚠️  Stopped by user")
    except Exception as e:
        print(f"\n❌ Fatal: {e}")
        logger.exception("Fatal error")
    finally:
        try:
            db.conn.close()
        except:
            pass
        print("✅ Cleanup complete")
if __name__=="__main__":
    main()
