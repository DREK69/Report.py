#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ADVANCED TELEGRAM REPORTER BOT - PROFESSIONAL EDITION v5.0
Complete bot system with owner/user separation, approval workflow, and advanced settings
"""

import os, sys, json, asyncio, zipfile, shutil, time, random, logging, sqlite3, hashlib, re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from telethon import TelegramClient, events, Button
from telethon.errors import *
from telethon.tl.functions.account import ReportPeerRequest
from telethon.tl.functions.messages import ReportRequest, CheckChatInviteRequest, ImportChatInviteRequest, GetMessagesRequest
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.types import *

# ===================== CONFIGURATION =====================
API_ID = 25723056
API_HASH = "cbda56fac135e92b755e1243aefe9697"
BOT_TOKEN = "8528337956:AAGU7PX6JooceLLL7HkH_LJ27v-QaKyrZVw"
OWNER_IDS = [8101867786]  # Bot owner IDs
REQUIRED_CHANNEL = "https://t.me/+-nGOXtIfUrBkOGM1"

# Create necessary directories
for d in ['sessions_db', 'temp_files', 'data', 'backups', 'logs', 'exports', 'cache', 'reports']:
    os.makedirs(d, exist_ok=True)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(f'logs/bot_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===================== DATABASE CLASS =====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('data/advanced_reporter.db', check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.init_db()
        self.migrate()
        self.optimize()
    
    def init_db(self):
        c = self.conn.cursor()
        c.executescript('''
            -- Users table with enhanced fields
            CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_date TEXT,
                last_active TEXT,
                is_owner INTEGER DEFAULT 0,
                is_approved INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                approval_type TEXT,
                approved_by INTEGER,
                approved_date TEXT,
                channel_joined INTEGER DEFAULT 0,
                total_reports INTEGER DEFAULT 0,
                successful_reports INTEGER DEFAULT 0
            );
            
            -- Sessions table
            CREATE TABLE IF NOT EXISTS sessions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                phone TEXT UNIQUE,
                name TEXT,
                session_file TEXT,
                verified INTEGER DEFAULT 0,
                added_date TEXT,
                total_reports INTEGER DEFAULT 0,
                success_reports INTEGER DEFAULT 0,
                failed_reports INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                last_used TEXT,
                health_score INTEGER DEFAULT 100
            );
            
            -- Reports table with message details
            CREATE TABLE IF NOT EXISTS reports(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                session_phone TEXT,
                target TEXT,
                target_type TEXT,
                message_link TEXT,
                message_id INTEGER,
                reason TEXT,
                reason_name TEXT,
                success INTEGER,
                timestamp TEXT,
                error_msg TEXT,
                execution_time REAL
            );
            
            -- Global settings (owner only)
            CREATE TABLE IF NOT EXISTS global_settings(
                id INTEGER PRIMARY KEY DEFAULT 1,
                delay_min INTEGER DEFAULT 2,
                delay_max INTEGER DEFAULT 5,
                max_reports_per_id INTEGER DEFAULT 20,
                require_approval INTEGER DEFAULT 1,
                auto_approve_enabled INTEGER DEFAULT 0,
                default_user_sessions INTEGER DEFAULT 5,
                default_user_reports_per_day INTEGER DEFAULT 50,
                flood_protection INTEGER DEFAULT 1,
                maintenance_mode INTEGER DEFAULT 0
            );
            
            -- User settings
            CREATE TABLE IF NOT EXISTS user_settings(
                user_id INTEGER PRIMARY KEY,
                reports_per_target INTEGER DEFAULT 1,
                selected_sessions INTEGER DEFAULT 0,
                delay_seconds INTEGER DEFAULT 3,
                auto_join INTEGER DEFAULT 1,
                random_order INTEGER DEFAULT 1
            );
            
            -- Approval requests
            CREATE TABLE IF NOT EXISTS approval_requests(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                first_name TEXT,
                requested_date TEXT,
                status TEXT DEFAULT 'pending',
                reviewed_by INTEGER,
                reviewed_date TEXT,
                notes TEXT,
                approval_duration_days INTEGER
            );
            
            -- Pending reports (before approval)
            CREATE TABLE IF NOT EXISTS pending_reports(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                target TEXT,
                target_type TEXT,
                message_link TEXT,
                message_id INTEGER,
                reason TEXT,
                reason_name TEXT,
                reports_count INTEGER,
                sessions_count INTEGER,
                requested_date TEXT,
                status TEXT DEFAULT 'pending',
                approved_by INTEGER,
                approved_date TEXT,
                scheduled_time TEXT
            );
            
            -- Statistics
            CREATE TABLE IF NOT EXISTS statistics(
                user_id INTEGER PRIMARY KEY,
                total_sessions INTEGER DEFAULT 0,
                active_sessions INTEGER DEFAULT 0,
                total_reports INTEGER DEFAULT 0,
                successful_reports INTEGER DEFAULT 0,
                failed_reports INTEGER DEFAULT 0,
                last_report_date TEXT,
                targets_reported INTEGER DEFAULT 0
            );
            
            -- Flood wait tracking
            CREATE TABLE IF NOT EXISTS flood_wait(
                session_phone TEXT PRIMARY KEY,
                wait_until TEXT,
                wait_seconds INTEGER
            );
            
            -- Create indexes
            CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, is_active);
            CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status, requested_date);
            CREATE INDEX IF NOT EXISTS idx_pending_reports_status ON pending_reports(status, requested_date);
            
            -- Insert default global settings
            INSERT OR IGNORE INTO global_settings(id) VALUES(1);
        ''')
        self.conn.commit()
    
    def migrate(self):
        """Handle database migrations for new columns"""
        c = self.conn.cursor()
        migrations = [
            ("is_owner", "users", "ALTER TABLE users ADD COLUMN is_owner INTEGER DEFAULT 0"),
            ("message_link", "reports", "ALTER TABLE reports ADD COLUMN message_link TEXT"),
            ("message_id", "reports", "ALTER TABLE reports ADD COLUMN message_id INTEGER"),
            ("reason_name", "reports", "ALTER TABLE reports ADD COLUMN reason_name TEXT"),
        ]
        
        for col, table, sql in migrations:
            try:
                c.execute(f"SELECT {col} FROM {table} LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    c.execute(sql)
                    self.conn.commit()
                except:
                    pass
    
    def optimize(self):
        c = self.conn.cursor()
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA cache_size=10000")
        c.execute("PRAGMA temp_store=MEMORY")
        self.conn.commit()
    
    def execute(self, query, params=()):
        try:
            c = self.conn.cursor()
            c.execute(query, params)
            self.conn.commit()
            return c
        except Exception as e:
            logger.error(f"DB Error: {e}")
            return None
    
    def fetchone(self, query, params=()):
        c = self.execute(query, params)
        if c:
            row = c.fetchone()
            return dict(row) if row else None
        return None
    
    def fetchall(self, query, params=()):
        c = self.execute(query, params)
        return [dict(row) for row in c.fetchall()] if c else []

# Initialize database
db = Database()

# Initialize bot
bot = TelegramClient('advanced_reporter_bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ===================== REPORT REASONS =====================
REASONS = {
    "1": ("📧 Spam", InputReportReasonSpam()),
    "2": ("⚔️ Violence", InputReportReasonViolence()),
    "3": ("🔞 Pornography", InputReportReasonPornography()),
    "4": ("👶 Child Abuse", InputReportReasonChildAbuse()),
    "5": ("© Copyright", InputReportReasonCopyright()),
    "6": ("🎭 Fake Account", InputReportReasonFake()),
    "7": ("💊 Illegal Drugs", InputReportReasonIllegalDrugs()),
    "8": ("🔐 Personal Info", InputReportReasonPersonalDetails()),
    "9": ("🌍 Geo Irrelevant", InputReportReasonGeoIrrelevant()),
    "10": ("❓ Other", InputReportReasonOther()),
    "11": ("💣 Terrorism", InputReportReasonViolence()),
    "12": ("💰 Scam", InputReportReasonOther()),
    "13": ("😡 Harassment", InputReportReasonOther()),
    "14": ("🤖 Bot Spam", InputReportReasonSpam()),
    "15": ("🎯 Custom", InputReportReasonOther()),
    "16": ("🎣 Phishing", InputReportReasonOther()),
    "17": ("🦠 Malware", InputReportReasonOther()),
    "18": ("💀 Self Harm", InputReportReasonViolence()),
    "19": ("🐕 Animal Abuse", InputReportReasonViolence()),
    "20": ("☠️ Extremism", InputReportReasonViolence())
}

# ===================== USER STATE MANAGEMENT =====================
user_states = {}

def set_state(uid, state, **data):
    user_states[uid] = {'state': state, 'timestamp': time.time(), **data}

def get_state(uid):
    state = user_states.get(uid)
    if state and time.time() - state.get('timestamp', 0) > 1800:
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

# ===================== HELPER FUNCTIONS =====================
def is_owner(uid):
    """Check if user is bot owner"""
    return uid in OWNER_IDS

async def check_channel_membership(uid):
    """Check if user has joined the required channel"""
    try:
        user_client = await bot.get_entity(uid)
        channel_link = REQUIRED_CHANNEL
        
        if '/+' in channel_link or '/joinchat/' in channel_link:
            hash_part = channel_link.split('/')[-1].replace('+', '')
            try:
                chat_invite = await bot(CheckChatInviteRequest(hash_part))
                if hasattr(chat_invite, 'chat'):
                    try:
                        participant = await bot.get_participants(chat_invite.chat, limit=1, 
                                                                search=user_client.username or str(uid))
                        return len(participant) > 0
                    except:
                        return False
            except:
                return False
        else:
            username = channel_link.split('/')[-1].replace('@', '')
            try:
                channel = await bot.get_entity(username)
                participants = await bot.get_participants(channel, limit=1, 
                                                         search=user_client.username or str(uid))
                return len(participants) > 0
            except:
                return False
    except:
        return False
    return False

def check_user_access(uid):
    """Check if user has access to the bot"""
    user = db.fetchone('SELECT is_approved, is_banned, is_owner, channel_joined FROM users WHERE user_id=?', (uid,))
    
    if not user:
        return False, 'not_registered'
    
    if user['is_banned']:
        return False, 'banned'
    
    if user['is_owner'] or is_owner(uid):
        return True, 'owner'
    
    if not user['channel_joined']:
        return False, 'not_joined'
    
    if not user['is_approved']:
        return False, 'not_approved'
    
    return True, 'approved'

def register_user(uid, username, first_name):
    """Register a new user"""
    existing = db.fetchone('SELECT user_id FROM users WHERE user_id=?', (uid,))
    if existing:
        db.execute('UPDATE users SET username=?, first_name=?, last_active=?, is_owner=? WHERE user_id=?',
                  (username, first_name, datetime.now().isoformat(), 1 if is_owner(uid) else 0, uid))
    else:
        db.execute('''INSERT INTO users(user_id, username, first_name, joined_date, last_active, is_owner, is_approved) 
                     VALUES(?, ?, ?, ?, ?, ?, ?)''',
                  (uid, username, first_name, datetime.now().isoformat(), 
                   datetime.now().isoformat(), 1 if is_owner(uid) else 0, 1 if is_owner(uid) else 0))
        
        # Initialize user settings
        db.execute('INSERT OR IGNORE INTO user_settings(user_id) VALUES(?)', (uid,))
        db.execute('INSERT OR IGNORE INTO statistics(user_id) VALUES(?)', (uid,))

async def add_session_from_file(uid, session_path, phone, name):
    """Add a session to user's account"""
    try:
        # Verify session is valid
        temp_client = TelegramClient(session_path, API_ID, API_HASH)
        try:
            await temp_client.connect()
            if not await temp_client.is_user_authorized():
                await temp_client.disconnect()
                return False, "Session not authorized"
            
            me = await temp_client.get_me()
            actual_phone = me.phone if me.phone else phone
            await temp_client.disconnect()
            
            # Move to sessions_db
            final_path = os.path.join('sessions_db', f"{uid}_{actual_phone.replace('+', '').replace(' ', '')}.session")
            shutil.move(session_path, final_path)
            
            # Add to database
            db.execute('''INSERT OR REPLACE INTO sessions(user_id, phone, name, session_file, verified, added_date, is_active, health_score)
                         VALUES(?, ?, ?, ?, 1, ?, 1, 100)''',
                      (uid, actual_phone, name or f"Session {actual_phone}", 
                       os.path.basename(final_path), datetime.now().isoformat()))
            
            # Update statistics
            db.execute('''UPDATE statistics SET total_sessions = total_sessions + 1, 
                         active_sessions = (SELECT COUNT(*) FROM sessions WHERE user_id=? AND is_active=1)
                         WHERE user_id=?''', (uid, uid))
            
            return True, "Session added successfully"
            
        except Exception as e:
            await temp_client.disconnect()
            return False, f"Session verification failed: {str(e)}"
            
    except Exception as e:
        return False, f"Error adding session: {str(e)}"

# ===================== START COMMAND =====================
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    uid = event.sender_id
    user = await event.get_sender()
    username = user.username or ""
    first_name = user.first_name or "User"
    
    # Register user
    register_user(uid, username, first_name)
    
    # Update last active
    db.execute('UPDATE users SET last_active=? WHERE user_id=?', (datetime.now().isoformat(), uid))
    
    # Check access
    has_access, reason = check_user_access(uid)
    
    welcome_text = f"""╔═══════════════════════════════╗
║  🎯 ADVANCED REPORTER BOT 🎯  ║
║     Professional Edition       ║
╚═══════════════════════════════╝

👋 Welcome, {first_name}!

"""
    
    if is_owner(uid):
        welcome_text += """🔱 OWNER ACCESS GRANTED

You have full control over:
├ 👥 User Management
├ ⚙️ Global Settings
├ ✅ Approval System
├ 📊 Full Statistics
└ 🎯 All Features

"""
        buttons = [
            [Button.inline("👑 Owner Menu", "owner_menu")],
            [Button.inline("📊 Bot Statistics", "owner_stats")],
            [Button.inline("⚙️ Global Settings", "owner_settings")],
            [Button.inline("✅ Approvals", "owner_approvals")],
            [Button.inline("🎯 Report (Owner)", "menu_main")]
        ]
        
    else:
        # Check channel membership
        if not has_access or reason == 'not_joined':
            channel_joined = await check_channel_membership(uid)
            if channel_joined:
                db.execute('UPDATE users SET channel_joined=1 WHERE user_id=?', (uid,))
                has_access, reason = check_user_access(uid)
            else:
                welcome_text += f"""⚠️ CHANNEL VERIFICATION REQUIRED

To use this bot, you must join our channel:
{REQUIRED_CHANNEL}

After joining, click the button below:"""
                await event.respond(welcome_text, buttons=[
                    [Button.url("📢 Join Channel", REQUIRED_CHANNEL)],
                    [Button.inline("✅ I Joined", "verify_channel")]
                ])
                return
        
        if reason == 'not_approved':
            # Check if already requested
            existing_request = db.fetchone(
                "SELECT id FROM approval_requests WHERE user_id=? AND status='pending'", (uid,)
            )
            
            if existing_request:
                welcome_text += """⏳ APPROVAL PENDING

Your access request is being reviewed.
Please wait for owner approval.

Status: Waiting for Review"""
            else:
                welcome_text += """🔐 APPROVAL REQUIRED

Your account needs approval from the bot owner.
Click below to request access:"""
                buttons = [[Button.inline("📝 Request Access", "request_approval")]]
                await event.respond(welcome_text, buttons=buttons)
                return
            
            await event.respond(welcome_text, buttons=[[Button.inline("🔄 Check Status", "/start")]])
            return
        
        welcome_text += """✅ ACCESS GRANTED

Available features:
├ 📱 Session Management
├ 🎯 Report Targets
├ 💬 Report Messages
├ 📊 Your Statistics
└ ⚙️ Your Settings

"""
        buttons = [
            [Button.inline("🎯 Start Reporting", "menu_main")],
            [Button.inline("📱 My Sessions", "menu_sessions")],
            [Button.inline("📊 My Stats", "menu_stats")],
            [Button.inline("⚙️ My Settings", "user_settings_menu")]
        ]
    
    await event.respond(welcome_text, buttons=buttons)

# ===================== CHANNEL VERIFICATION =====================
@bot.on(events.CallbackQuery(pattern=rb'verify_channel'))
async def verify_channel_handler(event):
    uid = event.sender_id
    
    channel_joined = await check_channel_membership(uid)
    
    if channel_joined:
        db.execute('UPDATE users SET channel_joined=1 WHERE user_id=?', (uid,))
        await event.answer("✅ Channel verified!", alert=True)
        # Restart
        await event.delete()
        await bot.send_message(uid, "/start")
    else:
        await event.answer("❌ You haven't joined the channel yet. Please join and try again.", alert=True)

# ===================== APPROVAL REQUEST =====================
@bot.on(events.CallbackQuery(pattern=rb'request_approval'))
async def request_approval_handler(event):
    uid = event.sender_id
    user = await event.get_sender()
    username = user.username or "No username"
    first_name = user.first_name or "User"
    
    # Check if already requested
    existing = db.fetchone("SELECT id FROM approval_requests WHERE user_id=? AND status='pending'", (uid,))
    
    if existing:
        await event.answer("⏳ You already have a pending request!", alert=True)
        return
    
    # Create approval request
    db.execute('''INSERT INTO approval_requests(user_id, username, first_name, requested_date)
                 VALUES(?, ?, ?, ?)''',
              (uid, username, first_name, datetime.now().isoformat()))
    
    await event.answer("✅ Request submitted! Wait for owner approval.", alert=True)
    
    # Notify all owners
    for owner_id in OWNER_IDS:
        try:
            await bot.send_message(owner_id, f"""📢 NEW APPROVAL REQUEST

👤 User: {first_name} (@{username})
🆔 ID: {uid}
📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}

Use /approvals to review.""")
        except:
            pass
    
    await event.edit("""✅ Access request submitted successfully!

Your request has been sent to the bot owner.
You will be notified once approved.

Please wait patiently.""", buttons=[[Button.inline("« Back", "/start")]])

# ===================== OWNER MENU =====================
@bot.on(events.CallbackQuery(pattern=rb'owner_menu'))
async def owner_menu_handler(event):
    uid = event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only", alert=True)
        return
    
    # Get stats
    total_users = db.fetchone("SELECT COUNT(*) as count FROM users")['count']
    approved_users = db.fetchone("SELECT COUNT(*) as count FROM users WHERE is_approved=1")['count']
    pending_approvals = db.fetchone("SELECT COUNT(*) as count FROM approval_requests WHERE status='pending'")['count']
    total_sessions = db.fetchone("SELECT COUNT(*) as count FROM sessions")['count']
    total_reports = db.fetchone("SELECT COUNT(*) as count FROM reports")['count']
    pending_reports = db.fetchone("SELECT COUNT(*) as count FROM pending_reports WHERE status='pending'")['count']
    
    text = f"""╔══════════════════════════════╗
║     👑 OWNER CONTROL PANEL    ║
╚══════════════════════════════╝

📊 BOT STATISTICS:
├ Total Users: {total_users}
├ Approved: {approved_users}
├ Pending Approvals: {pending_approvals}
├ Total Sessions: {total_sessions}
├ Total Reports: {total_reports}
└ Pending Reports: {pending_reports}

Select an option:"""
    
    buttons = [
        [Button.inline("✅ Pending Approvals", "owner_approvals"), Button.inline("📋 Pending Reports", "owner_pending_reports")],
        [Button.inline("👥 User Management", "owner_users"), Button.inline("📊 Statistics", "owner_stats")],
        [Button.inline("⚙️ Global Settings", "owner_settings"), Button.inline("📢 Broadcast", "owner_broadcast")],
        [Button.inline("🎯 Report (Owner)", "menu_main"), Button.inline("« Back", "/start")]
    ]
    
    await event.edit(text, buttons=buttons)

# ===================== OWNER APPROVALS =====================
@bot.on(events.CallbackQuery(pattern=rb'owner_approvals'))
async def owner_approvals_handler(event):
    uid = event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only", alert=True)
        return
    
    pending = db.fetchall("SELECT * FROM approval_requests WHERE status='pending' ORDER BY requested_date DESC LIMIT 10")
    
    if not pending:
        await event.edit("✅ No pending approval requests", buttons=[[Button.inline("« Back", "owner_menu")]])
        return
    
    text = "🔐 PENDING APPROVAL REQUESTS:\n\n"
    buttons = []
    
    for req in pending:
        req_date = datetime.fromisoformat(req['requested_date']).strftime('%Y-%m-%d %H:%M')
        text += f"━━━━━━━━━━━━━━━━\n"
        text += f"👤 {req['first_name']} (@{req['username']})\n"
        text += f"🆔 ID: {req['user_id']}\n"
        text += f"📅 {req_date}\n\n"
        
        buttons.append([
            Button.inline(f"✅ Approve", f"approve_{req['id']}"),
            Button.inline(f"❌ Reject", f"reject_{req['id']}")
        ])
    
    buttons.append([Button.inline("« Back", "owner_menu")])
    
    await event.edit(text, buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'approve_(\d+)'))
async def approve_user_handler(event):
    uid = event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only", alert=True)
        return
    
    req_id = int(event.data.decode().split('_')[1])
    req = db.fetchone('SELECT * FROM approval_requests WHERE id=?', (req_id,))
    
    if not req:
        await event.answer("❌ Request not found", alert=True)
        return
    
    # Ask for approval duration
    set_state(uid, 'approve_duration', req_id=req_id, user_id=req['user_id'])
    
    await event.edit(f"""✅ Approve User: {req['first_name']}

Select approval duration:""", buttons=[
        [Button.inline("🔓 Permanent", f"approve_perm_{req_id}")],
        [Button.inline("📅 7 Days Trial", f"approve_trial_7_{req_id}")],
        [Button.inline("📅 15 Days Trial", f"approve_trial_15_{req_id}")],
        [Button.inline("📅 30 Days Trial", f"approve_trial_30_{req_id}")],
        [Button.inline("« Cancel", "owner_approvals")]
    ])

@bot.on(events.CallbackQuery(pattern=rb'approve_(perm|trial_\d+)_(\d+)'))
async def process_approval_handler(event):
    uid = event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only", alert=True)
        return
    
    data_parts = event.data.decode().split('_')
    req_id = int(data_parts[-1])
    
    if data_parts[1] == 'perm':
        approval_type = 'permanent'
        days = None
    else:
        days = int(data_parts[2])
        approval_type = f'trial_{days}d'
    
    req = db.fetchone('SELECT * FROM approval_requests WHERE id=?', (req_id,))
    
    if not req:
        await event.answer("❌ Request not found", alert=True)
        return
    
    now = datetime.now().isoformat()
    
    # Update request
    db.execute('''UPDATE approval_requests SET status=?, reviewed_by=?, reviewed_date=?, approval_duration_days=?
                 WHERE id=?''', ('approved', uid, now, days, req_id))
    
    # Update user
    db.execute('''UPDATE users SET is_approved=1, approval_type=?, approved_by=?, approved_date=?
                 WHERE user_id=?''', (approval_type, uid, now, req['user_id']))
    
    await event.answer("✅ User approved!", alert=True)
    
    # Notify user
    approval_text = f"""╔══════════════════════════════╗
║      ✅ APPROVAL GRANTED      ║
╚══════════════════════════════╝

Your access request has been approved!

Type: {approval_type.upper()}
"""
    if days:
        approval_text += f"Valid for: {days} days\n"
    
    approval_text += "\nYou can now use all bot features!"
    
    try:
        await bot.send_message(req['user_id'], approval_text, buttons=[[Button.inline("🎯 Start", "/start")]])
    except:
        pass
    
    # Refresh approvals list
    await owner_approvals_handler(event)

@bot.on(events.CallbackQuery(pattern=rb'reject_(\d+)'))
async def reject_user_handler(event):
    uid = event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only", alert=True)
        return
    
    req_id = int(event.data.decode().split('_')[1])
    req = db.fetchone('SELECT * FROM approval_requests WHERE id=?', (req_id,))
    
    if not req:
        await event.answer("❌ Request not found", alert=True)
        return
    
    now = datetime.now().isoformat()
    
    # Update request
    db.execute('''UPDATE approval_requests SET status=?, reviewed_by=?, reviewed_date=?
                 WHERE id=?''', ('rejected', uid, now, req_id))
    
    await event.answer("❌ Request rejected", alert=True)
    
    # Notify user
    try:
        await bot.send_message(req['user_id'], """╔══════════════════════════════╗
║      ❌ REQUEST DENIED        ║
╚══════════════════════════════╝

Your access request has been reviewed and denied.

If you believe this was a mistake, please contact support.""")
    except:
        pass
    
    # Refresh approvals list
    await owner_approvals_handler(event)

# ===================== MAIN MENU =====================
@bot.on(events.CallbackQuery(pattern=rb'menu_main'))
async def main_menu_handler(event):
    uid = event.sender_id
    
    has_access, reason = check_user_access(uid)
    
    if not has_access:
        if reason == 'not_joined':
            await event.answer("❌ Please join the required channel first!", alert=True)
        elif reason == 'not_approved':
            await event.answer("❌ Your account is not approved yet!", alert=True)
        elif reason == 'banned':
            await event.answer("❌ Your account has been banned!", alert=True)
        else:
            await event.answer("❌ Access denied!", alert=True)
        return
    
    # Get user stats
    stats = db.fetchone('SELECT * FROM statistics WHERE user_id=?', (uid,)) or {}
    sessions_count = stats.get('active_sessions', 0)
    
    text = f"""╔══════════════════════════════╗
║       🎯 REPORTER MENU 🎯      ║
╚══════════════════════════════╝

📊 Your Stats:
├ Sessions: {sessions_count}
├ Total Reports: {stats.get('total_reports', 0)}
└ Success: {stats.get('successful_reports', 0)}

Select report type:"""
    
    buttons = [
        [Button.inline("👤 Report User/Channel", "report_peer")],
        [Button.inline("💬 Report Message", "report_message")],
        [Button.inline("📱 My Sessions", "menu_sessions")],
        [Button.inline("📊 Statistics", "menu_stats"), Button.inline("⚙️ Settings", "user_settings_menu")]
    ]
    
    if is_owner(uid):
        buttons.append([Button.inline("👑 Owner Menu", "owner_menu")])
    
    buttons.append([Button.inline("« Back", "/start")])
    
    await event.edit(text, buttons=buttons)

# ===================== REPORT PEER =====================
@bot.on(events.CallbackQuery(pattern=rb'report_peer'))
async def report_peer_handler(event):
    uid = event.sender_id
    
    has_access, reason = check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!", alert=True)
        return
    
    set_state(uid, 'awaiting_target')
    
    await event.edit("""🎯 REPORT USER/CHANNEL/GROUP

Send me the target:
├ Username: @username
├ User ID: 123456789
├ Channel Link: https://t.me/channel
├ Group Link: https://t.me/group
└ Private Group Link: https://t.me/+...

Type /cancel to cancel""", buttons=[[Button.inline("« Cancel", "menu_main")]])

@bot.on(events.NewMessage(pattern=r'^(?!/).*'))
async def message_handler(event):
    uid = event.sender_id
    state = get_state(uid)
    
    if not state:
        return
    
    if state['state'] == 'awaiting_target':
        target = event.text.strip()
        
        # Validate target
        if not target:
            await event.respond("❌ Invalid target!")
            return
        
        set_state(uid, 'select_reason', target=target, target_type='peer')
        
        # Show reason selection
        text = f"🎯 Target: {target}\n\n📝 Select report reason:"
        
        buttons = []
        for i in range(1, 21, 2):
            row = []
            if str(i) in REASONS:
                row.append(Button.inline(REASONS[str(i)][0], f"reason_{i}"))
            if str(i+1) in REASONS:
                row.append(Button.inline(REASONS[str(i+1)][0], f"reason_{i+1}"))
            if row:
                buttons.append(row)
        
        buttons.append([Button.inline("« Cancel", "menu_main")])
        
        await event.respond(text, buttons=buttons)
    
    elif state['state'] == 'awaiting_reports_count':
        try:
            count = int(event.text.strip())
            if count < 1 or count > 20:
                await event.respond("❌ Please enter a number between 1 and 20")
                return
            
            state['reports_count'] = count
            set_state(uid, 'awaiting_sessions_count', **state)
            
            # Get available sessions
            sessions = db.fetchall('SELECT COUNT(*) as count FROM sessions WHERE user_id=? AND is_active=1', (uid,))
            available = sessions[0]['count'] if sessions else 0
            
            await event.respond(f"""✅ Reports per session: {count}

📱 Available sessions: {available}

How many sessions to use? (1-{available})

Type /cancel to cancel""")
            
        except ValueError:
            await event.respond("❌ Please enter a valid number")

    elif state['state'] == 'awaiting_sessions_count':
        try:
            count = int(event.text.strip())
            
            # Get available sessions
            sessions = db.fetchall('SELECT COUNT(*) as count FROM sessions WHERE user_id=? AND is_active=1', (uid,))
            available = sessions[0]['count'] if sessions else 0
            
            if count < 1 or count > available:
                await event.respond(f"❌ Please enter a number between 1 and {available}")
                return
            
            state['sessions_count'] = count
            
            # Create pending report if owner requires approval
            global_settings = db.fetchone('SELECT * FROM global_settings WHERE id=1')
            
            if is_owner(uid) or not global_settings['require_approval']:
                # Direct execution
                await event.respond("⏳ Preparing to execute report...")
                await execute_report(uid, state)
            else:
                # Create pending report
                db.execute('''INSERT INTO pending_reports(user_id, target, target_type, message_link, message_id, 
                             reason, reason_name, reports_count, sessions_count, requested_date)
                             VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                          (uid, state['target'], state.get('target_type', 'peer'), 
                           state.get('message_link'), state.get('message_id'),
                           state['reason'], state['reason_name'], 
                           state['reports_count'], count, datetime.now().isoformat()))
                
                await event.respond("""✅ Report request submitted!

Your report has been queued for owner approval.
You will be notified once it's approved.

📊 Summary:
├ Target: {}
├ Reason: {}
├ Reports: {}
└ Sessions: {}""".format(
                    state['target'], 
                    state['reason_name'],
                    state['reports_count'],
                    count
                ), buttons=[[Button.inline("« Menu", "menu_main")]])
                
                # Notify owners
                for owner_id in OWNER_IDS:
                    try:
                        user = db.fetchone('SELECT first_name, username FROM users WHERE user_id=?', (uid,))
                        await bot.send_message(owner_id, f"""📢 NEW REPORT REQUEST

👤 User: {user['first_name']} (@{user['username']})
🎯 Target: {state['target']}
📝 Reason: {state['reason_name']}
📊 Reports: {state['reports_count']} x {count} sessions

Use /pending to review.""")
                    except:
                        pass
                
                clear_state(uid)
            
        except ValueError:
            await event.respond("❌ Please enter a valid number")

# ===================== REASON SELECTION =====================
@bot.on(events.CallbackQuery(pattern=rb'reason_(\d+)'))
async def reason_selection_handler(event):
    uid = event.sender_id
    state = get_state(uid)
    
    if not state:
        await event.answer("❌ Session expired", alert=True)
        return
    
    reason_id = event.data.decode().split('_')[1]
    reason_name, reason_obj = REASONS[reason_id]
    
    state['reason'] = reason_id
    state['reason_name'] = reason_name
    
    # Ask for reports count
    set_state(uid, 'awaiting_reports_count', **state)
    
    await event.edit(f"""✅ Selected: {reason_name}

🎯 Target: {state['target']}
📝 Reason: {reason_name}

How many reports per session? (1-20)

Type /cancel to cancel""", buttons=[[Button.inline("« Cancel", "menu_main")]])

# ===================== REPORT MESSAGE =====================
@bot.on(events.CallbackQuery(pattern=rb'report_message'))
async def report_message_handler(event):
    uid = event.sender_id
    
    has_access, reason = check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!", alert=True)
        return
    
    set_state(uid, 'awaiting_message_link')
    
    await event.edit("""💬 REPORT MESSAGE

Send me the message link:
https://t.me/channel/12345
or
https://t.me/c/123456/789

The message link must be from a public or private channel/group.

Type /cancel to cancel""", buttons=[[Button.inline("« Cancel", "menu_main")]])

@bot.on(events.NewMessage)
async def message_link_handler(event):
    uid = event.sender_id
    state = get_state(uid)
    
    if not state or state['state'] != 'awaiting_message_link':
        return
    
    message_link = event.text.strip()
    
    # Parse message link
    if 't.me/' not in message_link:
        await event.respond("❌ Invalid message link!")
        return
    
    try:
        # Extract message details
        if '/c/' in message_link:
            # Private channel format: t.me/c/123456/789
            parts = message_link.split('/c/')[-1].split('/')
            chat_id = int(parts[0])
            msg_id = int(parts[1])
            target = f"-100{chat_id}"
        else:
            # Public channel format: t.me/channel/123
            parts = message_link.split('/')
            channel = parts[-2]
            msg_id = int(parts[-1])
            target = channel
        
        set_state(uid, 'select_reason', target=target, target_type='message', 
                 message_link=message_link, message_id=msg_id)
        
        # Show reason selection
        text = f"💬 Message: {message_link}\n\n📝 Select report reason:"
        
        buttons = []
        for i in range(1, 21, 2):
            row = []
            if str(i) in REASONS:
                row.append(Button.inline(REASONS[str(i)][0], f"reason_{i}"))
            if str(i+1) in REASONS:
                row.append(Button.inline(REASONS[str(i+1)][0], f"reason_{i+1}"))
            if row:
                buttons.append(row)
        
        buttons.append([Button.inline("« Cancel", "menu_main")])
        
        await event.respond(text, buttons=buttons)
        
    except Exception as e:
        await event.respond(f"❌ Error parsing message link: {str(e)}")
        return

# ===================== EXECUTE REPORT =====================
async def execute_report(uid, state):
    """Execute the actual reporting process"""
    try:
        target = state['target']
        reason_id = state['reason']
        reason_name = state['reason_name']
        reports_count = state['reports_count']
        sessions_count = state['sessions_count']
        target_type = state.get('target_type', 'peer')
        message_link = state.get('message_link')
        message_id = state.get('message_id')
        
        # Get reason object
        _, reason_obj = REASONS[reason_id]
        
        # Get sessions
        sessions = db.fetchall('''SELECT * FROM sessions WHERE user_id=? AND is_active=1 
                                 ORDER BY health_score DESC LIMIT ?''', (uid, sessions_count))
        
        if not sessions:
            await bot.send_message(uid, "❌ No active sessions found!")
            clear_state(uid)
            return
        
        # Get settings
        global_settings = db.fetchone('SELECT * FROM global_settings WHERE id=1')
        delay_min = global_settings['delay_min']
        delay_max = global_settings['delay_max']
        
        # Progress message
        progress_msg = await bot.send_message(uid, f"""⏳ EXECUTING REPORT

🎯 Target: {target}
📝 Reason: {reason_name}
📊 Reports: {reports_count} x {sessions_count} sessions
💤 Delay: {delay_min}-{delay_max}s

Progress: 0/{sessions_count} sessions""")
        
        total_success = 0
        total_failed = 0
        
        for idx, session in enumerate(sessions, 1):
            session_path = os.path.join('sessions_db', session['session_file'])
            
            if not os.path.exists(session_path):
                total_failed += reports_count
                continue
            
            try:
                client = TelegramClient(session_path, API_ID, API_HASH)
                await client.connect()
                
                if not await client.is_user_authorized():
                    total_failed += reports_count
                    await client.disconnect()
                    continue
                
                # Execute reports
                for rep in range(reports_count):
                    try:
                        start_time = time.time()
                        
                        if target_type == 'message' and message_id:
                            # Report message
                            entity = await client.get_entity(target)
                            await client(ReportRequest(
                                peer=entity,
                                id=[message_id],
                                reason=reason_obj,
                                message="Violation"
                            ))
                        else:
                            # Report peer
                            entity = await client.get_entity(target)
                            await client(ReportPeerRequest(
                                peer=entity,
                                reason=reason_obj,
                                message="Violation"
                            ))
                        
                        execution_time = time.time() - start_time
                        
                        # Log success
                        db.execute('''INSERT INTO reports(user_id, session_phone, target, target_type, 
                                     message_link, message_id, reason, reason_name, success, timestamp, execution_time)
                                     VALUES(?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)''',
                                  (uid, session['phone'], target, target_type, message_link, message_id,
                                   reason_id, reason_name, datetime.now().isoformat(), execution_time))
                        
                        total_success += 1
                        
                        # Update session stats
                        db.execute('''UPDATE sessions SET success_reports=success_reports+1, 
                                     total_reports=total_reports+1, last_used=? WHERE id=?''',
                                  (datetime.now().isoformat(), session['id']))
                        
                        # Delay
                        if rep < reports_count - 1:
                            await asyncio.sleep(random.uniform(delay_min, delay_max))
                    
                    except FloodWaitError as e:
                        # Handle flood wait
                        wait_time = e.seconds
                        db.execute('''INSERT OR REPLACE INTO flood_wait(session_phone, wait_until, wait_seconds)
                                     VALUES(?, ?, ?)''',
                                  (session['phone'], 
                                   (datetime.now() + timedelta(seconds=wait_time)).isoformat(),
                                   wait_time))
                        
                        total_failed += (reports_count - rep)
                        break
                    
                    except Exception as e:
                        # Log error
                        db.execute('''INSERT INTO reports(user_id, session_phone, target, target_type,
                                     message_link, message_id, reason, reason_name, success, timestamp, error_msg)
                                     VALUES(?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)''',
                                  (uid, session['phone'], target, target_type, message_link, message_id,
                                   reason_id, reason_name, datetime.now().isoformat(), str(e)[:200]))
                        
                        total_failed += 1
                
                await client.disconnect()
                
                # Update progress
                try:
                    await progress_msg.edit(f"""⏳ EXECUTING REPORT

🎯 Target: {target}
📝 Reason: {reason_name}
📊 Reports: {reports_count} x {sessions_count} sessions
💤 Delay: {delay_min}-{delay_max}s

Progress: {idx}/{sessions_count} sessions
✅ Success: {total_success}
❌ Failed: {total_failed}""")
                except:
                    pass
                
                # Delay between sessions
                if idx < sessions_count:
                    await asyncio.sleep(random.uniform(delay_min, delay_max))
            
            except Exception as e:
                logger.error(f"Session error: {e}")
                total_failed += reports_count
        
        # Update user statistics
        db.execute('''UPDATE statistics SET total_reports=total_reports+?, successful_reports=successful_reports+?,
                     failed_reports=failed_reports+?, last_report_date=?, targets_reported=targets_reported+1
                     WHERE user_id=?''',
                  (total_success + total_failed, total_success, total_failed, 
                   datetime.now().isoformat(), uid))
        
        db.execute('''UPDATE users SET total_reports=total_reports+?, successful_reports=successful_reports+?
                     WHERE user_id=?''', (total_success + total_failed, total_success, uid))
        
        # Final message
        success_rate = (total_success / (total_success + total_failed) * 100) if (total_success + total_failed) > 0 else 0
        
        await progress_msg.edit(f"""✅ REPORT COMPLETED

🎯 Target: {target}
📝 Reason: {reason_name}

📊 RESULTS:
├ Total: {total_success + total_failed}
├ Success: ✅ {total_success}
├ Failed: ❌ {total_failed}
└ Rate: {success_rate:.1f}%

{'🎉 All reports successful!' if total_failed == 0 else '⚠️ Some reports failed'}""",
            buttons=[[Button.inline("🎯 Report Again", "menu_main")], [Button.inline("« Back", "/start")]])
        
        clear_state(uid)
    
    except Exception as e:
        logger.error(f"Execute report error: {e}")
        await bot.send_message(uid, f"❌ Error executing report: {str(e)}")
        clear_state(uid)

# ===================== SESSIONS MENU =====================
@bot.on(events.CallbackQuery(pattern=rb'menu_sessions'))
async def sessions_menu_handler(event):
    uid = event.sender_id
    
    has_access, reason = check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!", alert=True)
        return
    
    # Get sessions
    sessions = db.fetchall('SELECT * FROM sessions WHERE user_id=? ORDER BY added_date DESC', (uid,))
    
    text = f"""╔══════════════════════════════╗
║      📱 SESSION MANAGER       ║
╚══════════════════════════════╝

Total Sessions: {len(sessions)}
Active: {sum(1 for s in sessions if s['is_active'])}

"""
    
    if sessions:
        text += "Your sessions:\n\n"
        for sess in sessions[:5]:
            status = "✅" if sess['is_active'] else "❌"
            health = "💚" if sess['health_score'] > 80 else "💛" if sess['health_score'] > 50 else "❤️"
            text += f"{status} {sess['phone']}\n"
            text += f"   {health} Health: {sess['health_score']}% | Reports: {sess['success_reports']}/{sess['total_reports']}\n\n"
        
        if len(sessions) > 5:
            text += f"... and {len(sessions) - 5} more\n"
    else:
        text += "❌ No sessions added yet\n"
    
    buttons = [
        [Button.inline("➕ Add Session", "add_session")],
        [Button.inline("📦 Upload ZIP", "upload_zip")],
        [Button.inline("📋 View All", "view_sessions")],
        [Button.inline("« Back", "menu_main")]
    ]
    
    await event.edit(text, buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'add_session'))
async def add_session_handler(event):
    uid = event.sender_id
    
    has_access, reason = check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!", alert=True)
        return
    
    set_state(uid, 'awaiting_session_file')
    
    await event.edit("""➕ ADD SESSION

Send me your .session file

The file should be a Telethon session file.

Type /cancel to cancel""", buttons=[[Button.inline("« Cancel", "menu_sessions")]])

@bot.on(events.NewMessage)
async def session_file_handler(event):
    uid = event.sender_id
    state = get_state(uid)
    
    if not state or state['state'] != 'awaiting_session_file':
        return
    
    if not event.file:
        return
    
    # Check if it's a session file
    filename = event.file.name
    if not filename or not filename.endswith('.session'):
        await event.respond("❌ Please send a valid .session file")
        return
    
    try:
        # Download file
        file_path = await event.download_media(file=f"temp_files/{uid}_{int(time.time())}.session")
        
        # Extract phone from filename or ask
        phone = filename.replace('.session', '').strip()
        
        # Add session
        success, message = await add_session_from_file(uid, file_path, phone, phone)
        
        if success:
            await event.respond(f"✅ {message}", buttons=[[Button.inline("📱 Sessions", "menu_sessions")]])
        else:
            await event.respond(f"❌ {message}", buttons=[[Button.inline("🔄 Try Again", "add_session")]])
        
        clear_state(uid)
        
        # Clean up
        try:
            os.remove(file_path)
        except:
            pass
    
    except Exception as e:
        await event.respond(f"❌ Error: {str(e)}")
        clear_state(uid)

# ===================== USER SETTINGS =====================
@bot.on(events.CallbackQuery(pattern=rb'user_settings_menu'))
async def user_settings_menu_handler(event):
    uid = event.sender_id
    
    has_access, reason = check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!", alert=True)
        return
    
    # Get current settings
    settings = db.fetchone('SELECT * FROM user_settings WHERE user_id=?', (uid,)) or {}
    
    text = f"""╔══════════════════════════════╗
║      ⚙️ YOUR SETTINGS ⚙️       ║
╚══════════════════════════════╝

Current Settings:
├ Reports per target: {settings.get('reports_per_target', 1)}
├ Delay: {settings.get('delay_seconds', 3)}s
├ Auto join: {'✅' if settings.get('auto_join', 1) else '❌'}
└ Random order: {'✅' if settings.get('random_order', 1) else '❌'}

Select option to change:"""
    
    buttons = [
        [Button.inline("📊 Reports/Target", "setting_reports")],
        [Button.inline("⏱️ Delay Time", "setting_delay")],
        [Button.inline("🔀 Random Order", "setting_random")],
        [Button.inline("« Back", "menu_main")]
    ]
    
    await event.edit(text, buttons=buttons)

# ===================== OWNER SETTINGS =====================
@bot.on(events.CallbackQuery(pattern=rb'owner_settings'))
async def owner_settings_handler(event):
    uid = event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only", alert=True)
        return
    
    # Get global settings
    settings = db.fetchone('SELECT * FROM global_settings WHERE id=1')
    
    text = f"""╔══════════════════════════════╗
║     ⚙️ GLOBAL SETTINGS ⚙️      ║
╚══════════════════════════════╝

Current Global Settings:
├ Delay Min: {settings['delay_min']}s
├ Delay Max: {settings['delay_max']}s
├ Max Reports/ID: {settings['max_reports_per_id']}
├ Require Approval: {'✅' if settings['require_approval'] else '❌'}
├ Auto Approve: {'✅' if settings['auto_approve_enabled'] else '❌'}
├ Flood Protection: {'✅' if settings['flood_protection'] else '❌'}
└ Maintenance: {'✅' if settings['maintenance_mode'] else '❌'}

Select setting to modify:"""
    
    buttons = [
        [Button.inline("⏱️ Delay Settings", "gsetting_delay")],
        [Button.inline("📊 Report Limits", "gsetting_limits")],
        [Button.inline("✅ Approval Mode", "gsetting_approval")],
        [Button.inline("🛡️ Protection", "gsetting_protection")],
        [Button.inline("🔧 Maintenance", "gsetting_maintenance")],
        [Button.inline("« Back", "owner_menu")]
    ]
    
    await event.edit(text, buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'gsetting_approval'))
async def gsetting_approval_handler(event):
    uid = event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only", alert=True)
        return
    
    settings = db.fetchone('SELECT require_approval FROM global_settings WHERE id=1')
    current = settings['require_approval']
    
    # Toggle
    new_value = 0 if current else 1
    db.execute('UPDATE global_settings SET require_approval=? WHERE id=1', (new_value,))
    
    await event.answer(f"✅ Approval requirement: {'ENABLED' if new_value else 'DISABLED'}", alert=True)
    await owner_settings_handler(event)

# ===================== OWNER PENDING REPORTS =====================
@bot.on(events.CallbackQuery(pattern=rb'owner_pending_reports'))
async def owner_pending_reports_handler(event):
    uid = event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only", alert=True)
        return
    
    pending = db.fetchall('''SELECT pr.*, u.first_name, u.username 
                            FROM pending_reports pr 
                            JOIN users u ON pr.user_id = u.user_id 
                            WHERE pr.status='pending' 
                            ORDER BY pr.requested_date DESC LIMIT 10''')
    
    if not pending:
        await event.edit("✅ No pending report requests", buttons=[[Button.inline("« Back", "owner_menu")]])
        return
    
    text = "📋 PENDING REPORT REQUESTS:\n\n"
    buttons = []
    
    for req in pending:
        req_date = datetime.fromisoformat(req['requested_date']).strftime('%Y-%m-%d %H:%M')
        text += f"━━━━━━━━━━━━━━━━\n"
        text += f"👤 {req['first_name']} (@{req['username']})\n"
        text += f"🎯 {req['target']}\n"
        text += f"📝 {req['reason_name']}\n"
        text += f"📊 {req['reports_count']} x {req['sessions_count']}\n"
        text += f"📅 {req_date}\n\n"
        
        buttons.append([
            Button.inline(f"✅ Approve", f"preport_approve_{req['id']}"),
            Button.inline(f"❌ Reject", f"preport_reject_{req['id']}")
        ])
    
    buttons.append([Button.inline("« Back", "owner_menu")])
    
    await event.edit(text, buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'preport_(approve|reject)_(\d+)'))
async def pending_report_action_handler(event):
    uid = event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only", alert=True)
        return
    
    data_parts = event.data.decode().split('_')
    action = data_parts[1]
    report_id = int(data_parts[2])
    
    req = db.fetchone('SELECT * FROM pending_reports WHERE id=?', (report_id,))
    
    if not req:
        await event.answer("❌ Request not found", alert=True)
        return
    
    now = datetime.now().isoformat()
    
    if action == 'approve':
        # Update status
        db.execute('''UPDATE pending_reports SET status=?, approved_by=?, approved_date=?
                     WHERE id=?''', ('approved', uid, now, report_id))
        
        await event.answer("✅ Report approved! Executing...", alert=True)
        
        # Execute report
        state = {
            'target': req['target'],
            'target_type': req['target_type'],
            'message_link': req['message_link'],
            'message_id': req['message_id'],
            'reason': req['reason'],
            'reason_name': req['reason_name'],
            'reports_count': req['reports_count'],
            'sessions_count': req['sessions_count']
        }
        
        # Notify user
        try:
            await bot.send_message(req['user_id'], """✅ REPORT APPROVED

Your report request has been approved and is being executed.
You will receive a notification once completed.""")
        except:
            pass
        
        # Execute in background
        asyncio.create_task(execute_report(req['user_id'], state))
        
    else:
        # Reject
        db.execute('''UPDATE pending_reports SET status=?, approved_by=?, approved_date=?
                     WHERE id=?''', ('rejected', uid, now, report_id))
        
        await event.answer("❌ Report rejected", alert=True)
        
        # Notify user
        try:
            await bot.send_message(req['user_id'], """❌ REPORT REJECTED

Your report request has been reviewed and rejected.

If you have questions, please contact support.""")
        except:
            pass
    
    # Refresh list
    await owner_pending_reports_handler(event)

# ===================== STATISTICS =====================
@bot.on(events.CallbackQuery(pattern=rb'menu_stats'))
async def stats_menu_handler(event):
    uid = event.sender_id
    
    has_access, reason = check_user_access(uid)
    if not has_access:
        await event.answer("❌ Access denied!", alert=True)
        return
    
    # Get user statistics
    stats = db.fetchone('SELECT * FROM statistics WHERE user_id=?', (uid,)) or {}
    user = db.fetchone('SELECT * FROM users WHERE user_id=?', (uid,))
    
    total = stats.get('total_reports', 0)
    success = stats.get('successful_reports', 0)
    failed = stats.get('failed_reports', 0)
    success_rate = (success / total * 100) if total > 0 else 0
    
    text = f"""╔══════════════════════════════╗
║      📊 YOUR STATISTICS       ║
╚══════════════════════════════╝

📱 Sessions:
├ Total: {stats.get('total_sessions', 0)}
└ Active: {stats.get('active_sessions', 0)}

📊 Reports:
├ Total: {total}
├ Success: ✅ {success}
├ Failed: ❌ {failed}
└ Rate: {success_rate:.1f}%

🎯 Targets Reported: {stats.get('targets_reported', 0)}
📅 Last Report: {stats.get('last_report_date', 'Never')[:10] if stats.get('last_report_date') else 'Never'}
🔥 Account Status: {'👑 OWNER' if user['is_owner'] else '✅ APPROVED'}
"""
    
    buttons = [[Button.inline("🔄 Refresh", "menu_stats")], [Button.inline("« Back", "menu_main")]]
    
    await event.edit(text, buttons=buttons)

@bot.on(events.CallbackQuery(pattern=rb'owner_stats'))
async def owner_stats_handler(event):
    uid = event.sender_id
    if not is_owner(uid):
        await event.answer("❌ Owner only", alert=True)
        return
    
    # Get global statistics
    total_users = db.fetchone("SELECT COUNT(*) as count FROM users")['count']
    approved_users = db.fetchone("SELECT COUNT(*) as count FROM users WHERE is_approved=1")['count']
    banned_users = db.fetchone("SELECT COUNT(*) as count FROM users WHERE is_banned=1")['count']
    total_sessions = db.fetchone("SELECT COUNT(*) as count FROM sessions")['count']
    active_sessions = db.fetchone("SELECT COUNT(*) as count FROM sessions WHERE is_active=1")['count']
    total_reports = db.fetchone("SELECT COUNT(*) as count FROM reports")['count']
    success_reports = db.fetchone("SELECT COUNT(*) as count FROM reports WHERE success=1")['count']
    failed_reports = db.fetchone("SELECT COUNT(*) as count FROM reports WHERE success=0")['count']
    
    success_rate = (success_reports / total_reports * 100) if total_reports > 0 else 0
    
    text = f"""╔══════════════════════════════╗
║    📊 BOT STATISTICS (GLOBAL)  ║
╚══════════════════════════════╝

👥 Users:
├ Total: {total_users}
├ Approved: {approved_users}
└ Banned: {banned_users}

📱 Sessions:
├ Total: {total_sessions}
└ Active: {active_sessions}

📊 Reports:
├ Total: {total_reports}
├ Success: ✅ {success_reports}
├ Failed: ❌ {failed_reports}
└ Rate: {success_rate:.1f}%

🔥 Bot Performance: {'🟢 EXCELLENT' if success_rate > 90 else '🟡 GOOD' if success_rate > 70 else '🔴 NEEDS ATTENTION'}
"""
    
    buttons = [
        [Button.inline("🔄 Refresh", "owner_stats")],
        [Button.inline("📈 Detailed", "owner_stats_detailed")],
        [Button.inline("« Back", "owner_menu")]
    ]
    
    await event.edit(text, buttons=buttons)

# ===================== CANCEL COMMAND =====================
@bot.on(events.NewMessage(pattern='/cancel'))
async def cancel_handler(event):
    uid = event.sender_id
    clear_state(uid)
    await event.respond("❌ Operation cancelled", buttons=[[Button.inline("« Menu", "menu_main")]])

# ===================== MAIN FUNCTION =====================
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

if __name__ == "__main__":
    main()
