#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import logging
import re
import zipfile
import io
import os
from pathlib import Path
from typing import Optional, Tuple, Dict, List
from datetime import datetime, timedelta
from enum import Enum
from telethon import TelegramClient, events, Button
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.tl.functions.account import ReportPeerRequest
from telethon.tl.functions.messages import ReportRequest
from telethon.tl.types import (
    InputReportReasonSpam,
    InputReportReasonViolence,
    InputReportReasonPornography,
    InputReportReasonChildAbuse,
    InputReportReasonCopyright,
    InputReportReasonGeoIrrelevant,
    InputReportReasonFake,
    InputReportReasonIllegalDrugs,
    InputReportReasonPersonalDetails,
    InputReportReasonOther,
)

BOT_TOKEN = "8528337956:AAGU7PX6JooceLLL7HkH_LJ27v-QaKyrZVw"
API_ID = 25723056
API_HASH = "cbda56fac135e92b755e1243aefe9697"
OWNER_IDS = [8101867786]

USERS_DB_FILE = Path("bot_users.json")
SESSIONS_DIR = Path("user_sessions")
REPORTS_LOG_FILE = Path("reports_log.json")
CONFIG_FILE = Path("bot_config.json")

SESSIONS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('bot.log'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

class UserRole(Enum):
    OWNER = "OWNER"
    APPROVED_USER = "APPROVED_USER"
    PENDING = "PENDING"
    REJECTED = "REJECTED"

class ReportPriority(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"

REASON_MAP = {
    1: ("Spam Messages", InputReportReasonSpam, ReportPriority.MEDIUM),
    2: ("Violence / Physical Harm", InputReportReasonViolence, ReportPriority.HIGH),
    3: ("Pornographic Content", InputReportReasonPornography, ReportPriority.HIGH),
    4: ("Child Abuse Material", InputReportReasonChildAbuse, ReportPriority.EMERGENCY),
    5: ("Copyright Violation", InputReportReasonCopyright, ReportPriority.MEDIUM),
    6: ("Off-topic / Wrong Region", InputReportReasonGeoIrrelevant, ReportPriority.LOW),
    7: ("Fake Account / Impersonation", InputReportReasonFake, ReportPriority.MEDIUM),
    8: ("Illegal Drugs / Substances", InputReportReasonIllegalDrugs, ReportPriority.HIGH),
    9: ("Personal Details (Doxxing)", InputReportReasonPersonalDetails, ReportPriority.HIGH),
    10: ("Hate Speech / Discrimination", InputReportReasonOther, ReportPriority.HIGH),
    11: ("Terrorist Content", InputReportReasonViolence, ReportPriority.EMERGENCY),
    12: ("Financial Scams", InputReportReasonOther, ReportPriority.HIGH),
    13: ("Harassment / Bullying", InputReportReasonOther, ReportPriority.HIGH),
    14: ("Platform Manipulation", InputReportReasonSpam, ReportPriority.MEDIUM),
    15: ("Other Violations", InputReportReasonOther, ReportPriority.MEDIUM),
    16: ("Phishing Attempts", InputReportReasonOther, ReportPriority.CRITICAL),
    17: ("Malware Distribution", InputReportReasonOther, ReportPriority.CRITICAL),
    18: ("Suicide Promotion", InputReportReasonViolence, ReportPriority.EMERGENCY),
    19: ("Animal Abuse", InputReportReasonViolence, ReportPriority.HIGH),
    20: ("Extremist Content", InputReportReasonViolence, ReportPriority.EMERGENCY),
}

REASON_DISPLAY = {
    1: "📧 Spam", 2: "⚔️ Violence", 3: "🔞 Pornography", 4: "👶 Child Abuse",
    5: "©️ Copyright", 6: "🌍 Off-topic", 7: "🎭 Fake Account", 8: "💊 Drugs",
    9: "🔓 Doxxing", 10: "💢 Hate Speech", 11: "💣 Terrorism", 12: "💰 Scams",
    13: "😡 Harassment", 14: "🤖 Manipulation", 15: "⚠️ Other", 16: "🎣 Phishing",
    17: "🦠 Malware", 18: "☠️ Suicide", 19: "🐾 Animal Abuse", 20: "⚡ Extremism"
}

class BotConfig:
    def __init__(self):
        self.max_reports_per_user_daily = 50
        self.max_reports_per_session = 10
        self.approval_expiry_days = 30
        self.delay_between_reports = 3
        self.load_config()
    
    def load_config(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    self.max_reports_per_user_daily = data.get('max_reports_per_user_daily', 50)
                    self.max_reports_per_session = data.get('max_reports_per_session', 10)
                    self.approval_expiry_days = data.get('approval_expiry_days', 30)
                    self.delay_between_reports = data.get('delay_between_reports', 3)
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
    
    def save_config(self):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump({
                    'max_reports_per_user_daily': self.max_reports_per_user_daily,
                    'max_reports_per_session': self.max_reports_per_session,
                    'approval_expiry_days': self.approval_expiry_days,
                    'delay_between_reports': self.delay_between_reports
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

class UserData:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.role = UserRole.PENDING
        self.sessions = []
        self.reports_today = 0
        self.total_reports = 0
        self.last_report_date = None
        self.approval_date = None
        self.approval_expiry_date = None
        self.created_at = datetime.now().isoformat()
    
    def to_dict(self):
        return {
            'user_id': self.user_id,
            'role': self.role.value,
            'sessions': self.sessions,
            'reports_today': self.reports_today,
            'total_reports': self.total_reports,
            'last_report_date': self.last_report_date,
            'approval_date': self.approval_date,
            'approval_expiry_date': self.approval_expiry_date,
            'created_at': self.created_at
        }
    
    @staticmethod
    def from_dict(data: dict):
        user = UserData(data['user_id'])
        user.role = UserRole(data.get('role', 'PENDING'))
        user.sessions = data.get('sessions', [])
        user.reports_today = data.get('reports_today', 0)
        user.total_reports = data.get('total_reports', 0)
        user.last_report_date = data.get('last_report_date')
        user.approval_date = data.get('approval_date')
        user.approval_expiry_date = data.get('approval_expiry_date')
        user.created_at = data.get('created_at', datetime.now().isoformat())
        return user

class UsersDatabase:
    def __init__(self):
        self.users: Dict[int, UserData] = {}
        self.load_users()
    
    def load_users(self):
        if USERS_DB_FILE.exists():
            try:
                with open(USERS_DB_FILE, 'r') as f:
                    data = json.load(f)
                    for user_id_str, user_data in data.items():
                        user_id = int(user_id_str)
                        self.users[user_id] = UserData.from_dict(user_data)
            except Exception as e:
                logger.error(f"Failed to load users: {e}")
    
    def save_users(self):
        try:
            with open(USERS_DB_FILE, 'w') as f:
                data = {str(uid): u.to_dict() for uid, u in self.users.items()}
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save users: {e}")
    
    def get_user(self, user_id: int) -> UserData:
        if user_id not in self.users:
            user = UserData(user_id)
            if user_id in OWNER_IDS:
                user.role = UserRole.OWNER
            self.users[user_id] = user
            self.save_users()
        return self.users[user_id]
    
    def approve_user(self, user_id: int, days: int):
        user = self.get_user(user_id)
        user.role = UserRole.APPROVED_USER
        user.approval_date = datetime.now().isoformat()
        user.approval_expiry_date = (datetime.now() + timedelta(days=days)).isoformat()
        self.save_users()
    
    def reject_user(self, user_id: int):
        user = self.get_user(user_id)
        user.role = UserRole.REJECTED
        self.save_users()
    
    def check_daily_limit(self, user_id: int, max_reports: int) -> bool:
        user = self.get_user(user_id)
        today = datetime.now().date().isoformat()
        if user.last_report_date != today:
            user.reports_today = 0
            user.last_report_date = today
            self.save_users()
        return user.reports_today < max_reports
    
    def increment_report_count(self, user_id: int):
        user = self.get_user(user_id)
        today = datetime.now().date().isoformat()
        if user.last_report_date != today:
            user.reports_today = 1
            user.last_report_date = today
        else:
            user.reports_today += 1
        user.total_reports += 1
        self.save_users()
    
    def get_pending_users(self) -> List[UserData]:
        return [u for u in self.users.values() if u.role == UserRole.PENDING]
    
    def get_all_users(self) -> List[UserData]:
        return list(self.users.values())

class SessionManager:
    def __init__(self):
        self.active_clients: Dict[str, TelegramClient] = {}
    
    async def load_session_from_json(self, json_path: Path, session_name: str) -> bool:
        try:
            with open(json_path, 'r') as f:
                session_data = json.load(f)
            session_file = SESSIONS_DIR / f"{session_name}.session"
            client = TelegramClient(str(session_file.with_suffix('')), API_ID, API_HASH)
            await client.connect()
            if 'app_id' in session_data:
                client.session.set_dc(
                    session_data.get('dc_id', 2),
                    session_data.get('server_address', '149.154.167.51'),
                    session_data.get('port', 443)
                )
                client.session.auth_key = bytes.fromhex(session_data.get('auth_key', ''))
            await client.disconnect()
            logger.info(f"Converted JSON to {session_name}.session")
            return True
        except Exception as e:
            logger.error(f"Failed to load JSON session: {e}")
            return False
    
    async def get_session_client(self, session_name: str) -> Optional[TelegramClient]:
        session_path = SESSIONS_DIR / session_name
        if not session_path.exists():
            session_path = SESSIONS_DIR / f"{session_name}.session"
            if not session_path.exists():
                return None
        
        if session_name not in self.active_clients:
            try:
                base_name = session_name.replace('.session', '')
                client = TelegramClient(str(SESSIONS_DIR / base_name), API_ID, API_HASH)
                await client.connect()
                if not await client.is_user_authorized():
                    await client.disconnect()
                    return None
                self.active_clients[session_name] = client
                logger.info(f"Connected: {session_name}")
            except Exception as e:
                logger.error(f"Connection failed {session_name}: {e}")
                return None
        return self.active_clients[session_name]
    
    async def disconnect_all(self):
        for session_name, client in self.active_clients.items():
            try:
                await client.disconnect()
            except:
                pass
        self.active_clients.clear()

class ReportLogger:
    def __init__(self):
        self.reports = []
        self.load_reports()
    
    def load_reports(self):
        if REPORTS_LOG_FILE.exists():
            try:
                with open(REPORTS_LOG_FILE, 'r') as f:
                    self.reports = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load reports: {e}")
    
    def save_reports(self):
        try:
            with open(REPORTS_LOG_FILE, 'w') as f:
                json.dump(self.reports, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save reports: {e}")
    
    def log_report(self, user_id: int, target: str, reason: str, sessions: List[str], success: int, failed: int):
        entry = {
            'timestamp': datetime.now().isoformat(),
            'user_id': user_id,
            'target': target,
            'reason': reason,
            'sessions_used': sessions,
            'success_count': success,
            'failed_count': failed
        }
        self.reports.append(entry)
        self.save_reports()

bot_config = BotConfig()
users_db = UsersDatabase()
session_manager = SessionManager()
report_logger = ReportLogger()
user_states: Dict[int, Dict] = {}

def get_main_menu(role: UserRole):
    if role == UserRole.OWNER:
        return [
            [Button.inline("📊 My Stats", b"stats"), Button.inline("🔧 Sessions", b"sessions")],
            [Button.inline("📝 Report", b"report"), Button.inline("🗂 All Sessions", b"all_sessions")],
            [Button.inline("👥 Users", b"users"), Button.inline("⚙️ Settings", b"settings")],
            [Button.inline("📈 System Stats", b"system_stats")]
        ]
    elif role == UserRole.APPROVED_USER:
        return [
            [Button.inline("📊 My Stats", b"stats"), Button.inline("🔧 Sessions", b"sessions")],
            [Button.inline("📝 Start Report", b"report")]
        ]
    else:
        return [[Button.inline("ℹ️ Help", b"help")]]

def get_back_button():
    return [[Button.inline("🔙 Back", b"back")]]

def get_session_buttons(sessions: List[str], page: int = 0):
    buttons = []
    items_per_page = 8
    start = page * items_per_page
    end = start + items_per_page
    page_sessions = sessions[start:end]
    
    for i in range(0, len(page_sessions), 2):
        row = []
        session1 = page_sessions[i]
        row.append(Button.inline(f"📱 {session1[:15]}", f"sel_ses_{i+start}".encode()))
        if i + 1 < len(page_sessions):
            session2 = page_sessions[i + 1]
            row.append(Button.inline(f"📱 {session2[:15]}", f"sel_ses_{i+start+1}".encode()))
        buttons.append(row)
    
    nav_row = []
    if page > 0:
        nav_row.append(Button.inline("◀️ Prev", f"ses_page_{page-1}".encode()))
    if end < len(sessions):
        nav_row.append(Button.inline("Next ▶️", f"ses_page_{page+1}".encode()))
    if nav_row:
        buttons.append(nav_row)
    
    buttons.append([Button.inline("✅ Select All", b"select_all"), Button.inline("✔️ Done", b"done_select")])
    buttons.append([Button.inline("🔙 Back", b"back")])
    return buttons

def get_reason_buttons():
    buttons = []
    for i in range(0, 20, 2):
        row = []
        reason_num = i + 1
        row.append(Button.inline(REASON_DISPLAY[reason_num], f"reason_{reason_num}".encode()))
        if i + 1 < 20:
            reason_num2 = i + 2
            row.append(Button.inline(REASON_DISPLAY[reason_num2], f"reason_{reason_num2}".encode()))
        buttons.append(row)
    buttons.append([Button.inline("🔙 Back", b"back")])
    return buttons

def get_reports_per_session_buttons():
    buttons = []
    for i in range(1, 11, 3):
        row = []
        for j in range(3):
            if i + j <= 10:
                row.append(Button.inline(f"{i+j} Reports", f"rps_{i+j}".encode()))
        buttons.append(row)
    buttons.append([Button.inline("🔙 Back", b"back")])
    return buttons

async def is_authorized(user_id: int) -> Tuple[bool, UserRole]:
    user = users_db.get_user(user_id)
    if user.role == UserRole.OWNER:
        return True, UserRole.OWNER
    if user.role == UserRole.PENDING:
        return False, UserRole.PENDING
    if user.role == UserRole.REJECTED:
        return False, UserRole.REJECTED
    if user.approval_expiry_date:
        expiry = datetime.fromisoformat(user.approval_expiry_date)
        if datetime.now() > expiry:
            user.role = UserRole.REJECTED
            users_db.save_users()
            return False, UserRole.REJECTED
    return True, UserRole.APPROVED_USER

async def parse_target_link(link: str) -> Optional[Tuple[str, Optional[int]]]:
    patterns = [
        re.compile(r"https?://t\.me/(?P<user>[A-Za-z0-9_]+)(?:/(?P<msg_id>\d+))?"),
        re.compile(r"https?://t\.me/c/(?P<chat_id>\d+)/(?P<msg_id>\d+)"),
        re.compile(r"@?(?P<user>[A-Za-z0-9_]+)$")
    ]
    for pattern in patterns:
        match = pattern.match(link.strip())
        if match:
            groups = match.groupdict()
            if 'user' in groups:
                msg_id = int(groups['msg_id']) if groups.get('msg_id') else None
                return groups['user'], msg_id
            elif 'chat_id' in groups:
                return f"chat_{groups['chat_id']}", int(groups['msg_id'])
    return None

async def send_report(client: TelegramClient, target: str, reason_class, message_id: Optional[int] = None) -> bool:
    try:
        entity = await client.get_entity(target)
        if message_id:
            await client(ReportRequest(peer=entity, id=[message_id], reason=reason_class(), message=""))
        else:
            await client(ReportPeerRequest(peer=entity, reason=reason_class(), message=""))
        return True
    except FloodWaitError as e:
        logger.warning(f"FloodWait: {e.seconds}s")
        await asyncio.sleep(e.seconds)
        return False
    except Exception as e:
        logger.error(f"Report error: {e}")
        return False

@events.register(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user_id = event.sender_id
    user = users_db.get_user(user_id)
    
    if user.role == UserRole.OWNER:
        await event.respond(
            "🎖️ **Owner Panel**\n\nWelcome! Full access granted.\nUse buttons below to navigate.",
            buttons=get_main_menu(UserRole.OWNER)
        )
    elif user.role == UserRole.APPROVED_USER:
        await event.respond(
            "✅ **Welcome Back**\n\nYour account is approved.\nStart reporting using buttons below.",
            buttons=get_main_menu(UserRole.APPROVED_USER)
        )
    elif user.role == UserRole.PENDING:
        await event.respond(
            f"⏳ **Access Pending**\n\nRequest ID: `{user_id}`\nWaiting for owner approval.",
            buttons=get_main_menu(UserRole.PENDING)
        )
        for owner_id in OWNER_IDS:
            try:
                await event.client.send_message(
                    owner_id,
                    f"🔔 **New Request**\n\nUser ID: `{user_id}`\nUsername: @{event.sender.username or 'N/A'}\nName: {event.sender.first_name or 'N/A'}\n\nApprove: /approve {user_id} 30"
                )
            except:
                pass
    else:
        await event.respond(
            "❌ **Access Denied**\n\nYour request was rejected.\nContact bot owner.",
            buttons=get_main_menu(UserRole.REJECTED)
        )

@events.register(events.CallbackQuery())
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8') if isinstance(event.data, bytes) else event.data
    is_auth, role = await is_authorized(user_id)
    
    if data == "back":
        if user_id in user_states:
            del user_states[user_id]
        await event.edit("📋 **Main Menu**", buttons=get_main_menu(role if is_auth else UserRole.PENDING))
        return
    
    if not is_auth and data != "help":
        await event.answer("⛔ Access denied", alert=True)
        return
    
    if data == "stats":
        user = users_db.get_user(user_id)
        text = f"📊 **Your Statistics**\n\n"
        text += f"Total Reports: {user.total_reports}\n"
        text += f"Today: {user.reports_today}/{bot_config.max_reports_per_user_daily}\n"
        text += f"Sessions: {len(user.sessions)}\n"
        text += f"Role: {user.role.value}\n"
        text += f"Member Since: {user.created_at[:10]}"
        await event.edit(text, buttons=get_back_button())
    
    elif data == "sessions":
        user = users_db.get_user(user_id)
        text = f"🔧 **Session Management**\n\n"
        if user.sessions:
            text += f"Total Sessions: {len(user.sessions)}\n\n"
            for i, s in enumerate(user.sessions[:10], 1):
                text += f"{i}. {s}\n"
            if len(user.sessions) > 10:
                text += f"\n... and {len(user.sessions)-10} more"
        else:
            text += "No sessions uploaded yet."
        text += "\n\nUpload .session, .json or .zip files."
        await event.edit(text, buttons=get_back_button())
        user_states[user_id] = {'state': 'awaiting_session'}
    
    elif data == "report":
        user = users_db.get_user(user_id)
        if not user.sessions:
            await event.answer("❌ No sessions uploaded", alert=True)
            return
        if not users_db.check_daily_limit(user_id, bot_config.max_reports_per_user_daily):
            await event.answer(f"⚠️ Daily limit reached: {user.reports_today}/{bot_config.max_reports_per_user_daily}", alert=True)
            return
        user_states[user_id] = {'state': 'selecting_sessions', 'selected': [], 'page': 0}
        await event.edit("📝 **Select Sessions**\n\nChoose sessions for reporting:", buttons=get_session_buttons(user.sessions, 0))
    
    elif data == "all_sessions" and role == UserRole.OWNER:
        all_sessions = []
        for u in users_db.get_all_users():
            all_sessions.extend(u.sessions)
        all_sessions = list(set(all_sessions))
        if not all_sessions:
            await event.answer("❌ No sessions in system", alert=True)
            return
        user_states[user_id] = {'state': 'selecting_sessions', 'selected': [], 'page': 0, 'all_mode': True, 'available': all_sessions}
        await event.edit(f"🗂 **All Sessions** ({len(all_sessions)})\n\nSelect sessions:", buttons=get_session_buttons(all_sessions, 0))
    
    elif data == "users" and role == UserRole.OWNER:
        pending = users_db.get_pending_users()
        all_users = users_db.get_all_users()
        text = f"👥 **User Management**\n\n"
        text += f"Total: {len(all_users)}\n"
        text += f"Pending: {len(pending)}\n"
        text += f"Approved: {sum(1 for u in all_users if u.role == UserRole.APPROVED_USER)}\n"
        text += f"Owners: {sum(1 for u in all_users if u.role == UserRole.OWNER)}\n\n"
        if pending:
            text += "**Pending Approvals:**\n"
            for u in pending[:5]:
                text += f"• `{u.user_id}` - {u.created_at[:10]}\n"
        text += "\n/approve <id> <days>\n/reject <id>\n/listusers"
        await event.edit(text, buttons=get_back_button())
    
    elif data == "settings" and role == UserRole.OWNER:
        text = f"⚙️ **Bot Settings**\n\n"
        text += f"Daily Limit: {bot_config.max_reports_per_user_daily}\n"
        text += f"Per Session: {bot_config.max_reports_per_session}\n"
        text += f"Approval Days: {bot_config.approval_expiry_days}\n"
        text += f"Delay: {bot_config.delay_between_reports}s\n\n"
        text += "/setlimit <num>\n/setpersession <num>\n/setexpiry <days>\n/setdelay <seconds>"
        await event.edit(text, buttons=get_back_button())
    
    elif data == "system_stats" and role == UserRole.OWNER:
        all_users = users_db.get_all_users()
        total_reports = sum(u.total_reports for u in all_users)
        text = f"📈 **System Statistics**\n\n"
        text += f"Users: {len(all_users)}\n"
        text += f"Reports: {total_reports}\n"
        text += f"Sessions: {sum(len(u.sessions) for u in all_users)}\n\n"
        top = sorted(all_users, key=lambda u: u.total_reports, reverse=True)[:5]
        text += "**Top Reporters:**\n"
        for i, u in enumerate(top, 1):
            text += f"{i}. User {u.user_id}: {u.total_reports}\n"
        await event.edit(text, buttons=get_back_button())
    
    elif data == "help":
        text = "ℹ️ **Help**\n\n"
        text += "This bot reports Telegram users/channels.\n\n"
        text += "**Features:**\n"
        text += "• Multi-session support\n"
        text += "• Daily limits\n"
        text += "• Owner approval\n"
        text += "• Flood wait handling\n\n"
        text += "Upload sessions and start reporting."
        await event.edit(text, buttons=get_back_button())
    
    elif data.startswith("ses_page_"):
        page = int(data.split("_")[-1])
        state = user_states.get(user_id, {})
        user = users_db.get_user(user_id)
        sessions = state.get('available', user.sessions)
        state['page'] = page
        await event.edit("📝 **Select Sessions**", buttons=get_session_buttons(sessions, page))
    
    elif data.startswith("sel_ses_"):
        idx = int(data.split("_")[-1])
        state = user_states.get(user_id, {})
        if state.get('state') != 'selecting_sessions':
            return
        user = users_db.get_user(user_id)
        sessions = state.get('available', user.sessions)
        page = state.get('page', 0)
        
        if idx < len(sessions):
            session = sessions[idx]
            if session in state['selected']:
                state['selected'].remove(session)
                await event.answer(f"❌ Deselected: {session[:20]}")
            else:
                state['selected'].append(session)
                await event.answer(f"✅ Selected: {session[:20]}")
            await event.edit(f"📝 **Select Sessions** ({len(state['selected'])} selected)", buttons=get_session_buttons(sessions, page))
    
    elif data == "select_all":
        state = user_states.get(user_id, {})
        if state.get('state') != 'selecting_sessions':
            return
        user = users_db.get_user(user_id)
        sessions = state.get('available', user.sessions)
        state['selected'] = sessions.copy()
        page = state.get('page', 0)
        await event.answer(f"✅ Selected all {len(sessions)} sessions")
        await event.edit(f"📝 **Select Sessions** ({len(state['selected'])} selected)", buttons=get_session_buttons(sessions, page))
    
    elif data == "done_select":
        state = user_states.get(user_id, {})
        if not state.get('selected'):
            await event.answer("❌ Select at least 1 session", alert=True)
            return
        state['state'] = 'awaiting_target'
        await event.edit(f"✅ **{len(state['selected'])} Sessions Selected**\n\nNow send target link/username:", buttons=get_back_button())
    
    elif data.startswith("reason_"):
        reason_num = int(data.split("_")[1])
        state = user_states.get(user_id, {})
        if state.get('state') != 'awaiting_reason':
            return
        state['reason'] = reason_num
        state['state'] = 'selecting_reports_per_session'
        await event.edit(f"✅ **Reason:** {REASON_DISPLAY[reason_num]}\n\nSelect reports per session:", buttons=get_reports_per_session_buttons())
    
    elif data.startswith("rps_"):
        reports_per_session = int(data.split("_")[1])
        state = user_states.get(user_id, {})
        if state.get('state') != 'selecting_reports_per_session':
            return
        
        reason_num = state['reason']
        reason_name, reason_class, priority = REASON_MAP[reason_num]
        target = state['target']
        message_id = state.get('message_id')
        selected_sessions = state['selected']
        
        await event.edit(
            f"🚀 **Starting Reports**\n\n"
            f"Target: `{target}`\n"
            f"Reason: {reason_name}\n"
            f"Sessions: {len(selected_sessions)}\n"
            f"Per Session: {reports_per_session}\n\n"
            f"Processing..."
        )
        
        success_count = 0
        failed_count = 0
        
        for session_name in selected_sessions:
            try:
                client = await session_manager.get_session_client(session_name)
                if client:
                    for _ in range(reports_per_session):
                        success = await send_report(client, target, reason_class, message_id)
                        if success:
                            success_count += 1
                        else:
                            failed_count += 1
                        await asyncio.sleep(bot_config.delay_between_reports)
                else:
                    failed_count += reports_per_session
            except Exception as e:
                logger.error(f"Error with {session_name}: {e}")
                failed_count += reports_per_session
        
        users_db.increment_report_count(user_id)
        report_logger.log_report(user_id, target, reason_name, selected_sessions, success_count, failed_count)
        
        total_attempted = len(selected_sessions) * reports_per_session
        user = users_db.get_user(user_id)
        
        result_text = f"✅ **Report Complete**\n\n"
        result_text += f"Target: `{target}`\n"
        result_text += f"Reason: {reason_name}\n"
        result_text += f"Success: {success_count}/{total_attempted}\n"
        result_text += f"Failed: {failed_count}/{total_attempted}\n"
        result_text += f"\nYour Total: {user.total_reports}"
        
        await event.edit(result_text, buttons=get_main_menu(role))
        
        if user_id in user_states:
            del user_states[user_id]

@events.register(events.NewMessage(func=lambda e: e.document))
async def document_handler(event):
    user_id = event.sender_id
    is_auth, role = await is_authorized(user_id)
    
    if not is_auth:
        await event.respond("❌ Access denied")
        return
    
    state = user_states.get(user_id, {})
    if state.get('state') != 'awaiting_session':
        return
    
    try:
        user = users_db.get_user(user_id)
        file = await event.download_media(bytes)
        file_name = event.file.name
        
        if file_name.endswith('.zip'):
            zip_buffer = io.BytesIO(file)
            with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
                session_files = [f for f in zip_ref.namelist() if f.endswith('.session')]
                added = 0
                for sf in session_files:
                    data = zip_ref.read(sf)
                    path = SESSIONS_DIR / sf
                    with open(path, 'wb') as f:
                        f.write(data)
                    if sf not in user.sessions:
                        user.sessions.append(sf)
                        added += 1
                users_db.save_users()
            await event.respond(
                f"✅ **ZIP Processed**\n\nAdded: {added} sessions\nTotal: {len(user.sessions)}",
                buttons=get_main_menu(role)
            )
        
        elif file_name.endswith('.session'):
            path = SESSIONS_DIR / file_name
            with open(path, 'wb') as f:
                f.write(file)
            if file_name not in user.sessions:
                user.sessions.append(file_name)
                users_db.save_users()
            await event.respond(
                f"✅ **Session Added**\n\n📱 {file_name}\nTotal: {len(user.sessions)}",
                buttons=get_main_menu(role)
            )
        
        elif file_name.endswith('.json'):
            json_path = SESSIONS_DIR / f"temp_{user_id}_{file_name}"
            with open(json_path, 'wb') as f:
                f.write(file)
            session_name = f"user_{user_id}_{file_name.replace('.json', '')}"
            success = await session_manager.load_session_from_json(json_path, session_name)
            if success:
                final_name = f"{session_name}.session"
                if final_name not in user.sessions:
                    user.sessions.append(final_name)
                    users_db.save_users()
                await event.respond(
                    f"✅ **JSON Converted**\n\n📱 {final_name}\nTotal: {len(user.sessions)}",
                    buttons=get_main_menu(role)
                )
            else:
                await event.respond("❌ JSON conversion failed")
            try:
                os.remove(json_path)
            except:
                pass
        else:
            await event.respond("❌ Upload .session, .json or .zip only")
            return
        
        if user_id in user_states:
            del user_states[user_id]
    
    except Exception as e:
        logger.error(f"Document error: {e}")
        await event.respond(f"❌ Error: {e}")

@events.register(events.NewMessage(func=lambda e: not e.document and not e.message.message.startswith('/')))
async def message_handler(event):
    user_id = event.sender_id
    text = event.message.message
    is_auth, role = await is_authorized(user_id)
    
    if not is_auth:
        return
    
    state = user_states.get(user_id, {})
    
    if state.get('state') == 'awaiting_target':
        parsed = await parse_target_link(text)
        if not parsed:
            await event.respond(
                "❌ **Invalid Format**\n\n"
                "Send:\n"
                "• Username (@user or user)\n"
                "• Link (t.me/user)\n"
                "• Message (t.me/user/123)",
                buttons=get_back_button()
            )
            return
        
        target, msg_id = parsed
        state['target'] = target
        state['message_id'] = msg_id
        state['state'] = 'awaiting_reason'
        
        msg_info = f"Message ID: {msg_id}" if msg_id else "Reporting user/channel"
        await event.respond(
            f"✅ **Target Set**\n\nTarget: `{target}`\n{msg_info}\n\nSelect reason:",
            buttons=get_reason_buttons()
        )

@events.register(events.NewMessage(pattern='/approve'))
async def approve_handler(event):
    if event.sender_id not in OWNER_IDS:
        await event.respond("❌ Owner only")
        return
    
    try:
        parts = event.message.message.split()
        if len(parts) != 3:
            await event.respond("Usage: /approve <user_id> <days>")
            return
        
        target_id = int(parts[1])
        days = int(parts[2])
        
        if days < 1 or days > 365:
            await event.respond("❌ Days: 1-365")
            return
        
        users_db.approve_user(target_id, days)
        expiry = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
        
        await event.respond(f"✅ **Approved**\n\nUser: `{target_id}`\nDays: {days}\nExpires: {expiry}")
        
        try:
            await event.client.send_message(
                target_id,
                f"🎉 **Approved!**\n\nDuration: {days} days\n\nUse /start",
                buttons=get_main_menu(UserRole.APPROVED_USER)
            )
        except:
            pass
    
    except ValueError:
        await event.respond("❌ Invalid values")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")

@events.register(events.NewMessage(pattern='/reject'))
async def reject_handler(event):
    if event.sender_id not in OWNER_IDS:
        await event.respond("❌ Owner only")
        return
    
    try:
        parts = event.message.message.split()
        if len(parts) != 2:
            await event.respond("Usage: /reject <user_id>")
            return
        
        target_id = int(parts[1])
        users_db.reject_user(target_id)
        
        await event.respond(f"✅ **Rejected**\n\nUser: `{target_id}`")
        
        try:
            await event.client.send_message(target_id, "❌ **Access Denied**")
        except:
            pass
    
    except ValueError:
        await event.respond("❌ Invalid user ID")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")

@events.register(events.NewMessage(pattern='/listusers'))
async def listusers_handler(event):
    if event.sender_id not in OWNER_IDS:
        await event.respond("❌ Owner only")
        return
    
    all_users = users_db.get_all_users()
    response = "👥 **All Users**\n\n"
    
    for role_type in [UserRole.OWNER, UserRole.APPROVED_USER, UserRole.PENDING, UserRole.REJECTED]:
        role_users = [u for u in all_users if u.role == role_type]
        if role_users:
            response += f"**{role_type.value}** ({len(role_users)}):\n"
            for u in role_users[:10]:
                response += f"• `{u.user_id}` | R:{u.total_reports} | S:{len(u.sessions)}\n"
            if len(role_users) > 10:
                response += f"... +{len(role_users)-10} more\n"
            response += "\n"
    
    await event.respond(response)

@events.register(events.NewMessage(pattern='/setlimit'))
async def setlimit_handler(event):
    if event.sender_id not in OWNER_IDS:
        await event.respond("❌ Owner only")
        return
    
    try:
        parts = event.message.message.split()
        if len(parts) != 2:
            await event.respond("Usage: /setlimit <number>")
            return
        
        limit = int(parts[1])
        if limit < 1 or limit > 1000:
            await event.respond("❌ Limit: 1-1000")
            return
        
        bot_config.max_reports_per_user_daily = limit
        bot_config.save_config()
        await event.respond(f"✅ **Daily Limit**\n\nNew: {limit}")
    
    except ValueError:
        await event.respond("❌ Invalid number")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")

@events.register(events.NewMessage(pattern='/setpersession'))
async def setpersession_handler(event):
    if event.sender_id not in OWNER_IDS:
        await event.respond("❌ Owner only")
        return
    
    try:
        parts = event.message.message.split()
        if len(parts) != 2:
            await event.respond("Usage: /setpersession <number>")
            return
        
        limit = int(parts[1])
        if limit < 1 or limit > 50:
            await event.respond("❌ Limit: 1-50")
            return
        
        bot_config.max_reports_per_session = limit
        bot_config.save_config()
        await event.respond(f"✅ **Per Session Limit**\n\nNew: {limit}")
    
    except ValueError:
        await event.respond("❌ Invalid number")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")

@events.register(events.NewMessage(pattern='/setexpiry'))
async def setexpiry_handler(event):
    if event.sender_id not in OWNER_IDS:
        await event.respond("❌ Owner only")
        return
    
    try:
        parts = event.message.message.split()
        if len(parts) != 2:
            await event.respond("Usage: /setexpiry <days>")
            return
        
        days = int(parts[1])
        if days < 1 or days > 365:
            await event.respond("❌ Days: 1-365")
            return
        
        bot_config.approval_expiry_days = days
        bot_config.save_config()
        await event.respond(f"✅ **Approval Expiry**\n\nNew: {days} days")
    
    except ValueError:
        await event.respond("❌ Invalid number")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")

@events.register(events.NewMessage(pattern='/setdelay'))
async def setdelay_handler(event):
    if event.sender_id not in OWNER_IDS:
        await event.respond("❌ Owner only")
        return
    
    try:
        parts = event.message.message.split()
        if len(parts) != 2:
            await event.respond("Usage: /setdelay <seconds>")
            return
        
        delay = int(parts[1])
        if delay < 1 or delay > 60:
            await event.respond("❌ Delay: 1-60s")
            return
        
        bot_config.delay_between_reports = delay
        bot_config.save_config()
        await event.respond(f"✅ **Report Delay**\n\nNew: {delay}s")
    
    except ValueError:
        await event.respond("❌ Invalid number")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")

async def main():
    logger.info("Starting bot...")
    bot = TelegramClient('bot_session', API_ID, API_HASH)
    
    bot.add_event_handler(start_handler)
    bot.add_event_handler(callback_handler)
    bot.add_event_handler(document_handler)
    bot.add_event_handler(message_handler)
    bot.add_event_handler(approve_handler)
    bot.add_event_handler(reject_handler)
    bot.add_event_handler(listusers_handler)
    bot.add_event_handler(setlimit_handler)
    bot.add_event_handler(setpersession_handler)
    bot.add_event_handler(setexpiry_handler)
    bot.add_event_handler(setdelay_handler)
    
    await bot.start(bot_token=BOT_TOKEN)
    logger.info("Bot started!")
    print("Bot running... Press Ctrl+C to stop")
    
    await bot.run_until_disconnected()
    await session_manager.disconnect_all()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
