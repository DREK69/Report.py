#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import time
import re
import json
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, List, Any, Set
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import zipfile
import io
import os
import shutil
from collections import defaultdict
from telethon import TelegramClient, events, Button
from telethon.errors import FloodWaitError, SessionPasswordNeededError, ChannelPrivateError
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
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardHide
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
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', handlers=[logging.FileHandler('bot.log'), logging.StreamHandler()])
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
    1: ("Spam Messages", InputReportReasonSpam, ReportPriority.MEDIUM, "Unsolicited bulk messages or advertisements"),
    2: ("Violence / Physical Harm", InputReportReasonViolence, ReportPriority.HIGH, "Content promoting violence or physical harm"),
    3: ("Pornographic Content", InputReportReasonPornography, ReportPriority.HIGH, "Explicit sexual content or adult material"),
    4: ("Child Abuse Material", InputReportReasonChildAbuse, ReportPriority.EMERGENCY, "Content exploiting or endangering minors"),
    5: ("Copyright Violation", InputReportReasonCopyright, ReportPriority.MEDIUM, "Unauthorized use of copyrighted material"),
    6: ("Off-topic / Wrong Region", InputReportReasonGeoIrrelevant, ReportPriority.LOW, "Content not relevant to geographical context"),
    7: ("Fake Account / Impersonation", InputReportReasonFake, ReportPriority.MEDIUM, "Impersonation or fake identity"),
    8: ("Illegal Drugs / Substances", InputReportReasonIllegalDrugs, ReportPriority.HIGH, "Promotion or sale of illegal substances"),
    9: ("Personal Details (Doxxing)", InputReportReasonPersonalDetails, ReportPriority.HIGH, "Unauthorized sharing of personal information"),
    10: ("Hate Speech / Discrimination", InputReportReasonOther, ReportPriority.HIGH, "Content promoting hatred or discrimination"),
    11: ("Terrorist Content", InputReportReasonViolence, ReportPriority.EMERGENCY, "Content supporting terrorist activities"),
    12: ("Financial Scams", InputReportReasonOther, ReportPriority.HIGH, "Financial fraud or scam operations"),
    13: ("Harassment / Bullying", InputReportReasonOther, ReportPriority.HIGH, "Targeted harassment or bullying behavior"),
    14: ("Platform Manipulation", InputReportReasonSpam, ReportPriority.MEDIUM, "Artificial boosting or manipulation"),
    15: ("Other Violations", InputReportReasonOther, ReportPriority.MEDIUM, "Other terms of service violations"),
    16: ("Phishing Attempts", InputReportReasonOther, ReportPriority.CRITICAL, "Attempts to steal credentials or personal data"),
    17: ("Malware Distribution", InputReportReasonOther, ReportPriority.CRITICAL, "Distribution of malicious software"),
    18: ("Suicide Promotion", InputReportReasonViolence, ReportPriority.EMERGENCY, "Content promoting self-harm or suicide"),
    19: ("Animal Abuse", InputReportReasonViolence, ReportPriority.HIGH, "Content depicting animal cruelty"),
    20: ("Extremist Content", InputReportReasonViolence, ReportPriority.EMERGENCY, "Extremist propaganda or recruitment"),
}
REASON_DISPLAY_MAP = {
    1: "📧 Spam Messages",
    2: "⚔️ Violence / Physical Harm",
    3: "🔞 Pornographic Content",
    4: "👶 Child Abuse Material",
    5: "©️ Copyright Violation",
    6: "🌍 Off-topic / Wrong Region",
    7: "🎭 Fake Account / Impersonation",
    8: "💊 Illegal Drugs / Substances",
    9: "🔓 Personal Details (Doxxing)",
    10: "💢 Hate Speech / Discrimination",
    11: "💣 Terrorist Content",
    12: "💰 Financial Scams",
    13: "😡 Harassment / Bullying",
    14: "🤖 Platform Manipulation",
    15: "⚠️ Other Violations",
    16: "🎣 Phishing Attempts",
    17: "🦠 Malware Distribution",
    18: "☠️ Suicide Promotion",
    19: "🐾 Animal Abuse",
    20: "⚡ Extremist Content"
}
class BotConfig:
    def __init__(self):
        self.max_reports_per_user_daily = 50
        self.approval_expiry_days = 30
        self.load_config()
    def load_config(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    self.max_reports_per_user_daily = data.get('max_reports_per_user_daily', 50)
                    self.approval_expiry_days = data.get('approval_expiry_days', 30)
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
    def save_config(self):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump({'max_reports_per_user_daily': self.max_reports_per_user_daily, 'approval_expiry_days': self.approval_expiry_days}, f, indent=2)
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
        return {'user_id': self.user_id, 'role': self.role.value, 'sessions': self.sessions, 'reports_today': self.reports_today, 'total_reports': self.total_reports, 'last_report_date': self.last_report_date, 'approval_date': self.approval_date, 'approval_expiry_date': self.approval_expiry_date, 'created_at': self.created_at}
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
                logger.error(f"Failed to load users database: {e}")
    def save_users(self):
        try:
            with open(USERS_DB_FILE, 'w') as f:
                data = {str(user_id): user.to_dict() for user_id, user in self.users.items()}
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save users database: {e}")
    def get_user(self, user_id: int) -> UserData:
        if user_id not in self.users:
            if user_id in OWNER_IDS:
                user = UserData(user_id)
                user.role = UserRole.OWNER
                self.users[user_id] = user
                self.save_users()
            else:
                user = UserData(user_id)
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
        return [user for user in self.users.values() if user.role == UserRole.PENDING]
    def get_all_users_list(self) -> List[UserData]:
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
                client.session.set_dc(session_data.get('dc_id', 2), session_data.get('server_address', '149.154.167.51'), session_data.get('port', 443))
                client.session.auth_key = bytes.fromhex(session_data.get('auth_key', ''))
            await client.disconnect()
            logger.info(f"Successfully converted JSON session to {session_name}.session")
            return True
        except Exception as e:
            logger.error(f"Failed to load JSON session {json_path}: {e}")
            return False
    async def get_session_client(self, session_name: str) -> Optional[TelegramClient]:
        session_path = SESSIONS_DIR / session_name
        if not session_path.exists():
            session_path = SESSIONS_DIR / f"{session_name}.session"
            if not session_path.exists():
                logger.error(f"Session file not found: {session_name}")
                return None
        if session_name not in self.active_clients:
            try:
                base_name = session_name.replace('.session', '')
                client = TelegramClient(str(SESSIONS_DIR / base_name), API_ID, API_HASH)
                await client.connect()
                if not await client.is_user_authorized():
                    logger.error(f"Session not authorized: {session_name}")
                    await client.disconnect()
                    return None
                self.active_clients[session_name] = client
                logger.info(f"Connected to session: {session_name}")
            except Exception as e:
                logger.error(f"Failed to connect to session {session_name}: {e}")
                return None
        return self.active_clients[session_name]
    async def disconnect_all(self):
        for session_name, client in self.active_clients.items():
            try:
                await client.disconnect()
                logger.info(f"Disconnected session: {session_name}")
            except Exception as e:
                logger.error(f"Error disconnecting session {session_name}: {e}")
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
                logger.error(f"Failed to load reports log: {e}")
    def save_reports(self):
        try:
            with open(REPORTS_LOG_FILE, 'w') as f:
                json.dump(self.reports, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save reports log: {e}")
    def log_report(self, user_id: int, target: str, reason: str, sessions_used: List[str], success_count: int, failed_count: int):
        report_entry = {'timestamp': datetime.now().isoformat(), 'user_id': user_id, 'target': target, 'reason': reason, 'sessions_used': sessions_used, 'success_count': success_count, 'failed_count': failed_count, 'total_sessions': len(sessions_used)}
        self.reports.append(report_entry)
        self.save_reports()
bot_config = BotConfig()
users_db = UsersDatabase()
session_manager = SessionManager()
report_logger = ReportLogger()
user_states: Dict[int, Dict] = {}
def get_main_menu_keyboard(user_role: UserRole):
    keyboard = []
    if user_role == UserRole.OWNER:
        keyboard = [[KeyboardButton("📊 My Statistics"), KeyboardButton("🔧 Manage Sessions")], [KeyboardButton("📝 Start Reporting"), KeyboardButton("🗂 All Sessions Report")], [KeyboardButton("👥 User Management"), KeyboardButton("⚙️ Bot Settings")], [KeyboardButton("📈 View All Stats"), KeyboardButton("❌ Cancel")]]
    elif user_role == UserRole.APPROVED_USER:
        keyboard = [[KeyboardButton("📊 My Statistics"), KeyboardButton("🔧 Manage Sessions")], [KeyboardButton("📝 Start Reporting"), KeyboardButton("❌ Cancel")]]
    else:
        keyboard = [[KeyboardButton("ℹ️ Help"), KeyboardButton("❌ Cancel")]]
    return ReplyKeyboardMarkup(keyboard, resize=True)
def get_session_selection_keyboard(sessions: List[str]):
    keyboard = []
    for i in range(0, len(sessions), 2):
        row = []
        row.append(KeyboardButton(f"📱 {sessions[i][:20]}"))
        if i + 1 < len(sessions):
            row.append(KeyboardButton(f"📱 {sessions[i+1][:20]}"))
        keyboard.append(row)
    keyboard.append([KeyboardButton("✅ Select All Sessions")])
    keyboard.append([KeyboardButton("✔️ Done (Continue)"), KeyboardButton("🔙 Back to Menu")])
    return ReplyKeyboardMarkup(keyboard, resize=True)
def get_reason_keyboard():
    keyboard = []
    row = []
    for num, (reason_text) in REASON_DISPLAY_MAP.items():
        row.append(KeyboardButton(f"{num}. {reason_text[:15]}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([KeyboardButton("🔙 Back to Menu")])
    return ReplyKeyboardMarkup(keyboard, resize=True)
def get_cancel_keyboard():
    keyboard = [[KeyboardButton("❌ Cancel")]]
    return ReplyKeyboardMarkup(keyboard, resize=True)
async def is_authorized(event) -> Tuple[bool, UserRole]:
    user_id = event.sender_id
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
    patterns = [re.compile(r"https?://t\.me/(?P<user>[A-Za-z0-9_]+)(?:/(?P<msg_id>\d+))?"), re.compile(r"https?://t\.me/c/(?P<chat_id>\d+)/(?P<msg_id>\d+)"), re.compile(r"@?(?P<user>[A-Za-z0-9_]+)$")]
    for pattern in patterns:
        match = pattern.match(link.strip())
        if match:
            groups = match.groupdict()
            if 'user' in groups:
                return groups['user'], int(groups.get('msg_id', 0)) if groups.get('msg_id') else None
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
        logger.warning(f"FloodWaitError: Need to wait {e.seconds} seconds")
        await asyncio.sleep(e.seconds)
        return False
    except Exception as e:
        logger.error(f"Report error: {e}")
        return False
async def start_handler(event):
    user_id = event.sender_id
    user = users_db.get_user(user_id)
    if user.role == UserRole.OWNER:
        await event.respond("🎖️ **Welcome Owner!**\n\nYou have full access to all bot features.\nUse the menu below to navigate.", buttons=get_main_menu_keyboard(UserRole.OWNER))
    elif user.role == UserRole.APPROVED_USER:
        await event.respond("✅ **Welcome Back!**\n\nYour account is approved. You can start reporting.\nUse the menu below to navigate.", buttons=get_main_menu_keyboard(UserRole.APPROVED_USER))
    elif user.role == UserRole.PENDING:
        await event.respond(f"⏳ **Access Request Pending**\n\nYour request for access has been sent to the owner.\nPlease wait for approval.\n\n📋 Request ID: `{user_id}`", buttons=get_main_menu_keyboard(UserRole.PENDING))
        for owner_id in OWNER_IDS:
            try:
                await event.client.send_message(owner_id, f"🔔 **New Access Request**\n\nUser ID: `{user_id}`\nUsername: @{event.sender.username or 'N/A'}\nName: {event.sender.first_name or 'N/A'}\n\nUse User Management to approve or reject.")
            except Exception as e:
                logger.error(f"Failed to notify owner {owner_id}: {e}")
    else:
        await event.respond("❌ **Access Denied**\n\nYour access request was rejected or expired.\nPlease contact the bot owner.", buttons=get_main_menu_keyboard(UserRole.REJECTED))
async def message_handler(event):
    user_id = event.sender_id
    message_text = event.message.message
    is_auth, role = await is_authorized(event)
    if message_text == "❌ Cancel":
        if user_id in user_states:
            del user_states[user_id]
        await event.respond("Operation cancelled. Back to main menu.", buttons=get_main_menu_keyboard(role if is_auth else UserRole.PENDING))
        return
    if not is_auth:
        if role == UserRole.PENDING:
            await event.respond("⏳ Your access request is still pending.\nPlease wait for owner approval.")
        else:
            await event.respond("❌ You don't have access to this bot.\nPlease contact the bot owner.")
        return
    if message_text == "📊 My Statistics":
        user = users_db.get_user(user_id)
        await event.respond(f"📊 **Your Statistics**\n\nTotal Reports: {user.total_reports}\nReports Today: {user.reports_today}\nDaily Limit: {bot_config.max_reports_per_user_daily}\nSessions: {len(user.sessions)}\nRole: {user.role.value}\nMember Since: {user.created_at[:10]}", buttons=get_main_menu_keyboard(role))
        return
    elif message_text == "🔧 Manage Sessions":
        user = users_db.get_user(user_id)
        session_list = "\n".join([f"📱 {s}" for s in user.sessions]) if user.sessions else "No sessions uploaded yet"
        await event.respond(f"🔧 **Session Management**\n\nYour Sessions:\n{session_list}\n\nTo add sessions:\n1. Upload .session files directly\n2. Upload .json session files\n3. Upload a .zip file containing session files\n\nSend your session file(s) now or press Cancel.", buttons=get_cancel_keyboard())
        user_states[user_id] = {'state': 'awaiting_session_upload'}
        return
    elif message_text == "📝 Start Reporting":
        user = users_db.get_user(user_id)
        if not user.sessions:
            await event.respond("❌ You don't have any sessions uploaded.\nPlease upload sessions first using 'Manage Sessions'.", buttons=get_main_menu_keyboard(role))
            return
        if not users_db.check_daily_limit(user_id, bot_config.max_reports_per_user_daily):
            await event.respond(f"⚠️ Daily report limit reached!\n\nYou've sent {user.reports_today} reports today.\nLimit: {bot_config.max_reports_per_user_daily} per day\n\nTry again tomorrow.", buttons=get_main_menu_keyboard(role))
            return
        await event.respond("📝 **Start Reporting**\n\nSelect sessions to use for reporting:", buttons=get_session_selection_keyboard(user.sessions))
        user_states[user_id] = {'state': 'selecting_sessions', 'selected_sessions': []}
        return
    elif message_text == "🗂 All Sessions Report" and role == UserRole.OWNER:
        all_sessions = []
        for usr in users_db.get_all_users_list():
            all_sessions.extend(usr.sessions)
        all_sessions = list(set(all_sessions))
        if not all_sessions:
            await event.respond("❌ No sessions available in the system.", buttons=get_main_menu_keyboard(role))
            return
        await event.respond(f"🗂 **All Sessions Report**\n\nTotal Sessions: {len(all_sessions)}\n\nSelect sessions to use for reporting:", buttons=get_session_selection_keyboard(all_sessions))
        user_states[user_id] = {'state': 'selecting_sessions', 'selected_sessions': [], 'all_sessions_mode': True, 'available_sessions': all_sessions}
        return
    elif message_text == "👥 User Management" and role == UserRole.OWNER:
        pending_users = users_db.get_pending_users()
        all_users = users_db.get_all_users_list()
        user_stats = f"Total Users: {len(all_users)}\n"
        user_stats += f"Pending: {len(pending_users)}\n"
        user_stats += f"Approved: {sum(1 for u in all_users if u.role == UserRole.APPROVED_USER)}\n"
        user_stats += f"Owners: {sum(1 for u in all_users if u.role == UserRole.OWNER)}\n"
        if pending_users:
            pending_list = "\n".join([f"• ID: `{u.user_id}` - Since: {u.created_at[:10]}" for u in pending_users[:5]])
            await event.respond(f"👥 **User Management**\n\n{user_stats}\n**Pending Approvals:**\n{pending_list}\n\nTo approve: `/approve <user_id> <days>`\nTo reject: `/reject <user_id>`\nTo view all: `/listusers`", buttons=get_main_menu_keyboard(role))
        else:
            await event.respond(f"👥 **User Management**\n\n{user_stats}\nNo pending approvals.\n\nCommands:\n`/approve <user_id> <days>` - Approve user\n`/reject <user_id>` - Reject user\n`/listusers` - View all users", buttons=get_main_menu_keyboard(role))
        return
    elif message_text == "⚙️ Bot Settings" and role == UserRole.OWNER:
        await event.respond(f"⚙️ **Bot Settings**\n\nDaily Report Limit: {bot_config.max_reports_per_user_daily}\nApproval Expiry: {bot_config.approval_expiry_days} days\n\nTo change settings:\n`/setlimit <number>` - Set daily report limit\n`/setexpiry <days>` - Set approval expiry days", buttons=get_main_menu_keyboard(role))
        return
    elif message_text == "📈 View All Stats" and role == UserRole.OWNER:
        all_users = users_db.get_all_users_list()
        total_reports = sum(u.total_reports for u in all_users)
        stats_text = f"📈 **System Statistics**\n\nTotal Users: {len(all_users)}\nTotal Reports: {total_reports}\nTotal Sessions: {sum(len(u.sessions) for u in all_users)}\n\n**Top Reporters:**\n"
        top_users = sorted(all_users, key=lambda u: u.total_reports, reverse=True)[:5]
        for i, u in enumerate(top_users, 1):
            stats_text += f"{i}. User {u.user_id}: {u.total_reports} reports\n"
        await event.respond(stats_text, buttons=get_main_menu_keyboard(role))
        return
    elif message_text == "ℹ️ Help":
        await event.respond("ℹ️ **Help & Information**\n\nThis bot allows you to report Telegram users/channels.\n\n**Features:**\n• Multi-session support\n• Daily report limits\n• Approval system\n• Session selection\n\n**Getting Started:**\n1. Wait for owner approval\n2. Upload your session files\n3. Start reporting\n\nContact the owner for any issues.", buttons=get_main_menu_keyboard(role if is_auth else UserRole.PENDING))
        return
    elif message_text == "🔙 Back to Menu":
        if user_id in user_states:
            del user_states[user_id]
        await event.respond("Back to main menu.", buttons=get_main_menu_keyboard(role))
        return
    if user_id in user_states:
        state_data = user_states[user_id]
        current_state = state_data.get('state')
        if current_state == 'selecting_sessions':
            user = users_db.get_user(user_id)
            if state_data.get('all_sessions_mode'):
                available_sessions = state_data.get('available_sessions', [])
            else:
                available_sessions = user.sessions
            if message_text == "✅ Select All Sessions":
                state_data['selected_sessions'] = available_sessions.copy()
                await event.respond(f"✅ Selected all {len(available_sessions)} sessions.\n\nNow send the target link/username to report:", buttons=get_cancel_keyboard())
                state_data['state'] = 'awaiting_target'
                return
            elif message_text == "✔️ Done (Continue)":
                if state_data['selected_sessions']:
                    await event.respond(f"Selected {len(state_data['selected_sessions'])} sessions.\n\nNow send the target link/username to report:", buttons=get_cancel_keyboard())
                    state_data['state'] = 'awaiting_target'
                    return
                else:
                    await event.respond("❌ Please select at least one session first.")
                    return
            for session in available_sessions:
                session_short = session[:20]
                if message_text == f"📱 {session_short}" or message_text.endswith(session):
                    if session in state_data['selected_sessions']:
                        state_data['selected_sessions'].remove(session)
                        await event.respond(f"❌ Deselected: {session}\nCurrently selected: {len(state_data['selected_sessions'])} sessions")
                    else:
                        state_data['selected_sessions'].append(session)
                        await event.respond(f"✅ Selected: {session}\nCurrently selected: {len(state_data['selected_sessions'])} sessions\n\nSelect more or click 'Done' to continue.")
                    return
        elif current_state == 'awaiting_target':
            parsed = await parse_target_link(message_text)
            if not parsed:
                await event.respond("❌ Invalid target format.\n\nPlease send:\n• Username (@username or username)\n• Profile link (t.me/username)\n• Message link (t.me/username/123)")
                return
            target, msg_id = parsed
            state_data['target'] = target
            state_data['message_id'] = msg_id
            await event.respond(f"✅ Target: {target}\n{'Message ID: ' + str(msg_id) if msg_id else 'Reporting user/channel'}\n\nSelect report reason:", buttons=get_reason_keyboard())
            state_data['state'] = 'awaiting_reason'
            return
        elif current_state == 'awaiting_reason':
            reason_num = None
            for num in REASON_MAP.keys():
                if message_text.startswith(f"{num}."):
                    reason_num = num
                    break
            if reason_num is None:
                await event.respond("❌ Please select a valid reason number from the keyboard.")
                return
            reason_name, reason_class, priority, description = REASON_MAP[reason_num]
            target = state_data['target']
            message_id = state_data.get('message_id')
            selected_sessions = state_data['selected_sessions']
            await event.respond(f"🚀 **Starting Report Operation**\n\nTarget: `{target}`\nReason: {reason_name}\nPriority: {priority.value}\nSessions: {len(selected_sessions)}\n\nPlease wait...", buttons=ReplyKeyboardHide())
            success_count = 0
            failed_count = 0
            for session_name in selected_sessions:
                try:
                    client = await session_manager.get_session_client(session_name)
                    if client:
                        success = await send_report(client, target, reason_class, message_id)
                        if success:
                            success_count += 1
                        else:
                            failed_count += 1
                        await asyncio.sleep(2)
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.error(f"Error reporting with session {session_name}: {e}")
                    failed_count += 1
            report_logger.log_report(user_id, target, reason_name, selected_sessions, success_count, failed_count)
            users_db.increment_report_count(user_id)
            result_text = f"✅ **Report Complete**\n\nSuccess: {success_count}/{len(selected_sessions)}\nFailed: {failed_count}/{len(selected_sessions)}\n\nTarget: `{target}`\nReason: {reason_name}\n\n"
            user = users_db.get_user(user_id)
            result_text += f"Your stats:\nReports today: {user.reports_today}/{bot_config.max_reports_per_user_daily}\nTotal reports: {user.total_reports}"
            await event.respond(result_text, buttons=get_main_menu_keyboard(role))
            del user_states[user_id]
            return
async def document_handler(event):
    user_id = event.sender_id
    is_auth, role = await is_authorized(event)
    if not is_auth:
        await event.respond("❌ You need to be approved to upload sessions.")
        return
    if user_id not in user_states or user_states[user_id].get('state') != 'awaiting_session_upload':
        await event.respond("Please use 'Manage Sessions' from the menu first.", buttons=get_main_menu_keyboard(role))
        return
    user = users_db.get_user(user_id)
    try:
        file = await event.download_media(bytes)
        if not file:
            await event.respond("❌ Failed to download file.")
            return
        file_name = event.file.name
        if file_name.endswith('.zip'):
            await event.respond("📦 Processing zip file...")
            added_sessions = []
            try:
                with zipfile.ZipFile(io.BytesIO(file), 'r') as zip_ref:
                    for file_info in zip_ref.filelist:
                        if file_info.filename.endswith('.session'):
                            session_data = zip_ref.read(file_info.filename)
                            session_name = f"user_{user_id}_{file_info.filename}"
                            session_path = SESSIONS_DIR / session_name
                            with open(session_path, 'wb') as f:
                                f.write(session_data)
                            if session_name not in user.sessions:
                                user.sessions.append(session_name)
                                added_sessions.append(session_name)
                        elif file_info.filename.endswith('.json'):
                            session_data = zip_ref.read(file_info.filename)
                            json_filename = f"temp_{user_id}_{file_info.filename}"
                            json_path = SESSIONS_DIR / json_filename
                            with open(json_path, 'wb') as f:
                                f.write(session_data)
                            session_name = f"user_{user_id}_{file_info.filename.replace('.json', '')}"
                            success = await session_manager.load_session_from_json(json_path, session_name)
                            if success:
                                final_session_name = f"{session_name}.session"
                                if final_session_name not in user.sessions:
                                    user.sessions.append(final_session_name)
                                    added_sessions.append(final_session_name)
                            try:
                                os.remove(json_path)
                            except:
                                pass
                users_db.save_users()
                await event.respond(f"✅ Added {len(added_sessions)} sessions from zip file:\n" + "\n".join([f"📱 {s}" for s in added_sessions[:10]]), buttons=get_main_menu_keyboard(role))
            except Exception as e:
                await event.respond(f"❌ Error processing zip: {e}")
        elif file_name.endswith('.session'):
            session_name = f"user_{user_id}_{file_name}"
            session_path = SESSIONS_DIR / session_name
            with open(session_path, 'wb') as f:
                f.write(file)
            if session_name not in user.sessions:
                user.sessions.append(session_name)
                users_db.save_users()
            await event.respond(f"✅ Session added successfully!\n📱 {session_name}\n\nTotal sessions: {len(user.sessions)}", buttons=get_main_menu_keyboard(role))
        elif file_name.endswith('.json'):
            json_filename = f"temp_{user_id}_{file_name}"
            json_path = SESSIONS_DIR / json_filename
            with open(json_path, 'wb') as f:
                f.write(file)
            session_name = f"user_{user_id}_{file_name.replace('.json', '')}"
            success = await session_manager.load_session_from_json(json_path, session_name)
            if success:
                final_session_name = f"{session_name}.session"
                if final_session_name not in user.sessions:
                    user.sessions.append(final_session_name)
                    users_db.save_users()
                await event.respond(f"✅ JSON session converted and added!\n📱 {final_session_name}\n\nTotal sessions: {len(user.sessions)}", buttons=get_main_menu_keyboard(role))
            else:
                await event.respond("❌ Failed to convert JSON session.")
            try:
                os.remove(json_path)
            except:
                pass
        else:
            await event.respond("❌ Please upload .session, .json, or .zip files only.")
            return
        if user_id in user_states:
            del user_states[user_id]
    except Exception as e:
        logger.error(f"Error handling document: {e}")
        await event.respond(f"❌ Error processing file: {e}")
async def approve_command_handler(event):
    user_id = event.sender_id
    if user_id not in OWNER_IDS:
        await event.respond("❌ This command is only available to owners.")
        return
    try:
        parts = event.message.message.split()
        if len(parts) != 3:
            await event.respond("❌ Usage: `/approve <user_id> <days>`\n\nExample: `/approve 123456789 30`")
            return
        target_user_id = int(parts[1])
        days = int(parts[2])
        if days < 1 or days > 365:
            await event.respond("❌ Days must be between 1 and 365.")
            return
        users_db.approve_user(target_user_id, days)
        await event.respond(f"✅ **User Approved**\n\nUser ID: `{target_user_id}`\nApproval Duration: {days} days\nExpires: {(datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')}")
        try:
            await event.client.send_message(target_user_id, f"🎉 **Access Approved!**\n\nYour access has been approved for {days} days.\nYou can now use the bot to start reporting.\n\nUse /start to begin.", buttons=get_main_menu_keyboard(UserRole.APPROVED_USER))
        except Exception as e:
            logger.error(f"Failed to notify user {target_user_id}: {e}")
    except ValueError:
        await event.respond("❌ Invalid user ID or days value.")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")
async def reject_command_handler(event):
    user_id = event.sender_id
    if user_id not in OWNER_IDS:
        await event.respond("❌ This command is only available to owners.")
        return
    try:
        parts = event.message.message.split()
        if len(parts) != 2:
            await event.respond("❌ Usage: `/reject <user_id>`\n\nExample: `/reject 123456789`")
            return
        target_user_id = int(parts[1])
        users_db.reject_user(target_user_id)
        await event.respond(f"✅ **User Rejected**\n\nUser ID: `{target_user_id}`")
        try:
            await event.client.send_message(target_user_id, "❌ **Access Denied**\n\nYour access request has been rejected.\nPlease contact the bot owner if you believe this is an error.")
        except Exception as e:
            logger.error(f"Failed to notify user {target_user_id}: {e}")
    except ValueError:
        await event.respond("❌ Invalid user ID.")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")
async def listusers_command_handler(event):
    user_id = event.sender_id
    if user_id not in OWNER_IDS:
        await event.respond("❌ This command is only available to owners.")
        return
    all_users = users_db.get_all_users_list()
    response = "👥 **All Users**\n\n"
    for role_type in [UserRole.OWNER, UserRole.APPROVED_USER, UserRole.PENDING, UserRole.REJECTED]:
        users_in_role = [u for u in all_users if u.role == role_type]
        if users_in_role:
            response += f"**{role_type.value}** ({len(users_in_role)}):\n"
            for u in users_in_role[:10]:
                response += f"• ID: `{u.user_id}` | Reports: {u.total_reports} | Sessions: {len(u.sessions)}\n"
            if len(users_in_role) > 10:
                response += f"... and {len(users_in_role) - 10} more\n"
            response += "\n"
    await event.respond(response)
async def setlimit_command_handler(event):
    user_id = event.sender_id
    if user_id not in OWNER_IDS:
        await event.respond("❌ This command is only available to owners.")
        return
    try:
        parts = event.message.message.split()
        if len(parts) != 2:
            await event.respond("❌ Usage: `/setlimit <number>`\n\nExample: `/setlimit 100`")
            return
        new_limit = int(parts[1])
        if new_limit < 1 or new_limit > 1000:
            await event.respond("❌ Limit must be between 1 and 1000.")
            return
        bot_config.max_reports_per_user_daily = new_limit
        bot_config.save_config()
        await event.respond(f"✅ **Daily Report Limit Updated**\n\nNew Limit: {new_limit} reports per day")
    except ValueError:
        await event.respond("❌ Invalid number.")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")
async def setexpiry_command_handler(event):
    user_id = event.sender_id
    if user_id not in OWNER_IDS:
        await event.respond("❌ This command is only available to owners.")
        return
    try:
        parts = event.message.message.split()
        if len(parts) != 2:
            await event.respond("❌ Usage: `/setexpiry <days>`\n\nExample: `/setexpiry 60`")
            return
        new_expiry = int(parts[1])
        if new_expiry < 1 or new_expiry > 365:
            await event.respond("❌ Expiry must be between 1 and 365 days.")
            return
        bot_config.approval_expiry_days = new_expiry
        bot_config.save_config()
        await event.respond(f"✅ **Approval Expiry Updated**\n\nNew Expiry: {new_expiry} days")
    except ValueError:
        await event.respond("❌ Invalid number.")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")
async def main():
    logger.info("Starting Telegram Reporter Bot...")
    bot = TelegramClient('bot_session', API_ID, API_HASH)
    bot.add_event_handler(start_handler, events.NewMessage(pattern='/start'))
    bot.add_event_handler(approve_command_handler, events.NewMessage(pattern='/approve'))
    bot.add_event_handler(reject_command_handler, events.NewMessage(pattern='/reject'))
    bot.add_event_handler(listusers_command_handler, events.NewMessage(pattern='/listusers'))
    bot.add_event_handler(setlimit_command_handler, events.NewMessage(pattern='/setlimit'))
    bot.add_event_handler(setexpiry_command_handler, events.NewMessage(pattern='/setexpiry'))
    bot.add_event_handler(document_handler, events.NewMessage(func=lambda e: e.document))
    bot.add_event_handler(message_handler, events.NewMessage)
    await bot.start(bot_token=BOT_TOKEN)
    logger.info("Bot started successfully!")
    print("Bot is running... Press Ctrl+C to stop.")
    await bot.run_until_disconnected()
    await session_manager.disconnect_all()
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
