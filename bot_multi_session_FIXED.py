#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass, asdict, field
import random
import hashlib
import time
import csv

from telethon import TelegramClient, events, Button
from telethon.errors import (
    FloodWaitError,
    SessionPasswordNeededError,
    ChannelPrivateError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    UserPrivacyRestrictedError,
    ChatWriteForbiddenError,
    PeerIdInvalidError,
)
from telethon.tl.functions.account import ReportPeerRequest, UpdateStatusRequest
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
    User,
    Channel,
    Chat,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_reporter.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

SESSIONS_DIR = Path("sessions")
DATA_DIR = Path("data")
BACKUP_DIR = Path("backups")
EXPORT_DIR = Path("exports")
UPLOAD_DIR = Path("uploads")
SESSIONS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
BACKUP_DIR.mkdir(exist_ok=True)
EXPORT_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

SESSION_CONFIG_FILE = DATA_DIR / "session_configs.json"
REPORT_QUEUE_FILE = DATA_DIR / "report_queue.json"
REPORT_HISTORY_FILE = DATA_DIR / "report_history.json"
USER_STATES_FILE = DATA_DIR / "user_states.json"
ADMIN_CONFIG_FILE = DATA_DIR / "admin_config.json"
STATISTICS_FILE = DATA_DIR / "statistics.json"
TARGET_LIMITS_FILE = DATA_DIR / "target_limits.json"
SCHEDULE_FILE = DATA_DIR / "scheduled_tasks.json"
BLACKLIST_FILE = DATA_DIR / "blacklist.json"
WHITELIST_FILE = DATA_DIR / "whitelist.json"

BOT_API_ID = 25723056
BOT_API_HASH = "cbda56fac135e92b755e1243aefe9697"
BOT_TOKEN = "8528337956:AAGU7PX6JooceLLL7HkH_LJ27v-QaKyrZVw"

# ⚠️ CRITICAL: Replace with YOUR Telegram User ID (not bot ID!)
# Get it from @userinfobot on Telegram
ADMIN_USER_IDS = [123456789]  # 👈 REPLACE THIS!

REASON_MAP = {
    1: ("Spam Messages", InputReportReasonSpam, "Unsolicited bulk messages or advertisements"),
    2: ("Violence / Physical Harm", InputReportReasonViolence, "Content promoting violence or physical harm"),
    3: ("Pornographic Content", InputReportReasonPornography, "Explicit sexual content or adult material"),
    4: ("Child Abuse Material", InputReportReasonChildAbuse, "Content exploiting or endangering minors"),
    5: ("Copyright Violation", InputReportReasonCopyright, "Unauthorized use of copyrighted material"),
    6: ("Off-topic / Wrong Region", InputReportReasonGeoIrrelevant, "Content not relevant to geographical context"),
    7: ("Fake Account / Impersonation", InputReportReasonFake, "Impersonation or fake identity"),
    8: ("Illegal Drugs / Substances", InputReportReasonIllegalDrugs, "Promotion or sale of illegal substances"),
    9: ("Personal Details (Doxxing)", InputReportReasonPersonalDetails, "Unauthorized sharing of personal information"),
    10: ("Hate Speech / Discrimination", InputReportReasonOther, "Content promoting hatred or discrimination"),
    11: ("Terrorist Content", InputReportReasonViolence, "Content supporting terrorist activities"),
    12: ("Scam / Fraud", InputReportReasonSpam, "Fraudulent schemes or scam operations"),
    13: ("Harassment / Bullying", InputReportReasonOther, "Targeted harassment or bullying behavior"),
    14: ("Animal Abuse", InputReportReasonViolence, "Content showing animal cruelty"),
    15: ("Self-Harm Content", InputReportReasonOther, "Content promoting self-harm or suicide"),
    16: ("Misinformation", InputReportReasonFake, "Deliberately false or misleading information"),
    17: ("Privacy Violation", InputReportReasonPersonalDetails, "Unauthorized sharing of private information"),
    18: ("Underage User", InputReportReasonChildAbuse, "User below minimum age requirement"),
    19: ("Counterfeit Goods", InputReportReasonCopyright, "Sale of counterfeit or fake products"),
    20: ("Other Violation", InputReportReasonOther, "Other terms of service violations"),
}

@dataclass
class SessionConfig:
    session_id: str
    api_id: int
    api_hash: str
    phone: str
    status: str = "idle"
    reports_sent: int = 0
    reports_failed: int = 0
    last_used: Optional[str] = None
    flood_wait_until: Optional[str] = None
    daily_limit: int = 100
    hourly_limit: int = 20
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    notes: str = ""
    is_authorized: bool = False
    total_flood_waits: int = 0
    success_rate: float = 0.0

@dataclass
class ReportTask:
    task_id: str
    user_id: int
    target: str
    reason_id: int
    count: int
    session_id: Optional[str]
    created_at: str
    status: str = "pending"
    completed: int = 0
    failed: int = 0
    priority: int = 1
    notes: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3

@dataclass
class UserState:
    user_id: int
    current_action: Optional[str] = None
    temp_data: Dict = field(default_factory=dict)
    last_activity: str = field(default_factory=lambda: datetime.now().isoformat())
    is_admin: bool = False
    reports_today: int = 0
    tasks_created: int = 0
    last_report_date: Optional[str] = None

@dataclass
class TargetLimit:
    target: str
    max_reports: int
    current_reports: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_reported: Optional[str] = None
    created_by: Optional[int] = None
    reason: str = ""

@dataclass
class Statistics:
    total_reports: int = 0
    successful_reports: int = 0
    failed_reports: int = 0
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    active_sessions: int = 0
    total_users: int = 0
    reports_by_reason: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    reports_by_session: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    reports_by_user: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    flood_waits: int = 0
    total_flood_wait_time: int = 0
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    reports_by_hour: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    reports_by_day: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

@dataclass
class ScheduledTask:
    schedule_id: str
    task_id: Optional[str]
    user_id: int
    target: str
    reason_id: int
    count: int
    session_id: Optional[str]
    scheduled_time: str
    created_at: str
    status: str = "pending"
    executed_at: Optional[str] = None
    repeat: bool = False
    repeat_interval: Optional[int] = None

@dataclass
class ReportHistory:
    history_id: str
    task_id: str
    user_id: int
    target: str
    reason_id: int
    count: int
    successful: int
    failed: int
    session_id: str
    timestamp: str
    duration: float
    notes: str = ""

class FileManager:
    @staticmethod
    def save_json(file_path: Path, data: Any):
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved data to {file_path}")
        except Exception as e:
            logger.error(f"Error saving to {file_path}: {e}")

    @staticmethod
    def load_json(file_path: Path, default: Any = None) -> Any:
        try:
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return default if default is not None else {}
        except Exception as e:
            logger.error(f"Error loading from {file_path}: {e}")
            return default if default is not None else {}

    @staticmethod
    def backup_file(file_path: Path):
        if file_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = BACKUP_DIR / f"{file_path.stem}_{timestamp}.json"
            try:
                import shutil
                shutil.copy2(file_path, backup_path)
                logger.info(f"Backup created: {backup_path}")
            except Exception as e:
                logger.error(f"Backup failed: {e}")

    @staticmethod
    def export_to_csv(data: List[Dict], filename: str):
        export_path = EXPORT_DIR / filename
        try:
            if data:
                keys = data[0].keys()
                with open(export_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=keys)
                    writer.writeheader()
                    writer.writerows(data)
                logger.info(f"Exported to CSV: {export_path}")
                return str(export_path)
        except Exception as e:
            logger.error(f"CSV export failed: {e}")
        return None

class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, SessionConfig] = {}
        self.active_clients: Dict[str, TelegramClient] = {}
        self.load_sessions()

    def load_sessions(self):
        data = FileManager.load_json(SESSION_CONFIG_FILE, {})
        self.sessions = {k: SessionConfig(**v) for k, v in data.items()}
        logger.info(f"Loaded {len(self.sessions)} sessions")

    def save_sessions(self):
        FileManager.save_json(SESSION_CONFIG_FILE, {k: asdict(v) for k, v in self.sessions.items()})

    def add_session(self, session_id: str, api_id: int, api_hash: str, phone: str, notes: str = ""):
        self.sessions[session_id] = SessionConfig(
            session_id=session_id,
            api_id=api_id,
            api_hash=api_hash,
            phone=phone,
            notes=notes
        )
        self.save_sessions()
        logger.info(f"Added session: {session_id}")

    def remove_session(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]
            if session_id in self.active_clients:
                asyncio.create_task(self.disconnect_session(session_id))
            self.save_sessions()
            session_file = SESSIONS_DIR / f"{session_id}.session"
            if session_file.exists():
                session_file.unlink()
            logger.info(f"Removed session: {session_id}")
            return True
        return False

    async def disconnect_session(self, session_id: str):
        if session_id in self.active_clients:
            try:
                await self.active_clients[session_id].disconnect()
                del self.active_clients[session_id]
                logger.info(f"Disconnected session: {session_id}")
            except Exception as e:
                logger.error(f"Error disconnecting session {session_id}: {e}")

    async def get_client(self, session_id: str) -> Optional[TelegramClient]:
        if session_id not in self.sessions:
            logger.warning(f"Session {session_id} not found")
            return None
        
        if session_id in self.active_clients:
            client = self.active_clients[session_id]
            if client.is_connected():
                return client
        
        session_cfg = self.sessions[session_id]
        client = TelegramClient(
            str(SESSIONS_DIR / session_id),
            session_cfg.api_id,
            session_cfg.api_hash
        )
        
        try:
            await client.connect()
            if not await client.is_user_authorized():
                logger.warning(f"Session {session_id} not authorized")
                session_cfg.is_authorized = False
                self.save_sessions()
                return None
            
            session_cfg.is_authorized = True
            self.save_sessions()
            self.active_clients[session_id] = client
            logger.info(f"Connected session: {session_id}")
            return client
        except Exception as e:
            logger.error(f"Error connecting session {session_id}: {e}")
            return None

    def get_available_session(self, exclude_sessions: List[str] = None) -> Optional[str]:
        now = datetime.now()
        available_sessions = []
        
        for sid, cfg in self.sessions.items():
            if exclude_sessions and sid in exclude_sessions:
                continue
                
            if cfg.status == "disabled" or not cfg.is_authorized:
                continue
                
            if cfg.flood_wait_until:
                try:
                    wait_until = datetime.fromisoformat(cfg.flood_wait_until)
                    if now < wait_until:
                        continue
                    else:
                        cfg.flood_wait_until = None
                        cfg.status = "idle"
                except:
                    cfg.flood_wait_until = None
            
            if cfg.status in ["idle", "active"]:
                available_sessions.append((sid, cfg.reports_sent))
        
        if not available_sessions:
            return None
        
        available_sessions.sort(key=lambda x: x[1])
        return available_sessions[0][0]

    def update_session_status(self, session_id: str, status: str):
        if session_id in self.sessions:
            self.sessions[session_id].status = status
            self.sessions[session_id].last_used = datetime.now().isoformat()
            self.save_sessions()

    def set_flood_wait(self, session_id: str, seconds: int):
        if session_id in self.sessions:
            wait_until = datetime.now() + timedelta(seconds=seconds)
            self.sessions[session_id].flood_wait_until = wait_until.isoformat()
            self.sessions[session_id].status = "flood_wait"
            self.sessions[session_id].total_flood_waits += 1
            self.save_sessions()
            logger.warning(f"Session {session_id} in flood wait for {seconds}s")

    def increment_reports(self, session_id: str, success: bool = True):
        if session_id in self.sessions:
            if success:
                self.sessions[session_id].reports_sent += 1
            else:
                self.sessions[session_id].reports_failed += 1
            
            total = self.sessions[session_id].reports_sent + self.sessions[session_id].reports_failed
            if total > 0:
                self.sessions[session_id].success_rate = (self.sessions[session_id].reports_sent / total) * 100
            
            self.save_sessions()

    def get_session_info(self, session_id: str) -> Optional[SessionConfig]:
        return self.sessions.get(session_id)

    def list_sessions(self) -> List[SessionConfig]:
        return list(self.sessions.values())

    def get_session_stats(self) -> Dict[str, Any]:
        total = len(self.sessions)
        active = len([s for s in self.sessions.values() if s.status == "active"])
        idle = len([s for s in self.sessions.values() if s.status == "idle"])
        flood_wait = len([s for s in self.sessions.values() if s.status == "flood_wait"])
        disabled = len([s for s in self.sessions.values() if s.status == "disabled"])
        
        return {
            "total": total,
            "active": active,
            "idle": idle,
            "flood_wait": flood_wait,
            "disabled": disabled
        }

class ReportQueue:
    def __init__(self):
        self.tasks: Dict[str, ReportTask] = {}
        self.load_queue()

    def load_queue(self):
        data = FileManager.load_json(REPORT_QUEUE_FILE, {})
        self.tasks = {k: ReportTask(**v) for k, v in data.items()}
        logger.info(f"Loaded {len(self.tasks)} tasks")

    def save_queue(self):
        FileManager.save_json(REPORT_QUEUE_FILE, {k: asdict(v) for k, v in self.tasks.items()})

    def add_task(self, user_id: int, target: str, reason_id: int, count: int, 
                 session_id: Optional[str] = None, priority: int = 1, notes: str = "") -> str:
        task_id = f"task_{int(datetime.now().timestamp() * 1000)}_{random.randint(1000, 9999)}"
        task = ReportTask(
            task_id=task_id,
            user_id=user_id,
            target=target,
            reason_id=reason_id,
            count=count,
            session_id=session_id,
            created_at=datetime.now().isoformat(),
            priority=priority,
            notes=notes
        )
        self.tasks[task_id] = task
        self.save_queue()
        logger.info(f"Added task {task_id}: {target} x{count}")
        return task_id

    def get_pending_tasks(self) -> List[ReportTask]:
        tasks = [t for t in self.tasks.values() if t.status == "pending"]
        tasks.sort(key=lambda x: (x.priority, x.created_at), reverse=True)
        return tasks

    def get_task(self, task_id: str) -> Optional[ReportTask]:
        return self.tasks.get(task_id)

    def update_task(self, task_id: str, **kwargs):
        if task_id in self.tasks:
            for k, v in kwargs.items():
                if hasattr(self.tasks[task_id], k):
                    setattr(self.tasks[task_id], k, v)
            self.save_queue()

    def delete_task(self, task_id: str):
        if task_id in self.tasks:
            del self.tasks[task_id]
            self.save_queue()
            return True
        return False

    def get_user_tasks(self, user_id: int) -> List[ReportTask]:
        return [t for t in self.tasks.values() if t.user_id == user_id]

    def get_active_tasks(self) -> List[ReportTask]:
        return [t for t in self.tasks.values() if t.status == "processing"]

    def cleanup_old_tasks(self, days: int = 7):
        cutoff = datetime.now() - timedelta(days=days)
        to_remove = []
        for task_id, task in self.tasks.items():
            if task.status in ["completed", "failed"]:
                task_time = datetime.fromisoformat(task.created_at)
                if task_time < cutoff:
                    to_remove.append(task_id)
        
        for task_id in to_remove:
            del self.tasks[task_id]
        
        if to_remove:
            self.save_queue()
            logger.info(f"Cleaned up {len(to_remove)} old tasks")

class UserStateManager:
    def __init__(self):
        self.states: Dict[int, UserState] = {}
        self.load_states()

    def load_states(self):
        data = FileManager.load_json(USER_STATES_FILE, {})
        self.states = {int(k): UserState(**v) for k, v in data.items()}

    def save_states(self):
        FileManager.save_json(USER_STATES_FILE, {k: asdict(v) for k, v in self.states.items()})

    def get_state(self, user_id: int) -> UserState:
        if user_id not in self.states:
            self.states[user_id] = UserState(
                user_id=user_id,
                is_admin=user_id in ADMIN_USER_IDS
            )
            self.save_states()
        return self.states[user_id]

    def set_action(self, user_id: int, action: str, temp_data: Dict = None):
        state = self.get_state(user_id)
        state.current_action = action
        if temp_data:
            state.temp_data = temp_data
        else:
            state.temp_data = {}
        state.last_activity = datetime.now().isoformat()
        self.save_states()

    def clear_action(self, user_id: int):
        state = self.get_state(user_id)
        state.current_action = None
        state.temp_data = {}
        state.last_activity = datetime.now().isoformat()
        self.save_states()

    def is_admin(self, user_id: int) -> bool:
        return user_id in ADMIN_USER_IDS

    def increment_reports(self, user_id: int):
        state = self.get_state(user_id)
        today = datetime.now().date().isoformat()
        
        if state.last_report_date != today:
            state.reports_today = 0
            state.last_report_date = today
        
        state.reports_today += 1
        self.save_states()

    def increment_tasks(self, user_id: int):
        state = self.get_state(user_id)
        state.tasks_created += 1
        self.save_states()

class TargetLimitManager:
    def __init__(self):
        self.limits: Dict[str, TargetLimit] = {}
        self.load_limits()

    def load_limits(self):
        data = FileManager.load_json(TARGET_LIMITS_FILE, {})
        self.limits = {k: TargetLimit(**v) for k, v in data.items()}

    def save_limits(self):
        FileManager.save_json(TARGET_LIMITS_FILE, {k: asdict(v) for k, v in self.limits.items()})

    def set_limit(self, target: str, max_reports: int, created_by: Optional[int] = None, reason: str = ""):
        target = target.lower().strip('@')
        if target in self.limits:
            self.limits[target].max_reports = max_reports
            self.limits[target].reason = reason
        else:
            self.limits[target] = TargetLimit(
                target=target,
                max_reports=max_reports,
                created_by=created_by,
                reason=reason
            )
        self.save_limits()

    def can_report(self, target: str) -> Tuple[bool, Optional[str]]:
        target = target.lower().strip('@')
        if target not in self.limits:
            return True, None
        
        limit = self.limits[target]
        if limit.current_reports >= limit.max_reports:
            return False, f"Target limit reached: {limit.current_reports}/{limit.max_reports}"
        return True, None

    def increment_report(self, target: str):
        target = target.lower().strip('@')
        if target in self.limits:
            self.limits[target].current_reports += 1
            self.limits[target].last_reported = datetime.now().isoformat()
            self.save_limits()

    def get_limit(self, target: str) -> Optional[TargetLimit]:
        target = target.lower().strip('@')
        return self.limits.get(target)

    def remove_limit(self, target: str):
        target = target.lower().strip('@')
        if target in self.limits:
            del self.limits[target]
            self.save_limits()
            return True
        return False

    def list_limits(self) -> List[TargetLimit]:
        return list(self.limits.values())

    def reset_count(self, target: str):
        target = target.lower().strip('@')
        if target in self.limits:
            self.limits[target].current_reports = 0
            self.save_limits()
            return True
        return False

class StatisticsManager:
    def __init__(self):
        self.stats = Statistics()
        self.load_stats()

    def load_stats(self):
        data = FileManager.load_json(STATISTICS_FILE, None)
        if data:
            self.stats = Statistics(**data)

    def save_stats(self):
        self.stats.last_updated = datetime.now().isoformat()
        FileManager.save_json(STATISTICS_FILE, asdict(self.stats))

    def record_report(self, session_id: str, reason_id: int, user_id: int, success: bool):
        self.stats.total_reports += 1
        if success:
            self.stats.successful_reports += 1
        else:
            self.stats.failed_reports += 1
        
        self.stats.reports_by_reason[reason_id] = self.stats.reports_by_reason.get(reason_id, 0) + 1
        self.stats.reports_by_session[session_id] = self.stats.reports_by_session.get(session_id, 0) + 1
        self.stats.reports_by_user[user_id] = self.stats.reports_by_user.get(user_id, 0) + 1
        
        hour = datetime.now().hour
        day = datetime.now().date().isoformat()
        self.stats.reports_by_hour[hour] = self.stats.reports_by_hour.get(hour, 0) + 1
        self.stats.reports_by_day[day] = self.stats.reports_by_day.get(day, 0) + 1
        
        self.save_stats()

    def record_flood_wait(self, seconds: int):
        self.stats.flood_waits += 1
        self.stats.total_flood_wait_time += seconds
        self.save_stats()

    def record_task_completion(self, success: bool):
        self.stats.total_tasks += 1
        if success:
            self.stats.completed_tasks += 1
        else:
            self.stats.failed_tasks += 1
        self.save_stats()

    def get_stats(self) -> Statistics:
        return self.stats

    def get_success_rate(self) -> float:
        if self.stats.total_reports == 0:
            return 0.0
        return (self.stats.successful_reports / self.stats.total_reports) * 100

    def get_daily_report(self) -> Dict[str, int]:
        today = datetime.now().date().isoformat()
        yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
        
        return {
            "today": self.stats.reports_by_day.get(today, 0),
            "yesterday": self.stats.reports_by_day.get(yesterday, 0)
        }

class HistoryManager:
    def __init__(self):
        self.history: List[ReportHistory] = []
        self.load_history()

    def load_history(self):
        data = FileManager.load_json(REPORT_HISTORY_FILE, [])
        self.history = [ReportHistory(**h) for h in data]

    def save_history(self):
        FileManager.save_json(REPORT_HISTORY_FILE, [asdict(h) for h in self.history])

    def add_history(self, task_id: str, user_id: int, target: str, reason_id: int,
                    count: int, successful: int, failed: int, session_id: str,
                    duration: float, notes: str = ""):
        history_id = f"hist_{int(datetime.now().timestamp() * 1000)}"
        entry = ReportHistory(
            history_id=history_id,
            task_id=task_id,
            user_id=user_id,
            target=target,
            reason_id=reason_id,
            count=count,
            successful=successful,
            failed=failed,
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            duration=duration,
            notes=notes
        )
        self.history.append(entry)
        self.save_history()

    def get_user_history(self, user_id: int, limit: int = 50) -> List[ReportHistory]:
        user_history = [h for h in self.history if h.user_id == user_id]
        user_history.sort(key=lambda x: x.timestamp, reverse=True)
        return user_history[:limit]

    def get_target_history(self, target: str) -> List[ReportHistory]:
        target = target.lower().strip('@')
        return [h for h in self.history if h.target.lower().strip('@') == target]

class BlacklistManager:
    def __init__(self):
        self.blacklist: List[str] = []
        self.load_blacklist()

    def load_blacklist(self):
        self.blacklist = FileManager.load_json(BLACKLIST_FILE, [])

    def save_blacklist(self):
        FileManager.save_json(BLACKLIST_FILE, self.blacklist)

    def add(self, target: str):
        target = target.lower().strip('@')
        if target not in self.blacklist:
            self.blacklist.append(target)
            self.save_blacklist()
            return True
        return False

    def remove(self, target: str):
        target = target.lower().strip('@')
        if target in self.blacklist:
            self.blacklist.remove(target)
            self.save_blacklist()
            return True
        return False

    def is_blacklisted(self, target: str) -> bool:
        target = target.lower().strip('@')
        return target in self.blacklist

    def list_all(self) -> List[str]:
        return self.blacklist.copy()

class WhitelistManager:
    def __init__(self):
        self.whitelist: List[str] = []
        self.enabled: bool = False
        self.load_whitelist()

    def load_whitelist(self):
        data = FileManager.load_json(WHITELIST_FILE, {"enabled": False, "list": []})
        self.enabled = data.get("enabled", False)
        self.whitelist = data.get("list", [])

    def save_whitelist(self):
        FileManager.save_json(WHITELIST_FILE, {"enabled": self.enabled, "list": self.whitelist})

    def add(self, target: str):
        target = target.lower().strip('@')
        if target not in self.whitelist:
            self.whitelist.append(target)
            self.save_whitelist()
            return True
        return False

    def remove(self, target: str):
        target = target.lower().strip('@')
        if target in self.whitelist:
            self.whitelist.remove(target)
            self.save_whitelist()
            return True
        return False

    def is_whitelisted(self, target: str) -> bool:
        if not self.enabled:
            return True
        target = target.lower().strip('@')
        return target in self.whitelist

    def toggle_enabled(self):
        self.enabled = not self.enabled
        self.save_whitelist()
        return self.enabled

    def list_all(self) -> List[str]:
        return self.whitelist.copy()

class SessionFileImporter:
    @staticmethod
    def import_session_file(file_path: Path) -> Optional[str]:
        try:
            if file_path.suffix == '.session':
                session_name = file_path.stem
                dest_path = SESSIONS_DIR / file_path.name
                import shutil
                shutil.copy2(file_path, dest_path)
                logger.info(f"Imported session file: {session_name}")
                return session_name
            return None
        except Exception as e:
            logger.error(f"Failed to import session file: {e}")
            return None
    
    @staticmethod
    def import_from_zip(zip_path: Path) -> List[str]:
        import zipfile
        imported = []
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for file_info in zip_ref.filelist:
                    if file_info.filename.endswith('.session'):
                        zip_ref.extract(file_info, SESSIONS_DIR)
                        session_name = Path(file_info.filename).stem
                        
                        # ✅ FIX: Register session in session_manager
                        if not session_manager.get_session_info(session_name):
                            session_manager.add_session(
                                session_id=session_name,
                                api_id=BOT_API_ID,
                                api_hash=BOT_API_HASH,
                                phone="Unknown",
                                notes="Imported from ZIP - Update credentials"
                            )
                        
                        imported.append(session_name)
                        logger.info(f"Extracted and registered session: {session_name}")
            return imported
        except Exception as e:
            logger.error(f"Failed to import from zip: {e}")
            return []
    
    @staticmethod
    def import_from_json(json_path: Path) -> bool:
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
            
            if isinstance(data, dict):
                for session_id, session_data in data.items():
                    if 'api_id' in session_data and 'api_hash' in session_data and 'phone' in session_data:
                        session_manager.add_session(
                            session_id=session_data.get('session_id', session_id),
                            api_id=int(session_data['api_id']),
                            api_hash=session_data['api_hash'],
                            phone=session_data['phone'],
                            notes=session_data.get('notes', 'Imported from JSON')
                        )
                        logger.info(f"Imported session config from JSON: {session_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to import from JSON: {e}")
            return False
    
    @staticmethod
    def auto_detect_and_import(file_path: Path) -> Dict[str, Any]:
        result = {
            'success': False,
            'type': None,
            'imported': [],
            'message': ''
        }
        
        if not file_path.exists():
            result['message'] = 'File not found'
            return result
        
        if file_path.suffix == '.session':
            session_name = SessionFileImporter.import_session_file(file_path)
            if session_name:
                result['success'] = True
                result['type'] = 'session'
                result['imported'] = [session_name]
                result['message'] = f'Imported session: {session_name}'
        
        elif file_path.suffix == '.zip':
            imported = SessionFileImporter.import_from_zip(file_path)
            if imported:
                result['success'] = True
                result['type'] = 'zip'
                result['imported'] = imported
                result['message'] = f'Imported {len(imported)} sessions from zip'
        
        elif file_path.suffix == '.json':
            success = SessionFileImporter.import_from_json(file_path)
            if success:
                result['success'] = True
                result['type'] = 'json'
                result['message'] = 'Imported session configs from JSON'
        
        else:
            result['message'] = f'Unsupported file type: {file_path.suffix}'
        
        return result
    
    @staticmethod
    def scan_upload_directory() -> List[Dict[str, Any]]:
        results = []
        for file_path in UPLOAD_DIR.glob('*'):
            if file_path.is_file():
                result = SessionFileImporter.auto_detect_and_import(file_path)
                results.append({
                    'file': file_path.name,
                    'result': result
                })
        return results

session_file_importer = SessionFileImporter()

session_manager = SessionManager()
report_queue = ReportQueue()
user_state_manager = UserStateManager()
target_limit_manager = TargetLimitManager()
stats_manager = StatisticsManager()
history_manager = HistoryManager()
blacklist_manager = BlacklistManager()
whitelist_manager = WhitelistManager()

async def execute_report(client: TelegramClient, target: str, reason_id: int) -> Tuple[bool, str]:
    try:
        entity = await client.get_entity(target)
        reason_class = REASON_MAP[reason_id][1]
        
        if isinstance(entity, (Channel, User)):
            await client(ReportPeerRequest(
                peer=entity,
                reason=reason_class(),
                message=""
            ))
        else:
            await client(ReportRequest(
                peer=entity,
                id=[1],
                reason=reason_class(),
                message=""
            ))
        
        return True, "Report sent successfully"
    except FloodWaitError as e:
        return False, f"FloodWait:{e.seconds}"
    except ChannelPrivateError:
        return False, "Channel is private"
    except UserPrivacyRestrictedError:
        return False, "User privacy restricted"
    except PeerIdInvalidError:
        return False, "Invalid peer ID"
    except Exception as e:
        return False, str(e)

async def process_report_task(task: ReportTask):
    logger.info(f"Processing task {task.task_id}")
    start_time = time.time()
    
    report_queue.update_task(task.task_id, status="processing", started_at=datetime.now().isoformat())
    
    if blacklist_manager.is_blacklisted(task.target):
        report_queue.update_task(
            task.task_id,
            status="failed",
            error_message="Target is blacklisted",
            finished_at=datetime.now().isoformat()
        )
        stats_manager.record_task_completion(False)
        return
    
    if not whitelist_manager.is_whitelisted(task.target):
        report_queue.update_task(
            task.task_id,
            status="failed",
            error_message="Target not in whitelist",
            finished_at=datetime.now().isoformat()
        )
        stats_manager.record_task_completion(False)
        return
    
    session_id = task.session_id or session_manager.get_available_session()
    if not session_id:
        if task.retry_count < task.max_retries:
            report_queue.update_task(task.task_id, retry_count=task.retry_count + 1, status="pending")
            logger.warning(f"Task {task.task_id}: No session available, will retry")
            return
        else:
            report_queue.update_task(
                task.task_id,
                status="failed",
                error_message="No available session",
                finished_at=datetime.now().isoformat()
            )
            stats_manager.record_task_completion(False)
            return
    
    client = await session_manager.get_client(session_id)
    if not client:
        report_queue.update_task(
            task.task_id,
            status="failed",
            error_message=f"Failed to connect session {session_id}",
            finished_at=datetime.now().isoformat()
        )
        stats_manager.record_task_completion(False)
        return
    
    session_manager.update_session_status(session_id, "active")
    
    can_report, reason = target_limit_manager.can_report(task.target)
    if not can_report:
        report_queue.update_task(
            task.task_id,
            status="failed",
            error_message=reason,
            finished_at=datetime.now().isoformat()
        )
        session_manager.update_session_status(session_id, "idle")
        stats_manager.record_task_completion(False)
        return
    
    completed = 0
    failed = 0
    
    for i in range(task.count):
        success, message = await execute_report(client, task.target, task.reason_id)
        
        if success:
            completed += 1
            session_manager.increment_reports(session_id, True)
            target_limit_manager.increment_report(task.target)
            stats_manager.record_report(session_id, task.reason_id, task.user_id, True)
            user_state_manager.increment_reports(task.user_id)
            logger.info(f"Task {task.task_id}: Report {i+1}/{task.count} sent")
        else:
            failed += 1
            session_manager.increment_reports(session_id, False)
            stats_manager.record_report(session_id, task.reason_id, task.user_id, False)
            
            if message.startswith("FloodWait"):
                try:
                    wait_seconds = int(message.split(":")[1])
                    session_manager.set_flood_wait(session_id, wait_seconds)
                    stats_manager.record_flood_wait(wait_seconds)
                    break
                except:
                    pass
            
            logger.error(f"Task {task.task_id}: Report {i+1}/{task.count} failed - {message}")
        
        report_queue.update_task(task.task_id, completed=completed, failed=failed)
        
        if i < task.count - 1:
            delay = random.uniform(2, 5)
            await asyncio.sleep(delay)
    
    duration = time.time() - start_time
    
    status = "completed" if completed == task.count else "partial"
    if completed == 0:
        status = "failed"
    
    report_queue.update_task(
        task.task_id,
        status=status,
        completed=completed,
        failed=failed,
        finished_at=datetime.now().isoformat()
    )
    
    history_manager.add_history(
        task_id=task.task_id,
        user_id=task.user_id,
        target=task.target,
        reason_id=task.reason_id,
        count=task.count,
        successful=completed,
        failed=failed,
        session_id=session_id,
        duration=duration,
        notes=task.notes
    )
    
    session_manager.update_session_status(session_id, "idle")
    stats_manager.record_task_completion(status == "completed")
    
    logger.info(f"Task {task.task_id} finished: {completed} completed, {failed} failed in {duration:.2f}s")

async def task_processor():
    while True:
        try:
            pending_tasks = report_queue.get_pending_tasks()
            active_tasks = report_queue.get_active_tasks()
            
            max_concurrent = 3
            can_process = max_concurrent - len(active_tasks)
            
            for task in pending_tasks[:can_process]:
                asyncio.create_task(process_report_task(task))
            
            await asyncio.sleep(10)
        except Exception as e:
            logger.error(f"Task processor error: {e}")
            await asyncio.sleep(30)

async def periodic_cleanup():
    while True:
        try:
            await asyncio.sleep(3600)
            report_queue.cleanup_old_tasks(days=7)
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

def get_main_menu_buttons(is_admin: bool = False):
    buttons = [
        [Button.inline("📊 New Report", b"new_task")],
        [Button.inline("📋 My Tasks", b"my_tasks"), Button.inline("📈 Stats", b"stats")],
        [Button.inline("🎯 Limits", b"target_limits"), Button.inline("📜 History", b"history")],
        [Button.inline("ℹ️ Help", b"help")]
    ]
    
    if is_admin:
        buttons.append([Button.inline("⚙️ Admin", b"admin_panel")])
    
    return buttons

def get_admin_menu_buttons():
    return [
        [Button.inline("📱 Sessions", b"admin_sessions"), Button.inline("📊 Tasks", b"admin_tasks")],
        [Button.inline("📈 Stats", b"admin_stats"), Button.inline("🎯 Limits", b"admin_limits")],
        [Button.inline("🚫 Blacklist", b"admin_blacklist"), Button.inline("✅ Whitelist", b"admin_whitelist")],
        [Button.inline("📥 Import Sessions", b"admin_import"), Button.inline("📤 Export", b"admin_export")],
        [Button.inline("🔙 Back", b"main_menu")]
    ]

bot = TelegramClient('reporter_bot', BOT_API_ID, BOT_API_HASH).start(bot_token=BOT_TOKEN)

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user_id = event.sender_id
    is_admin = user_state_manager.is_admin(user_id)
    
    welcome_text = """🤖 **Multi-Session Reporter Bot**

✨ Features:
• Multi-session support
• 20 report reasons
• Target limits
• Task queue
• Real-time statistics
• History tracking

Choose an option below:"""
    
    await event.respond(welcome_text, buttons=get_main_menu_buttons(is_admin))

@bot.on(events.CallbackQuery(pattern=b"main_menu"))
async def main_menu_handler(event):
    user_id = event.sender_id
    is_admin = user_state_manager.is_admin(user_id)
    user_state_manager.clear_action(user_id)
    
    await event.edit(
        "🏠 **Main Menu**\n\nChoose an option:",
        buttons=get_main_menu_buttons(is_admin)
    )

@bot.on(events.CallbackQuery(pattern=b"new_task"))
async def new_task_handler(event):
    user_id = event.sender_id
    user_state_manager.set_action(user_id, "awaiting_target")
    
    await event.edit(
        "📊 **New Report Task**\n\n"
        "Enter target username or link:\n"
        "Examples:\n"
        "• @username\n"
        "• username\n"
        "• https://t.me/username",
        buttons=[[Button.inline("🔙 Cancel", b"main_menu")]]
    )

@bot.on(events.NewMessage())
async def message_handler(event):
    if event.is_private and not event.message.message.startswith('/'):
        user_id = event.sender_id
        state = user_state_manager.get_state(user_id)
        
        if event.message.document:
            if not user_state_manager.is_admin(user_id):
                await event.respond("❌ Only admins can upload session files")
                return
            
            try:
                file = await event.message.download_media(file=UPLOAD_DIR)
                file_path = Path(file)
                
                result = session_file_importer.auto_detect_and_import(file_path)
                
                if result['success']:
                    response = f"✅ **Import Successful**\n\n"
                    response += f"Type: {result['type']}\n"
                    response += f"Message: {result['message']}\n"
                    
                    if result['imported']:
                        response += f"\n**Imported Sessions:**\n"
                        for session in result['imported']:
                            response += f"• {session}\n"
                    
                    await event.respond(
                        response,
                        buttons=[[Button.inline("📱 View Sessions", b"admin_sessions")],
                                [Button.inline("🏠 Main Menu", b"main_menu")]]
                    )
                else:
                    await event.respond(
                        f"❌ **Import Failed**\n\n{result['message']}",
                        buttons=[[Button.inline("🔙 Back", b"main_menu")]]
                    )
                
                try:
                    file_path.unlink()
                except:
                    pass
                
                return
                
            except Exception as e:
                await event.respond(f"❌ Error processing file: {e}")
                return
        
        if state.current_action == "awaiting_target":
            target = event.message.message.strip()
            
            if blacklist_manager.is_blacklisted(target):
                await event.respond(
                    "❌ This target is blacklisted and cannot be reported.",
                    buttons=[[Button.inline("🔙 Back", b"main_menu")]]
                )
                user_state_manager.clear_action(user_id)
                return
            
            if not whitelist_manager.is_whitelisted(target):
                await event.respond(
                    "❌ This target is not whitelisted. Contact admin.",
                    buttons=[[Button.inline("🔙 Back", b"main_menu")]]
                )
                user_state_manager.clear_action(user_id)
                return
            
            user_state_manager.set_action(user_id, "awaiting_reason", {"target": target})
            
            reason_text = "**Select Report Reason:**\n\n"
            buttons = []
            for i in range(1, 21, 2):
                row = []
                for j in range(2):
                    rid = i + j
                    if rid <= 20:
                        name = REASON_MAP[rid][0]
                        row.append(Button.inline(f"{rid}. {name[:12]}...", f"reason_{rid}".encode()))
                buttons.append(row)
            
            buttons.append([Button.inline("🔙 Cancel", b"main_menu")])
            
            await event.respond(reason_text, buttons=buttons)
        
        elif state.current_action == "awaiting_count":
            try:
                count = int(event.message.message.strip())
                if count < 1 or count > 100:
                    await event.respond("❌ Count must be between 1 and 100")
                    return
                
                state.temp_data["count"] = count
                user_state_manager.set_action(user_id, "awaiting_session", state.temp_data)
                
                sessions = session_manager.list_sessions()
                if not sessions:
                    await event.respond("❌ No sessions available. Contact admin.")
                    user_state_manager.clear_action(user_id)
                    return
                
                buttons = [[Button.inline("🔄 Auto Select", b"session_auto")]]
                for session in sessions[:8]:
                    status_emoji = "✅" if session.status == "idle" else "⏸️"
                    buttons.append([Button.inline(
                        f"{status_emoji} {session.session_id[:15]} ({session.reports_sent})",
                        f"session_{session.session_id}".encode()
                    )])
                
                buttons.append([Button.inline("🔙 Cancel", b"main_menu")])
                
                await event.respond("**Select Session:**", buttons=buttons)
            
            except ValueError:
                await event.respond("❌ Please enter a valid number")
        
        elif state.current_action == "awaiting_session_add_id":
            api_id = event.message.message.strip()
            state.temp_data["api_id"] = api_id
            user_state_manager.set_action(user_id, "awaiting_session_add_hash", state.temp_data)
            await event.respond("Enter API Hash:")
        
        elif state.current_action == "awaiting_session_add_hash":
            api_hash = event.message.message.strip()
            state.temp_data["api_hash"] = api_hash
            user_state_manager.set_action(user_id, "awaiting_session_add_phone", state.temp_data)
            await event.respond("Enter Phone Number:")
        
        elif state.current_action == "awaiting_session_add_phone":
            phone = event.message.message.strip()
            state.temp_data["phone"] = phone
            user_state_manager.set_action(user_id, "awaiting_session_add_name", state.temp_data)
            await event.respond("Enter Session Name:")
        
        elif state.current_action == "awaiting_session_add_name":
            session_name = event.message.message.strip()
            
            try:
                api_id = int(state.temp_data["api_id"])
                api_hash = state.temp_data["api_hash"]
                phone = state.temp_data["phone"]
                
                session_manager.add_session(session_name, api_id, api_hash, phone)
                
                await event.respond(
                    f"✅ Session **{session_name}** added!",
                    buttons=[[Button.inline("🔙 Back", b"admin_panel")]]
                )
                user_state_manager.clear_action(user_id)
            except Exception as e:
                await event.respond(f"❌ Error: {e}")
                user_state_manager.clear_action(user_id)
        
        elif state.current_action == "awaiting_limit_target":
            target = event.message.message.strip()
            state.temp_data["target"] = target
            user_state_manager.set_action(user_id, "awaiting_limit_count", state.temp_data)
            await event.respond("Enter maximum reports:")
        
        elif state.current_action == "awaiting_limit_count":
            try:
                max_reports = int(event.message.message.strip())
                target = state.temp_data["target"]
                
                target_limit_manager.set_limit(target, max_reports, created_by=user_id)
                await event.respond(
                    f"✅ Limit set: **{target}** = {max_reports}",
                    buttons=[[Button.inline("🔙 Back", b"target_limits")]]
                )
                user_state_manager.clear_action(user_id)
            except ValueError:
                await event.respond("❌ Invalid number")
        
        elif state.current_action == "awaiting_blacklist_add":
            target = event.message.message.strip()
            if blacklist_manager.add(target):
                await event.respond(
                    f"✅ Added to blacklist: **{target}**",
                    buttons=[[Button.inline("🔙 Back", b"admin_blacklist")]]
                )
            else:
                await event.respond("⚠️ Already blacklisted")
            user_state_manager.clear_action(user_id)
        
        elif state.current_action == "awaiting_whitelist_add":
            target = event.message.message.strip()
            if whitelist_manager.add(target):
                await event.respond(
                    f"✅ Added to whitelist: **{target}**",
                    buttons=[[Button.inline("🔙 Back", b"admin_whitelist")]]
                )
            else:
                await event.respond("⚠️ Already whitelisted")
            user_state_manager.clear_action(user_id)

@bot.on(events.CallbackQuery(pattern=b"reason_"))
async def reason_handler(event):
    user_id = event.sender_id
    state = user_state_manager.get_state(user_id)
    
    if state.current_action != "awaiting_reason":
        return
    
    reason_id = int(event.data.decode().split("_")[1])
    state.temp_data["reason_id"] = reason_id
    user_state_manager.set_action(user_id, "awaiting_count", state.temp_data)
    
    reason_name = REASON_MAP[reason_id][0]
    await event.edit(
        f"**Reason:** {reason_name}\n\n"
        f"Enter report count (1-100):",
        buttons=[[Button.inline("🔙 Cancel", b"main_menu")]]
    )

@bot.on(events.CallbackQuery(pattern=b"session_"))
async def session_select_handler(event):
    user_id = event.sender_id
    state = user_state_manager.get_state(user_id)
    
    if state.current_action != "awaiting_session":
        return
    
    session_data = event.data.decode().split("_", 1)[1]
    
    if session_data == "auto":
        session_id = None
    else:
        session_id = session_data
    
    target = state.temp_data["target"]
    reason_id = state.temp_data["reason_id"]
    count = state.temp_data["count"]
    
    can_report, limit_message = target_limit_manager.can_report(target)
    if not can_report:
        await event.edit(
            f"❌ {limit_message}",
            buttons=[[Button.inline("🔙 Back", b"main_menu")]]
        )
        user_state_manager.clear_action(user_id)
        return
    
    task_id = report_queue.add_task(user_id, target, reason_id, count, session_id)
    user_state_manager.increment_tasks(user_id)
    
    reason_name = REASON_MAP[reason_id][0]
    session_text = session_id if session_id else "Auto"
    
    await event.edit(
        f"✅ **Task Created!**\n\n"
        f"📋 ID: `{task_id[:20]}...`\n"
        f"🎯 Target: {target}\n"
        f"📝 Reason: {reason_name}\n"
        f"🔢 Count: {count}\n"
        f"📱 Session: {session_text}\n\n"
        f"Processing automatically...",
        buttons=[[Button.inline("📋 My Tasks", b"my_tasks")],
                 [Button.inline("🏠 Menu", b"main_menu")]]
    )
    user_state_manager.clear_action(user_id)

@bot.on(events.CallbackQuery(pattern=b"my_tasks"))
async def my_tasks_handler(event):
    user_id = event.sender_id
    tasks = report_queue.get_user_tasks(user_id)
    
    if not tasks:
        await event.edit(
            "📋 **Your Tasks**\n\nNo tasks found.",
            buttons=[[Button.inline("🔙 Back", b"main_menu")]]
        )
        return
    
    tasks_text = f"📋 **Your Tasks** ({len(tasks)}):\n\n"
    buttons = []
    
    status_emojis = {
        "pending": "⏳",
        "processing": "⚙️",
        "completed": "✅",
        "failed": "❌",
        "partial": "⚠️"
    }
    
    for task in tasks[:12]:
        emoji = status_emojis.get(task.status, "❓")
        reason_name = REASON_MAP[task.reason_id][0]
        
        tasks_text += f"{emoji} {task.target[:20]} - {reason_name[:15]}\n"
        tasks_text += f"   {task.completed}/{task.count} reports\n\n"
        
        buttons.append([Button.inline(
            f"{emoji} {task.task_id[:25]}",
            f"task_detail_{task.task_id}".encode()
        )])
    
    buttons.append([Button.inline("🔙 Back", b"main_menu")])
    
    await event.edit(tasks_text[:4000], buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b"task_detail_"))
async def task_detail_handler(event):
    task_id = event.data.decode().split("_", 2)[2]
    task = report_queue.get_task(task_id)
    
    if not task:
        await event.answer("Task not found", alert=True)
        return
    
    reason_name = REASON_MAP[task.reason_id][0]
    status_map = {
        "pending": "⏳ Pending",
        "processing": "⚙️ Processing",
        "completed": "✅ Completed",
        "failed": "❌ Failed",
        "partial": "⚠️ Partial"
    }
    status_text = status_map.get(task.status, "❓ Unknown")
    
    text = f"""📋 **Task Details**

🆔 ID: `{task.task_id}`
🎯 Target: {task.target}
📝 Reason: {reason_name}
📊 Status: {status_text}
✅ Success: {task.completed}/{task.count}
❌ Failed: {task.failed}
📱 Session: {task.session_id or 'Auto'}
📅 Created: {task.created_at[:19]}
"""
    
    if task.started_at:
        text += f"▶️ Started: {task.started_at[:19]}\n"
    if task.finished_at:
        text += f"🏁 Finished: {task.finished_at[:19]}\n"
    if task.error_message:
        text += f"⚠️ Error: {task.error_message}\n"
    
    buttons = []
    if task.status == "pending":
        buttons.append([Button.inline("🗑️ Cancel", f"task_cancel_{task_id}".encode())])
    
    buttons.append([Button.inline("🔙 Back", b"my_tasks")])
    
    await event.edit(text, buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b"task_cancel_"))
async def task_cancel_handler(event):
    task_id = event.data.decode().split("_", 2)[2]
    report_queue.delete_task(task_id)
    
    await event.edit(
        f"✅ Task cancelled.",
        buttons=[[Button.inline("📋 Tasks", b"my_tasks")],
                 [Button.inline("🏠 Menu", b"main_menu")]]
    )

@bot.on(events.CallbackQuery(pattern=b"stats"))
async def stats_handler(event):
    user_id = event.sender_id
    state = user_state_manager.get_state(user_id)
    tasks = report_queue.get_user_tasks(user_id)
    stats = stats_manager.get_stats()
    
    user_reports = stats.reports_by_user.get(user_id, 0)
    
    total = len(tasks)
    completed = len([t for t in tasks if t.status == "completed"])
    pending = len([t for t in tasks if t.status == "pending"])
    
    success_rate = stats_manager.get_success_rate()
    daily = stats_manager.get_daily_report()
    
    text = f"""📈 **Your Statistics**

📊 Reports: {user_reports}
📋 Tasks: {total}
✅ Completed: {completed}
⏳ Pending: {pending}
📅 Today's Reports: {state.reports_today}

**System:**
🌐 Total: {stats.total_reports}
✅ Rate: {success_rate:.1f}%
📅 Today: {daily['today']}
⚠️ Flood Waits: {stats.flood_waits}
"""
    
    await event.edit(text, buttons=[[Button.inline("🔙 Back", b"main_menu")]])

@bot.on(events.CallbackQuery(pattern=b"target_limits"))
async def target_limits_handler(event):
    limits = target_limit_manager.list_limits()
    
    if not limits:
        text = "🎯 **Target Limits**\n\nNo limits set."
        buttons = [[Button.inline("➕ Add", b"add_limit")],
                   [Button.inline("🔙 Back", b"main_menu")]]
    else:
        text = f"🎯 **Target Limits** ({len(limits)}):\n\n"
        buttons = []
        
        for limit in limits[:10]:
            pct = (limit.current_reports / max(limit.max_reports, 1)) * 100
            text += f"• {limit.target}: {limit.current_reports}/{limit.max_reports} ({pct:.0f}%)\n"
            
            buttons.append([Button.inline(
                f"{limit.target[:20]} ({limit.current_reports}/{limit.max_reports})",
                f"limit_detail_{limit.target}".encode()
            )])
        
        buttons.append([Button.inline("➕ Add", b"add_limit")])
        buttons.append([Button.inline("🔙 Back", b"main_menu")])
    
    await event.edit(text, buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b"add_limit"))
async def add_limit_handler(event):
    user_id = event.sender_id
    user_state_manager.set_action(user_id, "awaiting_limit_target")
    
    await event.edit(
        "➕ **Add Limit**\n\nEnter target username:",
        buttons=[[Button.inline("🔙 Cancel", b"target_limits")]]
    )

@bot.on(events.CallbackQuery(pattern=b"limit_detail_"))
async def limit_detail_handler(event):
    target = event.data.decode().split("_", 2)[2]
    limit = target_limit_manager.get_limit(target)
    
    if not limit:
        await event.answer("Not found", alert=True)
        return
    
    pct = (limit.current_reports / max(limit.max_reports, 1)) * 100
    
    text = f"""🎯 **Limit Details**

📍 Target: {limit.target}
📊 Current: {limit.current_reports}/{limit.max_reports}
📈 Usage: {pct:.1f}%
📅 Created: {limit.created_at[:19]}
"""
    
    if limit.last_reported:
        text += f"🕐 Last: {limit.last_reported[:19]}\n"
    
    buttons = [
        [Button.inline("🔄 Reset", f"limit_reset_{target}".encode())],
        [Button.inline("🗑️ Remove", f"limit_remove_{target}".encode())],
        [Button.inline("🔙 Back", b"target_limits")]
    ]
    
    await event.edit(text, buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b"limit_reset_"))
async def limit_reset_handler(event):
    target = event.data.decode().split("_", 2)[2]
    target_limit_manager.reset_count(target)
    
    await event.edit(
        f"✅ Count reset for **{target}**",
        buttons=[[Button.inline("🔙 Back", b"target_limits")]]
    )

@bot.on(events.CallbackQuery(pattern=b"limit_remove_"))
async def limit_remove_handler(event):
    target = event.data.decode().split("_", 2)[2]
    target_limit_manager.remove_limit(target)
    
    await event.edit(
        f"✅ Limit removed for **{target}**",
        buttons=[[Button.inline("🔙 Back", b"target_limits")]]
    )

@bot.on(events.CallbackQuery(pattern=b"history"))
async def history_handler(event):
    user_id = event.sender_id
    history = history_manager.get_user_history(user_id, 15)
    
    if not history:
        await event.edit(
            "📜 **Report History**\n\nNo history found.",
            buttons=[[Button.inline("🔙 Back", b"main_menu")]]
        )
        return
    
    text = f"📜 **Report History** ({len(history)}):\n\n"
    
    for h in history:
        reason_name = REASON_MAP[h.reason_id][0]
        text += f"• {h.target[:20]}\n"
        text += f"  {reason_name[:20]} | {h.successful}/{h.count}\n"
        text += f"  {h.timestamp[:19]}\n\n"
    
    await event.edit(text[:4000], buttons=[[Button.inline("🔙 Back", b"main_menu")]])

@bot.on(events.CallbackQuery(pattern=b"help"))
async def help_handler(event):
    text = """ℹ️ **Help Guide**

**Features:**

📊 **New Report**
Create report tasks with target, reason, and count

📋 **My Tasks**
View and manage your tasks

📈 **Stats**
View your reporting statistics

🎯 **Limits**
Set/view target limits

📜 **History**
View report history

**Admin:**
⚙️ Manage sessions, tasks, limits, and more

**Support:** @admin_username
"""
    
    await event.edit(text, buttons=[[Button.inline("🔙 Back", b"main_menu")]])

@bot.on(events.CallbackQuery(pattern=b"admin_panel"))
async def admin_panel_handler(event):
    user_id = event.sender_id
    
    if not user_state_manager.is_admin(user_id):
        await event.answer("❌ Admin only", alert=True)
        return
    
    sessions = session_manager.get_session_stats()
    pending = len(report_queue.get_pending_tasks())
    stats = stats_manager.get_stats()
    
    text = f"""⚙️ **Admin Panel**

📱 Sessions: {sessions['total']} ({sessions['active']} active)
📋 Pending: {pending}
📊 Reports: {stats.total_reports}
✅ Rate: {stats_manager.get_success_rate():.1f}%
"""
    
    await event.edit(text, buttons=get_admin_menu_buttons())

@bot.on(events.CallbackQuery(pattern=b"admin_sessions"))
async def admin_sessions_handler(event):
    user_id = event.sender_id
    
    if not user_state_manager.is_admin(user_id):
        return
    
    sessions = session_manager.list_sessions()
    
    text = f"📱 **Sessions** ({len(sessions)}):\n\n"
    buttons = []
    
    status_map = {
        "idle": "✅",
        "active": "⚙️",
        "flood_wait": "⏸️",
        "disabled": "❌"
    }
    
    for s in sessions:
        emoji = status_map.get(s.status, "❓")
        text += f"{emoji} **{s.session_id[:20]}**\n"
        text += f"   Reports: {s.reports_sent} | Failed: {s.reports_failed}\n"
        text += f"   Rate: {s.success_rate:.1f}%\n\n"
        
        buttons.append([Button.inline(
            f"{emoji} {s.session_id[:25]}",
            f"session_detail_{s.session_id}".encode()
        )])
    
    buttons.append([Button.inline("➕ Add", b"session_add")])
    buttons.append([Button.inline("🔙 Back", b"admin_panel")])
    
    await event.edit(text[:4000], buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b"session_add"))
async def session_add_handler(event):
    user_id = event.sender_id
    
    if not user_state_manager.is_admin(user_id):
        return
    
    user_state_manager.set_action(user_id, "awaiting_session_add_id")
    
    await event.edit(
        "➕ **Add Session**\n\nEnter API ID:",
        buttons=[[Button.inline("🔙 Cancel", b"admin_sessions")]]
    )

@bot.on(events.CallbackQuery(pattern=b"session_detail_"))
async def session_detail_handler(event):
    user_id = event.sender_id
    
    if not user_state_manager.is_admin(user_id):
        return
    
    session_id = event.data.decode().split("_", 2)[2]
    session = session_manager.get_session_info(session_id)
    
    if not session:
        await event.answer("Not found", alert=True)
        return
    
    status_map = {
        "idle": "✅ Idle",
        "active": "⚙️ Active",
        "flood_wait": "⏸️ Flood Wait",
        "disabled": "❌ Disabled"
    }
    
    text = f"""📱 **Session Details**

🆔 ID: {session.session_id}
📞 Phone: {session.phone}
📊 Status: {status_map.get(session.status, "❓")}
✅ Sent: {session.reports_sent}
❌ Failed: {session.reports_failed}
📈 Rate: {session.success_rate:.1f}%
⚠️ Flood Waits: {session.total_flood_waits}
🕐 Last Used: {session.last_used[:19] if session.last_used else 'Never'}
"""
    
    if session.flood_wait_until:
        text += f"⏸️ Wait Until: {session.flood_wait_until[:19]}\n"
    
    buttons = [
        [Button.inline("🗑️ Remove", f"session_remove_{session_id}".encode())],
        [Button.inline("🔙 Back", b"admin_sessions")]
    ]
    
    await event.edit(text, buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b"session_remove_"))
async def session_remove_handler(event):
    user_id = event.sender_id
    
    if not user_state_manager.is_admin(user_id):
        return
    
    session_id = event.data.decode().split("_", 2)[2]
    session_manager.remove_session(session_id)
    
    await event.edit(
        f"✅ Session removed: **{session_id}**",
        buttons=[[Button.inline("🔙 Back", b"admin_sessions")]]
    )

@bot.on(events.CallbackQuery(pattern=b"admin_tasks"))
async def admin_tasks_handler(event):
    user_id = event.sender_id
    
    if not user_state_manager.is_admin(user_id):
        return
    
    pending = report_queue.get_pending_tasks()
    active = report_queue.get_active_tasks()
    all_tasks = list(report_queue.tasks.values())
    
    text = f"""📊 **All Tasks**

⏳ Pending: {len(pending)}
⚙️ Active: {len(active)}
📋 Total: {len(all_tasks)}
"""
    
    buttons = []
    for task in all_tasks[:15]:
        status_emojis = {"pending": "⏳", "processing": "⚙️", "completed": "✅", "failed": "❌"}
        emoji = status_emojis.get(task.status, "❓")
        
        buttons.append([Button.inline(
            f"{emoji} {task.task_id[:20]} - {task.target[:15]}",
            f"admin_task_detail_{task.task_id}".encode()
        )])
    
    buttons.append([Button.inline("🔙 Back", b"admin_panel")])
    
    await event.edit(text, buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b"admin_stats"))
async def admin_stats_handler(event):
    user_id = event.sender_id
    
    if not user_state_manager.is_admin(user_id):
        return
    
    stats = stats_manager.get_stats()
    sessions = session_manager.get_session_stats()
    daily = stats_manager.get_daily_report()
    
    success_rate = stats_manager.get_success_rate()
    
    text = f"""📈 **System Statistics**

**Reports:**
📊 Total: {stats.total_reports}
✅ Success: {stats.successful_reports}
❌ Failed: {stats.failed_reports}
📈 Rate: {success_rate:.1f}%
⚠️ Flood Waits: {stats.flood_waits}
⏱️ Total Wait: {stats.total_flood_wait_time}s

**Daily:**
📅 Today: {daily['today']}
📅 Yesterday: {daily['yesterday']}

**Sessions:**
📱 Total: {sessions['total']}
✅ Active: {sessions['active']}
💤 Idle: {sessions['idle']}

**Tasks:**
📋 Total: {stats.total_tasks}
✅ Completed: {stats.completed_tasks}
❌ Failed: {stats.failed_tasks}
"""
    
    await event.edit(text, buttons=[[Button.inline("🔙 Back", b"admin_panel")]])

@bot.on(events.CallbackQuery(pattern=b"admin_limits"))
async def admin_limits_handler(event):
    user_id = event.sender_id
    
    if not user_state_manager.is_admin(user_id):
        return
    
    limits = target_limit_manager.list_limits()
    
    text = f"🎯 **All Limits** ({len(limits)}):\n\n"
    
    for limit in limits[:20]:
        pct = (limit.current_reports / max(limit.max_reports, 1)) * 100
        text += f"• {limit.target}: {limit.current_reports}/{limit.max_reports} ({pct:.0f}%)\n"
    
    await event.edit(text[:4000], buttons=[[Button.inline("🔙 Back", b"admin_panel")]])

@bot.on(events.CallbackQuery(pattern=b"admin_blacklist"))
async def admin_blacklist_handler(event):
    user_id = event.sender_id
    
    if not user_state_manager.is_admin(user_id):
        return
    
    blacklist = blacklist_manager.list_all()
    
    if not blacklist:
        text = "🚫 **Blacklist**\n\nEmpty."
    else:
        text = f"🚫 **Blacklist** ({len(blacklist)}):\n\n"
        for target in blacklist[:20]:
            text += f"• {target}\n"
    
    buttons = [
        [Button.inline("➕ Add", b"blacklist_add")],
        [Button.inline("🔙 Back", b"admin_panel")]
    ]
    
    await event.edit(text, buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b"blacklist_add"))
async def blacklist_add_handler(event):
    user_id = event.sender_id
    
    if not user_state_manager.is_admin(user_id):
        return
    
    user_state_manager.set_action(user_id, "awaiting_blacklist_add")
    
    await event.edit(
        "➕ **Add to Blacklist**\n\nEnter username:",
        buttons=[[Button.inline("🔙 Cancel", b"admin_blacklist")]]
    )

@bot.on(events.CallbackQuery(pattern=b"admin_whitelist"))
async def admin_whitelist_handler(event):
    user_id = event.sender_id
    
    if not user_state_manager.is_admin(user_id):
        return
    
    whitelist = whitelist_manager.list_all()
    enabled = whitelist_manager.enabled
    
    status = "🟢 ENABLED" if enabled else "🔴 DISABLED"
    
    if not whitelist:
        text = f"✅ **Whitelist** {status}\n\nEmpty."
    else:
        text = f"✅ **Whitelist** {status} ({len(whitelist)}):\n\n"
        for target in whitelist[:20]:
            text += f"• {target}\n"
    
    buttons = [
        [Button.inline("🔄 Toggle", b"whitelist_toggle")],
        [Button.inline("➕ Add", b"whitelist_add")],
        [Button.inline("🔙 Back", b"admin_panel")]
    ]
    
    await event.edit(text, buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b"whitelist_toggle"))
async def whitelist_toggle_handler(event):
    user_id = event.sender_id
    
    if not user_state_manager.is_admin(user_id):
        return
    
    enabled = whitelist_manager.toggle_enabled()
    status = "enabled" if enabled else "disabled"
    
    await event.answer(f"Whitelist {status}", alert=True)
    await admin_whitelist_handler(event)

@bot.on(events.CallbackQuery(pattern=b"whitelist_add"))
async def whitelist_add_handler(event):
    user_id = event.sender_id
    
    if not user_state_manager.is_admin(user_id):
        return
    
    user_state_manager.set_action(user_id, "awaiting_whitelist_add")
    
    await event.edit(
        "➕ **Add to Whitelist**\n\nEnter username:",
        buttons=[[Button.inline("🔙 Cancel", b"admin_whitelist")]]
    )

@bot.on(events.CallbackQuery(pattern=b"admin_export"))
async def admin_export_handler(event):
    user_id = event.sender_id
    
    if not user_state_manager.is_admin(user_id):
        return
    
    try:
        stats_data = asdict(stats_manager.get_stats())
        tasks_data = [asdict(t) for t in report_queue.tasks.values()]
        history_data = [asdict(h) for h in history_manager.history]
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        stats_file = FileManager.export_to_csv([stats_data], f"stats_{timestamp}.csv")
        tasks_file = FileManager.export_to_csv(tasks_data, f"tasks_{timestamp}.csv")
        history_file = FileManager.export_to_csv(history_data, f"history_{timestamp}.csv")
        
        await event.answer("✅ Export complete!", alert=True)
        await event.edit(
            f"📤 **Export Complete**\n\n"
            f"Files saved to exports/ directory:\n"
            f"• stats_{timestamp}.csv\n"
            f"• tasks_{timestamp}.csv\n"
            f"• history_{timestamp}.csv",
            buttons=[[Button.inline("🔙 Back", b"admin_panel")]]
        )
    except Exception as e:
        await event.answer(f"❌ Error: {e}", alert=True)

async def main():
    logger.info("Starting bot...")
    asyncio.create_task(task_processor())
    asyncio.create_task(periodic_cleanup())
    logger.info("Bot started successfully!")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    try:
        bot.loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")


class AdvancedScheduler:
    def __init__(self):
        self.scheduled_tasks: Dict[str, ScheduledTask] = {}
        self.load_scheduled()
    
    def load_scheduled(self):
        data = FileManager.load_json(SCHEDULE_FILE, {})
        self.scheduled_tasks = {k: ScheduledTask(**v) for k, v in data.items()}
    
    def save_scheduled(self):
        FileManager.save_json(SCHEDULE_FILE, {k: asdict(v) for k, v in self.scheduled_tasks.items()})
    
    def add_scheduled(self, user_id: int, target: str, reason_id: int, count: int,
                     scheduled_time: str, session_id: Optional[str] = None,
                     repeat: bool = False, repeat_interval: Optional[int] = None) -> str:
        schedule_id = f"sched_{int(datetime.now().timestamp() * 1000)}"
        task = ScheduledTask(
            schedule_id=schedule_id,
            task_id=None,
            user_id=user_id,
            target=target,
            reason_id=reason_id,
            count=count,
            session_id=session_id,
            scheduled_time=scheduled_time,
            created_at=datetime.now().isoformat(),
            repeat=repeat,
            repeat_interval=repeat_interval
        )
        self.scheduled_tasks[schedule_id] = task
        self.save_scheduled()
        return schedule_id
    
    def get_due_tasks(self) -> List[ScheduledTask]:
        now = datetime.now()
        due = []
        for task in self.scheduled_tasks.values():
            if task.status == "pending":
                scheduled = datetime.fromisoformat(task.scheduled_time)
                if now >= scheduled:
                    due.append(task)
        return due
    
    def execute_scheduled(self, schedule_id: str, task_id: str):
        if schedule_id in self.scheduled_tasks:
            self.scheduled_tasks[schedule_id].task_id = task_id
            self.scheduled_tasks[schedule_id].status = "executed"
            self.scheduled_tasks[schedule_id].executed_at = datetime.now().isoformat()
            
            if self.scheduled_tasks[schedule_id].repeat and self.scheduled_tasks[schedule_id].repeat_interval:
                next_time = datetime.now() + timedelta(minutes=self.scheduled_tasks[schedule_id].repeat_interval)
                new_schedule_id = self.add_scheduled(
                    user_id=self.scheduled_tasks[schedule_id].user_id,
                    target=self.scheduled_tasks[schedule_id].target,
                    reason_id=self.scheduled_tasks[schedule_id].reason_id,
                    count=self.scheduled_tasks[schedule_id].count,
                    scheduled_time=next_time.isoformat(),
                    session_id=self.scheduled_tasks[schedule_id].session_id,
                    repeat=True,
                    repeat_interval=self.scheduled_tasks[schedule_id].repeat_interval
                )
            
            self.save_scheduled()

class ReportAnalytics:
    @staticmethod
    def get_hourly_distribution(stats: Statistics) -> Dict[int, int]:
        return dict(stats.reports_by_hour)
    
    @staticmethod
    def get_daily_distribution(stats: Statistics) -> Dict[str, int]:
        return dict(stats.reports_by_day)
    
    @staticmethod
    def get_reason_distribution(stats: Statistics) -> Dict[int, int]:
        return dict(stats.reports_by_reason)
    
    @staticmethod
    def get_session_distribution(stats: Statistics) -> Dict[str, int]:
        return dict(stats.reports_by_session)
    
    @staticmethod
    def get_top_reasons(stats: Statistics, limit: int = 5) -> List[Tuple[int, int]]:
        reasons = sorted(stats.reports_by_reason.items(), key=lambda x: x[1], reverse=True)
        return reasons[:limit]
    
    @staticmethod
    def get_top_sessions(stats: Statistics, limit: int = 5) -> List[Tuple[str, int]]:
        sessions = sorted(stats.reports_by_session.items(), key=lambda x: x[1], reverse=True)
        return sessions[:limit]
    
    @staticmethod
    def get_peak_hours(stats: Statistics) -> List[int]:
        hourly = dict(stats.reports_by_hour)
        if not hourly:
            return []
        max_reports = max(hourly.values())
        return [h for h, r in hourly.items() if r == max_reports]

class SessionHealth:
    @staticmethod
    def check_session_health(session: SessionConfig) -> Dict[str, Any]:
        total = session.reports_sent + session.reports_failed
        
        health_score = 0
        if total > 0:
            health_score = (session.reports_sent / total) * 100
        
        status = "excellent" if health_score >= 90 else ("good" if health_score >= 75 else ("fair" if health_score >= 50 else "poor"))
        
        return {
            "health_score": health_score,
            "status": status,
            "total_reports": total,
            "flood_waits": session.total_flood_waits,
            "is_authorized": session.is_authorized
        }
    
    @staticmethod
    def get_recommendations(session: SessionConfig) -> List[str]:
        recommendations = []
        
        if session.reports_failed > session.reports_sent:
            recommendations.append("High failure rate - check session authorization")
        
        if session.total_flood_waits > 10:
            recommendations.append("Frequent flood waits - reduce reporting rate")
        
        if not session.is_authorized:
            recommendations.append("Session not authorized - reauthorize required")
        
        if session.status == "disabled":
            recommendations.append("Session disabled - enable to resume operations")
        
        return recommendations

class RateLimiter:
    def __init__(self):
        self.hourly_limit = 50
        self.daily_limit = 500
        self.per_user_hourly = 10
        self.per_user_daily = 50
    
    def check_system_limit(self, stats: Statistics) -> Tuple[bool, Optional[str]]:
        now = datetime.now()
        hour = now.hour
        day = now.date().isoformat()
        
        hourly_count = stats.reports_by_hour.get(hour, 0)
        daily_count = stats.reports_by_day.get(day, 0)
        
        if hourly_count >= self.hourly_limit:
            return False, "System hourly limit reached"
        
        if daily_count >= self.daily_limit:
            return False, "System daily limit reached"
        
        return True, None
    
    def check_user_limit(self, user_id: int, stats: Statistics) -> Tuple[bool, Optional[str]]:
        now = datetime.now()
        state = user_state_manager.get_state(user_id)
        
        if state.reports_today >= self.per_user_daily:
            return False, "Your daily limit reached"
        
        return True, None
    
    def get_remaining(self, stats: Statistics) -> Dict[str, int]:
        now = datetime.now()
        hour = now.hour
        day = now.date().isoformat()
        
        hourly_count = stats.reports_by_hour.get(hour, 0)
        daily_count = stats.reports_by_day.get(day, 0)
        
        return {
            "hourly": max(0, self.hourly_limit - hourly_count),
            "daily": max(0, self.daily_limit - daily_count)
        }

class NotificationManager:
    @staticmethod
    async def notify_task_complete(bot: TelegramClient, user_id: int, task: ReportTask):
        try:
            reason_name = REASON_MAP[task.reason_id][0]
            message = (f"✅ **Task Completed**\n\n"
                      f"Target: {task.target}\n"
                      f"Reason: {reason_name}\n"
                      f"Success: {task.completed}/{task.count}")
            await bot.send_message(user_id, message)
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
    
    @staticmethod
    async def notify_flood_wait(bot: TelegramClient, user_id: int, session_id: str, seconds: int):
        try:
            message = (f"⚠️ **Flood Wait**\n\n"
                      f"Session: {session_id}\n"
                      f"Wait: {seconds}s")
            await bot.send_message(user_id, message)
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
    
    @staticmethod
    async def notify_admin_alert(bot: TelegramClient, message: str):
        try:
            for admin_id in ADMIN_USER_IDS:
                alert_msg = f"🚨 **Admin Alert**\n\n{message}"
                await bot.send_message(admin_id, alert_msg)
        except Exception as e:
            logger.error(f"Failed to send admin alert: {e}")

class BackupManager:
    @staticmethod
    def create_full_backup():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_{timestamp}"
        backup_path = BACKUP_DIR / backup_name
        backup_path.mkdir(exist_ok=True)
        
        files_to_backup = [
            SESSION_CONFIG_FILE,
            REPORT_QUEUE_FILE,
            REPORT_HISTORY_FILE,
            USER_STATES_FILE,
            STATISTICS_FILE,
            TARGET_LIMITS_FILE,
            BLACKLIST_FILE,
            WHITELIST_FILE
        ]
        
        for file in files_to_backup:
            if file.exists():
                import shutil
                shutil.copy2(file, backup_path / file.name)
        
        logger.info(f"Full backup created: {backup_path}")
        return str(backup_path)
    
    @staticmethod
    def list_backups() -> List[str]:
        backups = sorted(BACKUP_DIR.glob("backup_*"), reverse=True)
        return [b.name for b in backups]
    
    @staticmethod
    def restore_backup(backup_name: str):
        backup_path = BACKUP_DIR / backup_name
        if not backup_path.exists():
            return False
        
        for file in backup_path.glob("*.json"):
            import shutil
            shutil.copy2(file, DATA_DIR / file.name)
        
        logger.info(f"Restored backup: {backup_name}")
        return True

class PerformanceMonitor:
    def __init__(self):
        self.metrics: Dict[str, List[float]] = defaultdict(list)
    
    def record_metric(self, name: str, value: float):
        self.metrics[name].append(value)
        if len(self.metrics[name]) > 1000:
            self.metrics[name] = self.metrics[name][-1000:]
    
    def get_average(self, name: str) -> float:
        if name not in self.metrics or not self.metrics[name]:
            return 0.0
        return sum(self.metrics[name]) / len(self.metrics[name])
    
    def get_max(self, name: str) -> float:
        if name not in self.metrics or not self.metrics[name]:
            return 0.0
        return max(self.metrics[name])
    
    def get_min(self, name: str) -> float:
        if name not in self.metrics or not self.metrics[name]:
            return 0.0
        return min(self.metrics[name])

scheduler = AdvancedScheduler()
rate_limiter = RateLimiter()
performance_monitor = PerformanceMonitor()

async def scheduled_task_processor():
    while True:
        try:
            due_tasks = scheduler.get_due_tasks()
            
            for scheduled in due_tasks:
                task_id = report_queue.add_task(
                    user_id=scheduled.user_id,
                    target=scheduled.target,
                    reason_id=scheduled.reason_id,
                    count=scheduled.count,
                    session_id=scheduled.session_id,
                    notes=f"Scheduled task: {scheduled.schedule_id}"
                )
                
                scheduler.execute_scheduled(scheduled.schedule_id, task_id)
                logger.info(f"Executed scheduled task {scheduled.schedule_id} -> {task_id}")
            
            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"Scheduled task processor error: {e}")
            await asyncio.sleep(120)

async def health_monitor():
    while True:
        try:
            await asyncio.sleep(300)
            
            sessions = session_manager.list_sessions()
            critical_sessions = []
            
            for session in sessions:
                health = SessionHealth.check_session_health(session)
                if health["status"] == "poor":
                    critical_sessions.append(session.session_id)
            
            if critical_sessions:
                message = f"Sessions with poor health: {', '.join(critical_sessions)}"
                for admin_id in ADMIN_USER_IDS:
                    try:
                        await bot.send_message(admin_id, f"⚠️ {message}")
                    except:
                        pass
        
        except Exception as e:
            logger.error(f"Health monitor error: {e}")


@bot.on(events.CallbackQuery(pattern=b"admin_import"))
async def admin_import_handler(event):
    user_id = event.sender_id
    
    if not user_state_manager.is_admin(user_id):
        await event.answer("❌ Admin only", alert=True)
        return
    
    help_text = """📥 **Import Sessions**

**Supported formats:**
• **.session** - Single Telegram session file
• **.zip** - Multiple .session files
• **.json** - Session configuration file

**JSON format:**
```json
{
  "session1": {
    "session_id": "session1",
    "api_id": 12345,
    "api_hash": "hash",
    "phone": "+1234567890"
  }
}
```

**How to import:**
1. Upload file to this chat
2. Bot will auto-detect and import
3. Check imported sessions

📤 Upload your file now!"""
    
    await event.edit(
        help_text,
        buttons=[[Button.inline("🔙 Back", b"admin_panel")]]
    )

@bot.on(events.CallbackQuery(pattern=b"scan_uploads"))
async def scan_uploads_handler(event):
    user_id = event.sender_id
    
    if not user_state_manager.is_admin(user_id):
        return
    
    results = session_file_importer.scan_upload_directory()
    
    if not results:
        await event.answer("No files found in uploads directory", alert=True)
        return
    
    text = f"📥 **Scan Results** ({len(results)}):\n\n"
    
    for item in results:
        text += f"📄 **{item['file']}**\n"
        if item['result']['success']:
            text += f"✅ {item['result']['message']}\n"
        else:
            text += f"❌ {item['result']['message']}\n"
        text += "\n"
    
    await event.edit(
        text[:4000],
        buttons=[[Button.inline("🔙 Back", b"admin_import")]]
    )

