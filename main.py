#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TELEGRAM REPORT SYSTEM - ENTERPRISE EDITION v4.0
Advanced reporting tool with military-grade interface and functionality
"""

import asyncio
import time
import re
import json
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, List, Any
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import platform
import sys
import random
import uuid
import csv
import math
from collections import defaultdict, deque
import aiofiles
import os
import shutil

from telethon import TelegramClient, version as telethon_version
from telethon.errors import FloodWaitError, SessionPasswordNeededError, ChannelPrivateError
from telethon.tl.functions.account import ReportPeerRequest, UpdateStatusRequest
from telethon.tl.functions.messages import ReportRequest, GetMessagesViewsRequest
from telethon.tl.functions.channels import JoinChannelRequest, GetParticipantsRequest
from telethon.tl.functions.users import GetFullUserRequest
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
    Channel,
    User,
    InputPeerChannel,
    InputPeerUser,
    ChannelParticipantsRecent,
    UserStatusOnline,
    UserStatusOffline,
    UserStatusRecently,
    UserStatusLastWeek,
    UserStatusLastMonth
)

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm, IntPrompt, FloatPrompt
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
from rich import box
from rich.layout import Layout
from rich.columns import Columns
from rich.text import Text
from rich.align import Align
from rich.markdown import Markdown
from rich.traceback import install
from rich.live import Live
from rich.console import Group
from rich.syntax import Syntax

# Install rich traceback handler
install(show_locals=True)

console = Console()

# ===== ENTERPRISE CONFIGURATION =====
SESSION_NAME = "tg_enterprise_report_session"
LOG_FILE = Path("enterprise_report_log.json")
STATS_FILE = Path("enterprise_statistics.json")
AUDIT_LOG_FILE = Path("security_audit_trail.json")
CONFIG_FILE = Path("enterprise_config.json")
SCHEDULER_FILE = Path("scheduled_operations.json")
BLACKLIST_FILE = Path("enterprise_blacklist.json")
WHITELIST_FILE = Path("enterprise_whitelist.json")
TEMPLATE_FILE = Path("report_templates.json")
EXPORT_DIR = Path("exports")
SESSION_BACKUP_DIR = Path("session_backups")

# Create necessary directories
for directory in [EXPORT_DIR, SESSION_BACKUP_DIR]:
    directory.mkdir(exist_ok=True)

# SECURITY NOTICE: REPLACE WITH YOUR CREDENTIALS FROM https://my.telegram.org
API_ID = 27157163
API_HASH = "e0145db12519b08e1d2f5628e2db18c4"

# REQUIRED CHANNEL FOR SYSTEM ACCESS
REQUIRED_CHANNEL = "https://t.me/+HdWVx6n2C0U4ODU1"

class ReportPriority(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM" 
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"

class ReportStatus(Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    FLOOD_WAIT = "FLOOD_WAIT"
    RATE_LIMITED = "RATE_LIMITED"
    SECURITY_BLOCKED = "SECURITY_BLOCKED"
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"

class SecurityLevel(Enum):
    STANDARD = "STANDARD"
    ENHANCED = "ENHANCED"
    STRICT = "STRICT"
    PARANOID = "PARANOID"

class OperationMode(Enum):
    SINGLE = "SINGLE_TARGET"
    BATCH = "BATCH_PROCESSING"
    SCHEDULED = "SCHEDULED_OPERATIONS"
    MONITORING = "CONTINUOUS_MONITORING"
    AUTO = "AUTOMATED_RESPONSE"

# Enhanced reason mapping with detailed categories
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

PRIORITY_COLORS = {
    ReportPriority.LOW: "dim white",
    ReportPriority.MEDIUM: "yellow", 
    ReportPriority.HIGH: "red",
    ReportPriority.CRITICAL: "bold red",
    ReportPriority.EMERGENCY: "blink bold red"
}

PRIORITY_WEIGHTS = {
    ReportPriority.LOW: 1,
    ReportPriority.MEDIUM: 2,
    ReportPriority.HIGH: 4,
    ReportPriority.CRITICAL: 8,
    ReportPriority.EMERGENCY: 16
}

LINK_PATTERNS = [
    re.compile(r"https?://t\.me/(?P<user>[A-Za-z0-9_]+)/(?P<msg_id>\d+)$"),
    re.compile(r"https?://t\.me/c/(?P<chat_id>\d+)/(?P<msg_id>\d+)$"),
    re.compile(r"https?://t\.me/joinchat/(?P<invite>[A-Za-z0-9_-]+)$"),
]

# ===== ENTERPRISE BANNER FUNCTION =====
def create_enterprise_banner():
    """Create military-grade enterprise banner"""
    banner_lines = [
        "╔══════════════════════════════════════════════════════════════╗",
        "║ TELEGRAM ENTERPRISE REPORTING SYSTEM v4.0                   ║",
        "║ MILITARY-GRADE CONTENT MODERATION PLATFORM                  ║",
        f"║ Version 4.0.0 | Session ID: {stats.session_id}               ║",
        f"║ Security Level: {config.SECURITY_LEVEL.value}                  ║",
        f"║ Threat Level: {audit_system.threat_level}                         ║",
        f"║ Platform: {platform.system()} {platform.release()}           ║",
        f"║ Python {platform.python_version()} | Telethon {telethon_version.__version__} ║",
        "╚══════════════════════════════════════════════════════════════╝"
    ]
    
    for line in banner_lines:
        if "Session ID" in line:
            console.print(f"[bold bright_cyan]{line}[/bold bright_cyan]")
        elif "Security Level" in line:
            color = "green" if config.SECURITY_LEVEL.value == "STANDARD" else "yellow" if config.SECURITY_LEVEL.value == "ENHANCED" else "red"
            console.print(f"[bold {color}]{line}[/bold {color}]")
        elif "Threat Level" in line:
            color = "green" if audit_system.threat_level == "LOW" else "yellow" if audit_system.threat_level == "MEDIUM" else "red"
            console.print(f"[bold {color}]{line}[/bold {color}]")
        else:
            console.print(f"[bold bright_white]{line}[/bold bright_white]")
    
    system_info = Panel(
        Columns([
            f"[bright_white]Session:[/bright_white] [cyan]{SESSION_NAME}[/cyan]",
            f"[bright_white]API Status:[/bright_white] [green]OPERATIONAL[/green]",
            f"[bright_white]Security Level:[/bright_white] [yellow]{config.SECURITY_LEVEL.value}[/yellow]",
            f"[bright_white]Channel Access:[/bright_white] [magenta]MANDATORY[/magenta]"
        ]),
        style="bright_blue",
        box=box.ROUNDED
    )
    
    console.print("\n")
    console.print(system_info)
    console.print("\n")

# ===== ENHANCED ENTERPRISE CONFIGURATION CLASS =====
class EnterpriseConfig:
    """Enterprise-grade configuration with advanced security controls"""
    
    def __init__(self):
        # Rate Limiting
        self.MAX_REPORTS_PER_SESSION = 200
        self.MAX_REPORTS_PER_HOUR = 100
        self.MAX_REPORTS_PER_DAY = 500
        self.MAX_BATCH_SIZE = 50
        
        # Timing and Delays
        self.SAFETY_DELAY_SECONDS = 2.5
        self.MINIMUM_DELAY_SECONDS = 1.0
        self.MAXIMUM_DELAY_SECONDS = 10.0
        
        self.PRIORITY_DELAY_MULTIPLIERS = {
            ReportPriority.LOW: 1.8,
            ReportPriority.MEDIUM: 1.3,
            ReportPriority.HIGH: 1.0,
            ReportPriority.CRITICAL: 0.6,
            ReportPriority.EMERGENCY: 0.3
        }
        
        # Security Settings
        self.FLOOD_WAIT_THRESHOLD = 60  # seconds
        self.AUTO_RETRY_ATTEMPTS = 5
        self.SECURITY_LEVEL = SecurityLevel.ENHANCED
        self.SESSION_TIMEOUT_MINUTES = 180
        self.MAX_CONCURRENT_OPERATIONS = 3
        
        # Feature Toggles
        self.ENABLE_ADVANCED_LOGGING = True
        self.COMPREHENSIVE_STATISTICS = True
        self.ENABLE_AUDIT_TRAIL = True
        self.REQUIRE_CHANNEL_JOIN = True
        self.ENABLE_RATE_LIMITING = True
        self.ENABLE_SECURITY_CHECKS = True
        self.ENABLE_AUTO_RETRY = True
        self.ENABLE_BLACKLIST = True
        self.ENABLE_WHITELIST = True
        self.ENABLE_TEMPLATES = True
        self.ENABLE_SCHEDULING = True
        self.ENABLE_MONITORING = False
        self.AUTO_BACKUP_SESSIONS = True
        self.BACKUP_INTERVAL_MINUTES = 30
        
        # Monitoring Settings
        self.MONITORING_CHECK_INTERVAL = 300  # seconds
        self.MONITORING_MAX_TARGETS = 20
        
        # Export Settings
        self.AUTO_EXPORT_STATS = True
        self.EXPORT_FORMAT = "json"  # json, csv, both
        
        # Notification Settings
        self.ENABLE_NOTIFICATIONS = False
        self.NOTIFY_ON_EMERGENCY = True
        self.NOTIFY_ON_CRITICAL = True
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary with enum handling"""
        result = {}
        for k, v in self.__dict__.items():
            if isinstance(v, Enum):
                result[k] = v.value
            elif isinstance(v, dict):
                # Handle nested dictionaries with enum values
                converted_dict = {}
                for dict_k, dict_v in v.items():
                    if isinstance(dict_v, Enum):
                        converted_dict[dict_k.value if isinstance(dict_k, Enum) else dict_k] = dict_v.value
                    else:
                        converted_dict[dict_k.value if isinstance(dict_k, Enum) else dict_k] = dict_v
                result[k] = converted_dict
            else:
                result[k] = v
        return result
    
    def save_to_file(self):
        """Save configuration to file"""
        try:
            with CONFIG_FILE.open('w') as f:
                json.dump(self.to_dict(), f, indent=2)
            console.print(f"[green]Configuration saved to {CONFIG_FILE}[/green]")
        except Exception as e:
            console.print(f"[red]CONFIG SAVE FAILED: {e}[/red]")
    
    def load_from_file(self):
        """Load configuration from file"""
        try:
            if CONFIG_FILE.exists():
                with CONFIG_FILE.open('r') as f:
                    data = json.load(f)
                    for key, value in data.items():
                        if hasattr(self, key):
                            # Handle enum values
                            if key == 'SECURITY_LEVEL' and isinstance(value, str):
                                value = SecurityLevel[value]
                            elif key == 'EXPORT_FORMAT' and value not in ["json", "csv", "both"]:
                                value = "json"
                            elif key == 'PRIORITY_DELAY_MULTIPLIERS' and isinstance(value, dict):
                                # Convert string keys back to ReportPriority enums
                                converted_dict = {}
                                for k, v in value.items():
                                    try:
                                        enum_key = ReportPriority[k]
                                        converted_dict[enum_key] = v
                                    except:
                                        converted_dict[k] = v
                                value = converted_dict
                            setattr(self, key, value)
                console.print(f"[green]Configuration loaded from {CONFIG_FILE}[/green]")
        except Exception as e:
            console.print(f"[yellow]CONFIG LOAD WARNING: {e}[/yellow]")

config = EnterpriseConfig()
config.load_from_file()

# ===== ENHANCED ENTERPRISE STATISTICS CLASS =====
class EnterpriseStatistics:
    """Comprehensive enterprise statistics tracking with advanced analytics"""
    
    def __init__(self):
        self.session_id = hashlib.md5(f"{datetime.now()}{random.randint(1000, 9999)}".encode()).hexdigest()[:12]
        self.session_start = datetime.now()
        self.last_report_time = None
        self.last_backup_time = None
        
        # Core Statistics
        self.total_reports = 0
        self.successful_reports = 0
        self.failed_reports = 0
        self.flood_waits = 0
        self.rate_limited_requests = 0
        self.security_blocks = 0
        self.scheduled_reports = 0
        self.cancelled_reports = 0
        
        # Detailed Tracking
        self.reports_by_priority = {priority: 0 for priority in ReportPriority}
        self.reports_by_reason = {reason_id: 0 for reason_id in REASON_MAP.keys()}
        self.reports_by_hour = {i: 0 for i in range(24)}
        self.reports_by_day = {i: 0 for i in range(7)}  # 0=Monday
        self.reports_by_target_type = {"user": 0, "group": 0, "channel": 0, "bot": 0}
        
        # Performance Metrics
        self.total_report_time = 0
        self.average_report_time = 0
        self.min_report_time = float('inf')
        self.max_report_time = 0
        self.report_times = []
        
        # Failure Analysis
        self.consecutive_failures = 0
        self.max_consecutive_failures = 0
        self.failure_reasons = defaultdict(int)
        
        # Session Metrics
        self.session_operations = 0
        self.session_backups = 0
        self.session_exports = 0
        
        # System Metrics
        self.system_platform = platform.system()
        self.python_version = platform.python_version()
        self.telethon_version = telethon_version.__version__
        
    def update_report_stats(self, success: bool, report_time: float, priority: ReportPriority, 
                          reason_id: int = None, target_type: str = None, failure_reason: str = None):
        """Update comprehensive statistics"""
        self.total_reports += 1
        self.total_report_time += report_time
        self.report_times.append(report_time)
        
        # Update min/max times
        self.min_report_time = min(self.min_report_time, report_time)
        self.max_report_time = max(self.max_report_time, report_time)
        self.average_report_time = self.total_report_time / max(1, self.total_reports)
        
        if success:
            self.successful_reports += 1
            self.consecutive_failures = 0
        else:
            self.failed_reports += 1
            self.consecutive_failures += 1
            self.max_consecutive_failures = max(self.max_consecutive_failures, 
                                              self.consecutive_failures)
            if failure_reason:
                self.failure_reasons[failure_reason] += 1
        
        if priority:
            self.reports_by_priority[priority] += 1
        
        if reason_id:
            self.reports_by_reason[reason_id] += 1
        
        current_time = datetime.now()
        self.reports_by_hour[current_time.hour] += 1
        self.reports_by_day[current_time.weekday()] += 1
        
        if target_type:
            self.reports_by_target_type[target_type] += 1
        
        self.last_report_time = current_time
    
    def update_session_operation(self, operation_type: str):
        """Update session operation count"""
        self.session_operations += 1
    
    def get_success_rate(self) -> float:
        """Calculate success rate percentage"""
        if self.total_reports == 0:
            return 0.0
        return (self.successful_reports / self.total_reports) * 100
    
    def get_session_duration(self) -> timedelta:
        """Get current session duration"""
        return datetime.now() - self.session_start
    
    def get_reports_per_hour(self) -> float:
        """Calculate reports per hour"""
        duration_hours = self.get_session_duration().total_seconds() / 3600
        if duration_hours == 0:
            return 0.0
        return self.total_reports / duration_hours
    
    def get_performance_grade(self) -> str:
        """Calculate performance grade"""
        success_rate = self.get_success_rate()
        if success_rate >= 95:
            return "A+"
        elif success_rate >= 90:
            return "A"
        elif success_rate >= 85:
            return "B+"
        elif success_rate >= 80:
            return "B"
        elif success_rate >= 70:
            return "C"
        else:
            return "D"
    
    def get_std_dev_report_time(self) -> float:
        """Calculate standard deviation of report times"""
        if len(self.report_times) < 2:
            return 0.0
        mean = sum(self.report_times) / len(self.report_times)
        variance = sum((x - mean) ** 2 for x in self.report_times) / len(self.report_times)
        return math.sqrt(variance)
    
    def get_top_failure_reasons(self, n: int = 5) -> List[Tuple[str, int]]:
        """Get top n failure reasons"""
        return sorted(self.failure_reasons.items(), key=lambda x: x[1], reverse=True)[:n]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert statistics to dictionary with enum handling"""
        def convert_value(value):
            if isinstance(value, Enum):
                return value.value
            elif isinstance(value, datetime):
                return value.isoformat()
            elif isinstance(value, timedelta):
                return str(value)
            elif isinstance(value, defaultdict):
                return dict(value)
            return value
        
        result = {}
        for key, value in self.__dict__.items():
            if key.startswith('_'):
                continue
                
            if isinstance(value, dict):
                converted_dict = {}
                for k, v in value.items():
                    if isinstance(k, Enum):
                        k = k.value
                    converted_dict[k] = convert_value(v)
                result[key] = converted_dict
            else:
                result[key] = convert_value(value)
        
        # Add calculated fields
        result["success_rate_percentage"] = self.get_success_rate()
        result["performance_grade"] = self.get_performance_grade()
        result["session_duration_seconds"] = self.get_session_duration().total_seconds()
        result["reports_per_hour"] = self.get_reports_per_hour()
        result["std_dev_report_time"] = self.get_std_dev_report_time()
        result["top_failure_reasons"] = dict(self.get_top_failure_reasons(5))
        
        return result
    
    def export_to_file(self, format_type: str = "json"):
        """Export statistics to file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        data = self.to_dict()
        
        try:
            if format_type in ["json", "both"]:
                json_file = EXPORT_DIR / f"stats_{self.session_id}_{timestamp}.json"
                with json_file.open('w') as f:
                    json.dump(data, f, indent=2)
                console.print(f"[green]Statistics exported to {json_file}[/green]")
            
            if format_type in ["csv", "both"]:
                csv_file = EXPORT_DIR / f"stats_{self.session_id}_{timestamp}.csv"
                
                # Flatten the data for CSV
                flat_data = {}
                for key, value in data.items():
                    if isinstance(value, dict):
                        for sub_key, sub_value in value.items():
                            flat_data[f"{key}_{sub_key}"] = sub_value
                    else:
                        flat_data[key] = value
                
                with csv_file.open('w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=flat_data.keys())
                    writer.writeheader()
                    writer.writerow(flat_data)
                console.print(f"[green]Statistics exported to {csv_file}[/green]")
            
            self.session_exports += 1
            return True
            
        except Exception as e:
            console.print(f"[red]EXPORT FAILED: {e}[/red]")
            return False
    
    def save_to_file(self):
        """Save statistics to JSON file"""
        try:
            with STATS_FILE.open('w') as f:
                json.dump(self.to_dict(), f, indent=2)
        except Exception as e:
            console.print(f"[red]STATS SAVE FAILED: {e}[/red]")

stats = EnterpriseStatistics()

# ===== ENHANCED SECURITY AND AUDITING SYSTEM =====
class SecurityAudit:
    """Enterprise security audit system with threat detection"""
    
    def __init__(self):
        self.audit_entries = []
        self.suspicious_activities = 0
        self.threat_level = "LOW"
        self.activity_log = deque(maxlen=1000)  # Keep last 1000 activities
        self.ip_addresses = set()
        
    def log_event(self, event_type: str, severity: str, description: str, 
                 user: str = "SYSTEM", target: str = "N/A", metadata: Dict = None):
        """Log security event with comprehensive details"""
        event_id = hashlib.md5(f"{event_type}{description}{datetime.now()}{random.random()}".encode()).hexdigest()[:16]
        
        audit_entry = {
            "timestamp": datetime.now().isoformat(),
            "event_id": event_id,
            "event_type": event_type,
            "severity": severity,
            "user": user,
            "target": target,
            "description": description,
            "session_id": stats.session_id,
            "system_platform": platform.system(),
            "metadata": metadata or {}
        }
        
        self.audit_entries.append(audit_entry)
        self.activity_log.append(audit_entry)
        
        # Update threat level based on severity
        self._update_threat_level(severity)
        
        # Console output based on severity
        if severity == "CRITICAL":
            console.print(f"[blink bold red]🚨 CRITICAL SECURITY ALERT: {event_type} - {description}[/blink bold red]")
        elif severity == "HIGH":
            console.print(f"[bold red]⚠️ SECURITY ALERT: {event_type} - {description}[/bold red]")
        elif severity == "MEDIUM":
            console.print(f"[bold yellow]SECURITY EVENT: {event_type} - {description}[/bold yellow]")
        elif severity == "LOW":
            console.print(f"[dim]AUDIT: {event_type} - {description}[/dim]")
        else:
            console.print(f"[white]LOG: {event_type} - {description}[/white]")
        
        # Save to audit log
        self.save_audit_entry(audit_entry)
        
        # Check for suspicious patterns
        self._detect_suspicious_patterns()
    
    def _update_threat_level(self, severity: str):
        """Update system threat level"""
        severity_weights = {"LOW": 1, "MEDIUM": 3, "HIGH": 8, "CRITICAL": 15}
        weight = severity_weights.get(severity, 0)
        
        # Simple threat level calculation
        recent_critical = sum(1 for entry in list(self.activity_log)[-10:] 
                            if entry.get("severity") == "CRITICAL")
        
        if recent_critical >= 3:
            self.threat_level = "CRITICAL"
        elif recent_critical >= 1 or weight >= 8:
            self.threat_level = "HIGH"
        elif weight >= 3:
            self.threat_level = "MEDIUM"
        else:
            self.threat_level = "LOW"
    
    def _detect_suspicious_patterns(self):
        """Detect suspicious activity patterns"""
        recent_events = list(self.activity_log)[-20:]  # Last 20 events
        
        # Check for rapid-fire reports
        report_events = [e for e in recent_events if "REPORT" in e.get("event_type", "")]
        if len(report_events) > 10:
            self.suspicious_activities += 1
            self.log_event("SUSPICIOUS_PATTERN", "MEDIUM",
                         "Rapid-fire reporting pattern detected", metadata={"count": len(report_events)})
        
        # Check for multiple failures
        failure_events = [e for e in recent_events if "FAILED" in e.get("event_type", "")]
        if len(failure_events) > 5:
            self.suspicious_activities += 1
            self.log_event("SUSPICIOUS_PATTERN", "MEDIUM",
                         "Multiple consecutive failures detected", metadata={"count": len(failure_events)})
    
    def save_audit_entry(self, entry: Dict):
        """Save individual audit entry to file"""
        try:
            with AUDIT_LOG_FILE.open('a') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception as e:
            console.print(f"[red]AUDIT LOGGING FAILED: {e}[/red]")
    
    def get_security_report(self) -> Dict:
        """Generate security report"""
        recent_events = list(self.activity_log)[-100]  # Last 100 events
        
        critical_count = sum(1 for e in recent_events if e.get("severity") == "CRITICAL")
        high_count = sum(1 for e in recent_events if e.get("severity") == "HIGH")
        medium_count = sum(1 for e in recent_events if e.get("severity") == "MEDIUM")
        
        return {
            "threat_level": self.threat_level,
            "suspicious_activities": self.suspicious_activities,
            "total_audit_entries": len(self.audit_entries),
            "recent_critical": critical_count,
            "recent_high": high_count,
            "recent_medium": medium_count,
            "session_id": stats.session_id,
            "timestamp": datetime.now().isoformat()
        }
    
    def export_audit_log(self, format_type: str = "json"):
        """Export audit log to file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        try:
            if format_type in ["json", "both"]:
                json_file = EXPORT_DIR / f"audit_{stats.session_id}_{timestamp}.json"
                with json_file.open('w') as f:
                    json.dump(self.audit_entries, f, indent=2, default=str)
                console.print(f"[green]Audit log exported to {json_file}[/green]")
            
            return True
        except Exception as e:
            console.print(f"[red]AUDIT EXPORT FAILED: {e}[/red]")
            return False

audit_system = SecurityAudit()

# ===== ESSENTIAL FUNCTIONS FROM ORIGINAL CODE =====

def create_enterprise_progress() -> Progress:
    """Create enterprise-grade progress display"""
    return Progress(
        SpinnerColumn("dots", style="bright_yellow"),
        TextColumn("[bold bright_blue]{task.description}"),
        BarColumn(bar_width=40, style="bright_white", complete_style="bright_green", finished_style="bright_green"),
        TaskProgressColumn(style="bright_cyan"),
        TextColumn("•"),
        TextColumn("[bold bright_yellow]{task.completed}/{task.total}", style="dim"),
        TimeRemainingColumn(),
        console=console,
        transient=False
    )

def check_rate_limits() -> Tuple[bool, str]:
    """Check if rate limits would be exceeded"""
    current_time = datetime.now()
    
    # Check hourly limit
    hour_reports = stats.reports_by_hour[current_time.hour]
    if hour_reports >= config.MAX_REPORTS_PER_HOUR:
        return False, f"Hourly limit exceeded: {hour_reports}/{config.MAX_REPORTS_PER_HOUR}"
    
    # Check daily limit (approximate)
    today_reports = sum(stats.reports_by_hour.values())
    if today_reports >= config.MAX_REPORTS_PER_DAY:
        return False, f"Daily limit exceeded: {today_reports}/{config.MAX_REPORTS_PER_DAY}"
    
    # Check session limit
    if stats.total_reports >= config.MAX_REPORTS_PER_SESSION:
        return False, f"Session limit exceeded: {stats.total_reports}/{config.MAX_REPORTS_PER_SESSION}"
    
    return True, "Rate limits OK"

def create_advanced_reason_selection() -> Table:
    """Create enterprise-grade reason selection interface"""
    table = Table(
        title="REPORT CATEGORY SELECTION MATRIX",
        box=box.DOUBLE_EDGE,
        border_style="bright_yellow",
        header_style="bold bright_white"
    )
    
    table.add_column("ID", justify="center", style="bold cyan", width=4)
    table.add_column("CATEGORY", style="bright_white", width=28)
    table.add_column("PRIORITY", justify="center", width=10)
    table.add_column("RESPONSE TIME", style="dim", width=15)
    table.add_column("DESCRIPTION", style="dim", width=40)
    
    response_times = {
        ReportPriority.EMERGENCY: "IMMEDIATE",
        ReportPriority.CRITICAL: "WITHIN 30M",
        ReportPriority.HIGH: "WITHIN 2H",
        ReportPriority.MEDIUM: "WITHIN 24H", 
        ReportPriority.LOW: "WITHIN 7D"
    }
    
    for reason_id, (name, reason_class, priority, description) in REASON_MAP.items():
        priority_color = PRIORITY_COLORS[priority]
        truncated_desc = (description[:37] + '...') if len(description) > 40 else description
        table.add_row(
            str(reason_id),
            name,
            f"[{priority_color}]{priority.value}[/{priority_color}]",
            response_times[priority],
            truncated_desc
        )
    
    return table

def select_report_reason() -> Tuple:
    """Enhanced reason selection with comprehensive validation"""
    console.print(create_advanced_reason_selection())
    
    while True:
        try:
            choice = Prompt.ask("Enter report category identifier")
            if not choice.isdigit():
                console.print("[red]ERROR: Please enter a numeric identifier[/red]")
                continue
                
            reason_id = int(choice)
            
            if reason_id not in REASON_MAP:
                console.print("[red]ERROR: Invalid category identifier[/red]")
                continue
                
            name, reason_cls, priority, description = REASON_MAP[reason_id]
            
            # Comprehensive confirmation panel
            priority_color = PRIORITY_COLORS[priority]
            console.print(
                Panel.fit(
                    f"[bright_white]Category Identifier:[/bright_white] [cyan]{reason_id}[/cyan]\n"
                    f"[bright_white]Category Name:[/bright_white] [yellow]{name}[/yellow]\n"
                    f"[bright_white]Priority Level:[/bright_white] [{priority_color}]{priority.value}[/{priority_color}]\n"
                    f"[bright_white]Response Timeline:[/bright_white] {['IMMEDIATE', 'WITHIN 30M', 'WITHIN 2H', 'WITHIN 24H', 'WITHIN 7D'][list(ReportPriority).index(priority)]}\n"
                    f"[bright_white]Description:[/bright_white] [dim]{description}[/dim]",
                    border_style=priority_color,
                    title="CATEGORY SELECTION CONFIRMATION"
                )
            )
            
            if Confirm.ask("Confirm category selection?", default=True):
                return reason_cls(), priority, name, description
            else:
                console.print("[yellow]Category selection cancelled[/yellow]")
                continue
                
        except KeyboardInterrupt:
            raise
        except Exception as e:
            console.print(f"[red]SELECTION ERROR: {e}[/red]")
            continue

async def enterprise_authentication_flow(client: TelegramClient):
    """Enterprise-grade secure authentication flow"""
    if not await client.is_user_authorized():
        console.print(Panel.fit(
            "[bold yellow]ENTERPRISE AUTHENTICATION REQUIRED[/bold yellow]\n"
            "Secure authentication protocol initiated",
            border_style="yellow"
        ))
        
        phone = Prompt.ask("Enter Telegram phone number")
        
        if not phone:
            console.print("[red]ERROR: Phone number is required[/red]")
            return False
        
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]Initiating secure authentication..."),
                transient=True
            ) as progress:
                progress.add_task("auth_init")
                await client.send_code_request(phone)
            
            code = Prompt.ask("Enter verification code")
            
            if not code:
                console.print("[red]ERROR: Verification code is required[/red]")
                return False
            
            await client.sign_in(phone=phone, code=code)
            console.print("[green]AUTHENTICATION: Primary authentication successful[/green]")
            audit_system.log_event(
                "AUTH_SUCCESS", "MEDIUM",
                "Primary authentication completed",
                user=phone
            )
            return True
            
        except SessionPasswordNeededError:
            console.print("[yellow]SECURITY: Two-factor authentication required[/yellow]")
            password = Prompt.ask("Enter two-factor authentication password", password=True)
            
            if not password:
                console.print("[red]ERROR: Password is required[/red]")
                return False
                
            await client.sign_in(password=password)
            console.print("[green]AUTHENTICATION: Two-factor authentication successful[/green]")
            audit_system.log_event(
                "2FA_SUCCESS", "MEDIUM", 
                "Two-factor authentication completed",
                user=phone
            )
            return True
            
        except Exception as e:
            console.print(f"[red]AUTHENTICATION FAILED: {e}[/red]")
            return False
    
    return True

async def enterprise_channel_verification(client: TelegramClient) -> bool:
    """Enhanced channel verification with security checks"""
    try:
        console.print(Panel.fit(
            "[bold yellow]CHANNEL VERIFICATION REQUIRED[/bold yellow]\n"
            "Mandatory channel membership for system access",
            border_style="yellow"
        ))
        
        # Extract channel entity
        channel_entity = await client.get_entity(REQUIRED_CHANNEL)
        channel_name = getattr(channel_entity, 'title', 'Unknown Channel')
        channel_id = getattr(channel_entity, 'id', 'N/A')
        
        audit_system.log_event(
            "CHANNEL_VERIFICATION_START", "LOW",
            f"Initiating channel verification: {channel_name}",
            metadata={"channel_id": channel_id, "channel_name": channel_name}
        )
        
        # Check current participation status
        try:
            participant = await client.get_participants(channel_entity, limit=1)
            if participant:
                console.print(f"[green]VERIFIED: Already joined channel: {channel_name}[/green]")
                audit_system.log_event(
                    "CHANNEL_VERIFICATION_SUCCESS", "LOW",
                    f"Channel membership verified: {channel_name}"
                )
                return True
        except ChannelPrivateError:
            # Not a participant, proceed to join
            pass
        except Exception as e:
            console.print(f"[yellow]PARTICIPANT CHECK WARNING: {e}[/yellow]")
        
        # Display channel information
        console.print(Panel.fit(
            f"[bright_white]Channel Name:[/bright_white] [cyan]{channel_name}[/cyan]\n"
            f"[bright_white]Channel ID:[/bright_white] [dim]{channel_id}[/dim]\n"
            f"[bright_white]Access Link:[/bright_white] [dim]{REQUIRED_CHANNEL}[/dim]\n"
            f"[bold yellow]Channel membership is mandatory for system operation[/bold yellow]",
            border_style="cyan",
            title="REQUIRED CHANNEL ACCESS"
        ))
        
        if Confirm.ask("Proceed with automatic channel join?", default=True):
            try:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[bold blue]Executing channel join operation..."),
                    transient=True
                ) as progress:
                    progress.add_task("channel_join")
                    await client(JoinChannelRequest(channel_entity))
                
                console.print(f"[green]SUCCESS: Joined channel: {channel_name}[/green]")
                
                # Verification with retry logic
                await asyncio.sleep(3)
                for attempt in range(3):
                    try:
                        participant = await client.get_participants(channel_entity, limit=1)
                        if participant:
                            console.print("[green]VERIFICATION: Channel access confirmed[/green]")
                            audit_system.log_event(
                                "CHANNEL_JOIN_SUCCESS", "MEDIUM",
                                f"Successfully joined and verified: {channel_name}"
                            )
                            return True
                    except ChannelPrivateError:
                        if attempt < 2:
                            await asyncio.sleep(2)
                            continue
                    except Exception as e:
                        console.print(f"[yellow]Verification attempt {attempt + 1} failed: {e}[/yellow]")
                        if attempt < 2:
                            await asyncio.sleep(2)
                
                console.print("[yellow]WARNING: Automatic verification incomplete[/yellow]")
                return Confirm.ask("Confirm manual channel join completion?", default=True)
            
            except Exception as e:
                console.print(f"[red]CHANNEL JOIN FAILED: {e}[/red]")
                return Confirm.ask("Join channel manually and confirm?", default=True)
        
        else:
            console.print(Panel.fit(
                f"[red]ACCESS DENIED[/red]\n"
                f"Channel membership required for system access:\n"
                f"[cyan]{REQUIRED_CHANNEL}[/cyan]",
                border_style="red"
            ))
            return False
            
    except Exception as e:
        console.print(f"[red]CHANNEL VERIFICATION FAILED: {e}[/red]")
        audit_system.log_event(
            "CHANNEL_VERIFICATION_FAILED", "HIGH",
            f"Channel verification error: {e}",
            metadata={"error": str(e)}
        )
        console.print(f"[yellow]Manual join required: {REQUIRED_CHANNEL}[/yellow]")
        return Confirm.ask("Confirm channel join completion?", default=True)

async def execute_enterprise_report(client, request_func, description: str, 
                                  count: int, priority: ReportPriority) -> Dict[str, Any]:
    """Enterprise-grade reporting execution with comprehensive tracking"""
    
    results = {
        "sent": 0,
        "failed": 0,
        "flood_waits": 0,
        "rate_limited": 0,
        "security_blocked": 0,
        "total_time": 0,
        "individual_times": [],
        "errors": []
    }
    
    start_time = time.time()
    
    # Pre-execution rate limit check
    rate_ok, rate_msg = check_rate_limits()
    if not rate_ok:
        console.print(f"[red]RATE LIMIT EXCEEDED: {rate_msg}[/red]")
        results["rate_limited"] = count
        stats.rate_limited_requests += count
        return results
    
    with create_enterprise_progress() as progress:
        task = progress.add_task(
            f"[bright_white]EXECUTING {priority.value} PRIORITY REPORTS...[/bright_white]", 
            total=count
        )
        
        for i in range(count):
            report_start = time.time()
            
            try:
                # Adaptive delay based on priority and security level
                base_delay = config.SAFETY_DELAY_SECONDS
                priority_multiplier = config.PRIORITY_DELAY_MULTIPLIERS[priority]
                security_multiplier = 1.0
                
                if config.SECURITY_LEVEL == SecurityLevel.STRICT:
                    security_multiplier = 1.3
                elif config.SECURITY_LEVEL == SecurityLevel.PARANOID:
                    security_multiplier = 1.7
                
                adaptive_delay = base_delay * priority_multiplier * security_multiplier
                
                # Only delay between reports, not before first one
                if i > 0:
                    await asyncio.sleep(adaptive_delay)
                
                # Execute report request
                res = await client(request_func)
                report_time = time.time() - report_start
                
                results["sent"] += 1
                results["individual_times"].append(report_time)
                stats.update_report_stats(True, report_time, priority)
                
                progress.update(task, advance=1, 
                              description=f"[green]SUCCESS: Report {i+1}/{count} Completed[/green]")
                
                audit_system.log_event(
                    "REPORT_SENT", "LOW",
                    f"Report {i+1} completed successfully",
                    target=description,
                    metadata={"report_time": report_time, "priority": priority.value}
                )
                
            except FloodWaitError as fw:
                results["flood_waits"] += 1
                stats.flood_waits += 1
                stats.update_report_stats(False, time.time() - report_start, priority)
                
                if fw.seconds > config.FLOOD_WAIT_THRESHOLD:
                    console.print(f"\n[red]CRITICAL FLOOD WAIT DETECTED: {fw.seconds} seconds[/red]")
                    results["errors"].append(f"FloodWait: {fw.seconds}s")
                    audit_system.log_event(
                        "FLOOD_WAIT_CRITICAL", "HIGH",
                        f"Critical flood wait encountered: {fw.seconds}s",
                        target=description
                    )
                    break
                else:
                    console.print(f"\n[yellow]Flood wait encountered: {fw.seconds}s - Implementing retry protocol[/yellow]")
                    await asyncio.sleep(fw.seconds)
                    # Retry the same report
                    continue
                    
            except Exception as e:
                results["failed"] += 1
                stats.update_report_stats(False, time.time() - report_start, priority)
                error_msg = f"Report {i+1} execution failed: {e}"
                results["errors"].append(error_msg)
                
                console.print(f"\n[red]EXECUTION ERROR: {error_msg}[/red]")
                audit_system.log_event(
                    "REPORT_FAILED", "MEDIUM",
                    f"Report execution failed: {e}",
                    target=description,
                    metadata={"error": str(e), "attempt": i+1}
                )
                
                # Security block detection
                if "security" in str(e).lower() or "block" in str(e).lower():
                    results["security_blocked"] += 1
                    stats.security_blocks += 1
                
                # Continue with next report instead of breaking
                continue
    
    results["total_time"] = time.time() - start_time
    return results

async def execute_peer_reporting_flow(client: TelegramClient):
    """Enterprise-grade peer reporting execution flow"""
    console.print(Panel.fit(
        "[bold bright_white]ENTERPRISE PEER REPORTING MODE[/bold bright_white]\n"
        "Comprehensive reporting for users, groups, channels, and bots",
        border_style="bright_blue"
    ))
    
    target = Prompt.ask("Enter target identifier (username or Telegram link)").strip()
    
    if not target:
        console.print("[red]ERROR: Target identifier is required[/red]")
        return
    
    # Security validation
    if config.ENABLE_SECURITY_CHECKS:
        security_ok, security_msg, analysis = await perform_enhanced_security_checks(client, target)
        if not security_ok:
            console.print(f"[red]SECURITY VALIDATION FAILED: {security_msg}[/red]")
            audit_system.log_event(
                "SECURITY_VALIDATION_FAILED", "HIGH",
                f"Target validation failed: {security_msg}",
                target=target,
                metadata=analysis
            )
            if not Confirm.ask("Override security check and proceed?", default=False):
                return
    
    try:
        reason_cls, priority, reason_name, reason_desc = select_report_reason()
    except KeyboardInterrupt:
        console.print("[yellow]Operation cancelled by user[/yellow]")
        return
    
    investigation_notes = Prompt.ask(
        "Enter investigation notes for audit trail", 
        default=f"Enterprise report - {reason_name} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    
    try:
        count = IntPrompt.ask(
            "Enter number of report instances", 
            default=1
        )
        count = max(1, min(count, config.MAX_REPORTS_PER_SESSION))
    except:
        count = 1
    
    # Comprehensive confirmation panel
    confirmation_panel = Panel.fit(
        f"[bright_white]Target Identifier:[/bright_white] [cyan]{target}[/cyan]\n"
        f"[bright_white]Report Category:[/bright_white] [yellow]{reason_name}[/yellow]\n"
        f"[bright_white]Category Description:[/bright_white] [dim]{reason_desc}[/dim]\n"
        f"[bright_white]Priority Level:[/bright_white] [{PRIORITY_COLORS[priority]}]{priority.value}[/{PRIORITY_COLORS[priority]}]\n"
        f"[bright_white]Investigation Notes:[/bright_white] [dim]{investigation_notes}[/dim]\n"
        f"[bright_white]Report Instances:[/bright_white] [bright_white]{count}[/bright_white]\n"
        f"[bright_white]Security Level:[/bright_white] [yellow]{config.SECURITY_LEVEL.value}[/yellow]",
        border_style="bright_yellow",
        title="ENTERPRISE OPERATION CONFIRMATION"
    )
    console.print(confirmation_panel)
    
    if not Confirm.ask("Execute enterprise reporting operation?", default=True):
        console.print("[dim]Operation cancelled by user[/dim]")
        audit_system.log_event(
            "OPERATION_CANCELLED", "LOW",
            "User cancelled reporting operation",
            target=target
        )
        return

    try:
        entity = await client.get_entity(target)
        request = ReportPeerRequest(peer=entity, reason=reason_cls, message=investigation_notes)
        
        operation_description = f"ENTERPRISE_PEER_REPORT | target={target} | category={reason_name} | priority={priority.value} | instances={count}"
        
        audit_system.log_event(
            "OPERATION_START", "MEDIUM",
            f"Initiating enterprise reporting operation",
            target=target,
            metadata={
                "category": reason_name,
                "priority": priority.value,
                "instances": count,
                "notes": investigation_notes
            }
        )
        
        results = await execute_enterprise_report(client, request, operation_description, count, priority)
        
        # Update comprehensive statistics
        stats.total_reports += count
        stats.reports_by_priority[priority] += count
        reason_id = [k for k, v in REASON_MAP.items() if v[0] == reason_name][0]
        stats.reports_by_reason[reason_id] += count
        
        # Display summary
        display_enterprise_summary(results, operation_description)
        
        audit_system.log_event(
            "OPERATION_COMPLETE", "MEDIUM",
            f"Enterprise reporting operation completed",
            target=target,
            metadata={
                "results": results,
                "category": reason_name,
                "priority": priority.value
            }
        )
        
    except Exception as e:
        console.print(f"[red]ENTERPRISE OPERATION FAILED: {e}[/red]")
        stats.failed_reports += count
        audit_system.log_event(
            "OPERATION_FAILED", "HIGH",
            f"Enterprise operation failed: {e}",
            target=target,
            metadata={"error": str(e), "instances": count}
        )

def display_enterprise_summary(results: Dict[str, Any], description: str):
    """Display comprehensive enterprise execution summary"""
    
    summary_table = Table(
        title="ENTERPRISE EXECUTION SUMMARY",
        box=box.ROUNDED,
        border_style="green",
        show_header=True,
        header_style="bold bright_white"
    )
    
    summary_table.add_column("METRIC", style="cyan", width=20)
    summary_table.add_column("VALUE", style="bright_white", justify="center", width=15)
    summary_table.add_column("STATUS", justify="center", width=15)
    summary_table.add_column("PERFORMANCE", width=20)
    
    success_rate = (results["sent"] / max(1, results["sent"] + results["failed"])) * 100
    avg_time = sum(results["individual_times"]) / max(1, len(results["individual_times"]))
    reports_per_min = (results["sent"] / max(1, results["total_time"] / 60))
    
    status_icon = "OPTIMAL" if success_rate > 95 else "ACCEPTABLE" if success_rate > 80 else "DEGRADED"
    performance_rating = "EXCELLENT" if reports_per_min > 10 else "GOOD" if reports_per_min > 5 else "MODERATE"
    
    summary_table.add_row("Total Executed", str(results["sent"]), status_icon, performance_rating)
    summary_table.add_row("Failed Executions", str(results["failed"]), "MONITORED", "REVIEW REQUIRED" if results["failed"] > 0 else "OPTIMAL")
    summary_table.add_row("Flood Waits", str(results["flood_waits"]), "CONTROLLED", "MANAGED" if results["flood_waits"] > 0 else "CLEAN")
    summary_table.add_row("Rate Limited", str(results["rate_limited"]), "BLOCKED" if results["rate_limited"] > 0 else "CLEAR", "SYSTEM LIMIT")
    summary_table.add_row("Security Blocks", str(results["security_blocked"]), "ALERT" if results["security_blocked"] > 0 else "SECURE", "MONITORED")
    summary_table.add_row("Total Duration", f"{results['total_time']:.2f}s", "COMPLETED", f"{reports_per_min:.1f}/min")
    summary_table.add_row("Average Time/Report", f"{avg_time:.2f}s", "EFFICIENT", "ANALYZED")
    summary_table.add_row("Success Rate", f"{success_rate:.1f}%", "ACHIEVED", "CALCULATED")
    
    console.print(Panel(summary_table, border_style="bright_green"))
    
    # Error details if any
    if results["errors"]:
        error_table = Table(title="ERROR DETAILS", box=box.SIMPLE, border_style="red")
        error_table.add_column("Error", style="red")
        for error in results["errors"][:5]:  # Show first 5 errors
            error_table.add_row(error)
        if len(results["errors"]) > 5:
            error_table.add_row(f"... and {len(results['errors']) - 5} more errors")
        console.print(error_table)

# ===== NEW ENHANCED FUNCTIONS =====

async def perform_enhanced_security_checks(client: TelegramClient, target: str) -> Tuple[bool, str, Dict]:
    """Perform comprehensive security checks with detailed analysis"""
    
    try:
        entity = await client.get_entity(target)
        analysis = {
            "type": type(entity).__name__,
            "id": getattr(entity, 'id', 'N/A'),
            "title": getattr(entity, 'title', 'N/A'),
            "username": getattr(entity, 'username', 'N/A'),
            "verified": getattr(entity, 'verified', False),
            "bot": getattr(entity, 'bot', False),
            "scam": getattr(entity, 'scam', False),
            "fake": getattr(entity, 'fake', False),
            "premium": getattr(entity, 'premium', False)
        }
        
        # Bot check
        if isinstance(entity, User) and entity.bot:
            return False, "Target is a bot - reporting not applicable", analysis
        
        # Scam/fake account check
        if hasattr(entity, 'scam') and entity.scam:
            analysis["risk_level"] = "HIGH"
            console.print("[yellow]SECURITY NOTE: Target is marked as scam[/yellow]")
        
        if hasattr(entity, 'fake') and entity.fake:
            analysis["risk_level"] = "HIGH"
            console.print("[yellow]SECURITY NOTE: Target is marked as fake[/yellow]")
        
        return True, "Security checks passed", analysis
        
    except Exception as e:
        return False, f"Security validation failed: {e}", {}

def display_enhanced_statistics():
    """Display enterprise-grade statistics dashboard"""
    
    # Performance metrics
    success_rate = stats.get_success_rate()
    performance_grade = stats.get_performance_grade()
    session_duration = stats.get_session_duration()
    
    # Main statistics table
    stats_table = Table(
        title=f"ENTERPRISE STATISTICS DASHBOARD | Grade: {performance_grade}",
        box=box.ROUNDED,
        border_style="bright_blue",
        header_style="bold bright_white"
    )
    
    stats_table.add_column("METRIC", style="cyan", width=20)
    stats_table.add_column("VALUE", style="bright_white", justify="center", width=15)
    stats_table.add_column("TREND", style="dim", width=12)
    stats_table.add_column("STATUS", width=10)
    
    status_color = "green" if success_rate > 90 else "yellow" if success_rate > 75 else "red"
    
    stats_table.add_row("Total Reports", str(stats.total_reports), "ANALYZING", "[cyan]ACTIVE[/cyan]")
    stats_table.add_row("Success Rate", f"[{status_color}]{success_rate:.1f}%[/{status_color}]", "MONITORED", f"[{status_color}]{performance_grade}[/{status_color}]")
    stats_table.add_row("Session Duration", str(session_duration).split('.')[0], "CONTINUOUS", "[green]ACTIVE[/green]")
    stats_table.add_row("Reports/Hour", f"{stats.get_reports_per_hour():.1f}", "OPTIMIZING", "[yellow]EFFICIENT[/yellow]")
    stats_table.add_row("Avg Time/Report", f"{stats.average_report_time:.2f}s", "STABLE", "[green]FAST[/green]" if stats.average_report_time < 3 else "[yellow]MODERATE[/yellow]")
    stats_table.add_row("Consecutive Failures", str(stats.consecutive_failures), "WATCHING", "[green]OK[/green]" if stats.consecutive_failures < 3 else "[red]ALERT[/red]")
    
    # Priority distribution
    priority_table = Table(
        title="PRIORITY DISTRIBUTION",
        box=box.SIMPLE,
        show_header=True,
        header_style="bold yellow"
    )
    priority_table.add_column("Priority", style="bright_white")
    priority_table.add_column("Count", justify="center")
    priority_table.add_column("Percentage", justify="center")
    
    for priority, count in stats.reports_by_priority.items():
        if count > 0:
            percentage = (count / stats.total_reports * 100) if stats.total_reports > 0 else 0
            priority_color = PRIORITY_COLORS[priority]
            priority_table.add_row(
                f"[{priority_color}]{priority.value}[/{priority_color}]",
                str(count),
                f"{percentage:.1f}%"
            )
    
    console.print(Columns([stats_table, priority_table]))
    
    # Failure analysis if any failures
    if stats.failed_reports > 0:
        failure_table = Table(
            title="FAILURE ANALYSIS",
            box=box.SIMPLE,
            show_header=True,
            header_style="bold red"
        )
        failure_table.add_column("Reason", style="red")
        failure_table.add_column("Count", justify="center")
        
        for reason, count in stats.get_top_failure_reasons(3):
            failure_table.add_row(reason[:40], str(count))
        
        console.print(failure_table)
    
    console.print("\n")

async def backup_session(client: TelegramClient):
    """Backup current session"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = SESSION_BACKUP_DIR / f"session_{stats.session_id}_{timestamp}.backup"
        
        # Copy session file
        session_file = Path(f"{SESSION_NAME}.session")
        if session_file.exists():
            shutil.copy2(session_file, backup_file)
            
            stats.session_backups += 1
            stats.last_backup_time = datetime.now()
            
            console.print(f"[green]Session backed up to {backup_file}[/green]")
            audit_system.log_event(
                "SESSION_BACKUP", "LOW",
                f"Session backup created: {backup_file.name}"
            )
            
            # Clean old backups (keep last 5)
            backup_files = sorted(SESSION_BACKUP_DIR.glob("*.backup"))
            if len(backup_files) > 5:
                for old_backup in backup_files[:-5]:
                    old_backup.unlink()
                    console.print(f"[dim]Removed old backup: {old_backup.name}[/dim]")
                    
    except Exception as e:
        console.print(f"[red]Session backup failed: {e}[/red]")

# ===== SIMPLIFIED NEW MODULES =====

async def batch_reporting_flow(client: TelegramClient):
    """Simplified batch reporting for multiple targets"""
    console.print(Panel.fit(
        "[bold bright_white]BATCH REPORTING (SIMPLIFIED)[/bold bright_white]\n"
        "Process multiple targets with unified settings",
        border_style="bright_cyan"
    ))
    
    console.print("[yellow]This feature is under development[/yellow]")
    console.print("[dim]Coming in the next update...[/dim]")

async def template_based_reporting_flow(client: TelegramClient):
    """Simplified template reporting"""
    console.print(Panel.fit(
        "[bold bright_white]TEMPLATE REPORTING (SIMPLIFIED)[/bold bright_white]",
        border_style="bright_magenta"
    ))
    
    console.print("[yellow]This feature is under development[/yellow]")
    console.print("[dim]Coming in the next update...[/dim]")

async def scheduled_operations_flow(client: TelegramClient):
    """Simplified scheduled operations"""
    console.print(Panel.fit(
        "[bold bright_white]SCHEDULED OPERATIONS (SIMPLIFIED)[/bold bright_white]",
        border_style="bright_yellow"
    ))
    
    console.print("[yellow]This feature is under development[/yellow]")
    console.print("[dim]Coming in the next update...[/dim]")

async def list_management_flow():
    """Simplified list management"""
    console.print(Panel.fit(
        "[bold bright_white]LIST MANAGEMENT (SIMPLIFIED)[/bold bright_white]",
        border_style="bright_cyan"
    ))
    
    console.print("[yellow]This feature is under development[/yellow]")
    console.print("[dim]Coming in the next update...[/dim]")

async def system_configuration_flow():
    """Simplified system configuration"""
    console.print(Panel.fit(
        "[bold bright_white]SYSTEM CONFIGURATION[/bold bright_white]",
        border_style="bright_magenta"
    ))
    
    while True:
        # Display current configuration
        config_table = Table(
            title="CURRENT CONFIGURATION",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan"
        )
        
        config_table.add_column("Setting", style="bright_white", width=30)
        config_table.add_column("Value", style="cyan", width=20)
        config_table.add_column("Description", style="dim", width=40)
        
        # Add key settings
        key_settings = [
            ("SECURITY_LEVEL", config.SECURITY_LEVEL.value, "System security posture"),
            ("MAX_REPORTS_PER_HOUR", config.MAX_REPORTS_PER_HOUR, "Rate limiting threshold"),
            ("SAFETY_DELAY_SECONDS", config.SAFETY_DELAY_SECONDS, "Delay between reports"),
            ("REQUIRE_CHANNEL_JOIN", config.REQUIRE_CHANNEL_JOIN, "Mandatory channel membership"),
            ("AUTO_BACKUP_SESSIONS", config.AUTO_BACKUP_SESSIONS, "Automatic session backups"),
        ]
        
        for setting, value, desc in key_settings:
            config_table.add_row(setting, str(value), desc)
        
        console.print(config_table)
        
        # Simple menu
        console.print("\n[bold]Configuration Options:[/bold]")
        console.print("  1. Save configuration")
        console.print("  0. Back to main menu")
        
        choice = Prompt.ask("Select option", choices=["1", "0"])
        
        if choice == "1":
            config.save_to_file()
            console.print("[green]Configuration saved[/green]")
        elif choice == "0":
            break

async def export_data_flow():
    """Simplified data export"""
    console.print(Panel.fit(
        "[bold bright_white]DATA EXPORT[/bold bright_white]",
        border_style="bright_green"
    ))
    
    console.print("[dim]Exporting current statistics...[/dim]")
    stats.export_to_file(config.EXPORT_FORMAT)
    console.print("[green]Data exported successfully[/green]")
    
    audit_system.log_event(
        "DATA_EXPORTED", "LOW",
        "System data exported"
    )

async def security_dashboard_flow():
    """Simplified security dashboard"""
    console.print(Panel.fit(
        "[bold bright_white]SECURITY DASHBOARD[/bold bright_white]",
        border_style="bright_red"
    ))
    
    # Get security report
    security_report = audit_system.get_security_report()
    
    # Threat level indicator
    threat_level = security_report["threat_level"]
    threat_color = "green" if threat_level == "LOW" else "yellow" if threat_level == "MEDIUM" else "red"
    
    threat_panel = Panel.fit(
        f"[bold bright_white]CURRENT THREAT LEVEL:[/bold bright_white] [{threat_color}]{threat_level}[/{threat_color}]\n"
        f"[dim]Security Events: {security_report['total_audit_entries']}[/dim]\n"
        f"[dim]Suspicious Activities: {security_report['suspicious_activities']}[/dim]",
        border_style=threat_color,
        title="SECURITY STATUS"
    )
    
    console.print(threat_panel)
    
    # Recent security events
    recent_events = list(audit_system.activity_log)[-5:]  # Last 5 events
    
    if recent_events:
        events_table = Table(
            title="RECENT SECURITY EVENTS",
            box=box.SIMPLE,
            show_header=True,
            header_style="bold yellow"
        )
        
        events_table.add_column("Time", style="dim", width=8)
        events_table.add_column("Type", style="bright_white", width=15)
        events_table.add_column("Severity", width=8)
        
        for event in reversed(recent_events):
            time_str = datetime.fromisoformat(event["timestamp"]).strftime("%H:%M:%S")
            severity = event["severity"]
            severity_color = "red" if severity in ["CRITICAL", "HIGH"] else "yellow" if severity == "MEDIUM" else "green"
            
            events_table.add_row(
                time_str,
                event["event_type"][:15],
                f"[{severity_color}]{severity}[/{severity_color}]"
            )
        
        console.print(events_table)
    
    console.print("\n[dim]Press Enter to continue...[/dim]")
    input()

# ===== UPDATED MAIN EXECUTION FLOW =====

async def main():
    """Main enterprise execution flow"""
    create_enterprise_banner()
    
    # Initialize enterprise client
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    
    try:
        await client.start()
        
        # Authenticate user
        auth_success = await enterprise_authentication_flow(client)
        if not auth_success:
            console.print("[red]AUTHENTICATION FAILED - System shutdown[/red]")
            return
        
        # Enterprise channel verification
        if config.REQUIRE_CHANNEL_JOIN:
            channel_verified = await enterprise_channel_verification(client)
            if not channel_verified:
                console.print(Panel.fit(
                    "[red]ENTERPRISE ACCESS DENIED[/red]\n"
                    "Mandatory channel membership not verified.\n"
                    f"Required channel: [cyan]{REQUIRED_CHANNEL}[/cyan]",
                    border_style="red"
                ))
                audit_system.log_event(
                    "ACCESS_DENIED", "HIGH",
                    "Channel verification failed - System access denied"
                )
                return
        
        console.print(Panel.fit(
            "[green]ENTERPRISE ACCESS GRANTED[/green]\n"
            "All security validations passed\n"
            "Full system capabilities enabled",
            border_style="bright_green"
        ))
        
        audit_system.log_event(
            "SYSTEM_READY", "LOW",
            "Enterprise system initialized and ready for operations"
        )
        
        # Initial backup
        if config.AUTO_BACKUP_SESSIONS:
            await backup_session(client)
        
        # Main operation loop
        while True:
            display_enhanced_statistics()
            
            # Enhanced control panel
            control_table = Table(show_header=False, box=box.ROUNDED, border_style="cyan")
            control_table.add_column("OPTION", style="bold green", justify="center", width=4)
            control_table.add_column("MODULE", style="bright_white", width=25)
            control_table.add_column("DESCRIPTION", style="dim", width=45)
            
            control_table.add_row("1", "SINGLE TARGET REPORTING", "Comprehensive reporting for individual targets")
            control_table.add_row("2", "BATCH REPORTING", "Process multiple targets (Coming Soon)")
            control_table.add_row("3", "TEMPLATE REPORTING", "Use pre-configured templates (Coming Soon)")
            control_table.add_row("4", "SCHEDULED OPERATIONS", "Schedule reports (Coming Soon)")
            control_table.add_row("5", "LIST MANAGEMENT", "Manage lists (Coming Soon)")
            control_table.add_row("6", "STATISTICS ANALYTICS", "Detailed session analytics")
            control_table.add_row("7", "SECURITY DASHBOARD", "Security audit and monitoring")
            control_table.add_row("8", "SYSTEM CONFIGURATION", "Enterprise configuration")
            control_table.add_row("9", "DATA EXPORT", "Export system data")
            control_table.add_row("0", "SYSTEM SHUTDOWN", "Secure session termination")
            
            console.print(Panel(control_table, title="ENTERPRISE CONTROL PANEL v4.0", border_style="bright_blue"))
            
            choice = Prompt.ask("Select enterprise module", 
                              choices=["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"])
            
            if choice == "1":
                await execute_peer_reporting_flow(client)
            elif choice == "2":
                await batch_reporting_flow(client)
            elif choice == "3":
                await template_based_reporting_flow(client)
            elif choice == "4":
                await scheduled_operations_flow(client)
            elif choice == "5":
                await list_management_flow()
            elif choice == "6":
                display_enhanced_statistics()
                continue
            elif choice == "7":
                await security_dashboard_flow()
            elif choice == "8":
                await system_configuration_flow()
            elif choice == "9":
                await export_data_flow()
            elif choice == "0":
                console.print("[dim]Initiating secure shutdown sequence...[/dim]")
                break
                
            # Session continuation check
            if not Confirm.ask("Continue enterprise operations?", default=True):
                console.print("[dim]Initiating operation termination...[/dim]")
                break
                
            # Security check for prolonged sessions
            session_duration = stats.get_session_duration()
            if session_duration.total_seconds() > config.SESSION_TIMEOUT_MINUTES * 60:
                console.print("[yellow]SECURITY NOTICE: Session duration limit approaching[/yellow]")
                if not Confirm.ask("Extend session duration?", default=False):
                    break
                
    except Exception as e:
        console.print(f"[red]ENTERPRISE SYSTEM FAILURE: {e}[/red]")
        audit_system.log_event(
            "SYSTEM_FAILURE", "HIGH",
            f"Enterprise system critical failure: {e}",
            metadata={"error": str(e)}
        )
    
    finally:
        # Enterprise session conclusion
        try:
            session_duration = stats.get_session_duration()
            success_rate = stats.get_success_rate()
            
            # Final backup
            if config.AUTO_BACKUP_SESSIONS:
                await backup_session(client)
            
            # Final export if enabled
            if config.AUTO_EXPORT_STATS:
                stats.export_to_file(config.EXPORT_FORMAT)
            
            console.print(Panel.fit(
                f"[green]ENTERPRISE SESSION TERMINATED[/green]\n"
                f"Session ID: [bright_white]{stats.session_id}[/bright_white]\n"
                f"Total Operations: [bright_white]{stats.total_reports}[/bright_white]\n"
                f"Success Rate: [bright_white]{success_rate:.1f}%[/bright_white]\n"
                f"Performance Grade: [bright_white]{stats.get_performance_grade()}[/bright_white]\n"
                f"Session Duration: [bright_white]{session_duration}[/bright_white]\n"
                f"Security Events: [bright_white]{len(audit_system.audit_entries)}[/bright_white]\n"
                f"Threat Level: [bright_white]{audit_system.threat_level}[/bright_white]",
                border_style="bright_green",
                title="ENTERPRISE SESSION SUMMARY"
            ))
            
            # Save final statistics and configuration
            stats.save_to_file()
            config.save_to_file()
            
            audit_system.log_event(
                "SESSION_TERMINATED", "LOW",
                f"Enterprise session completed - Duration: {session_duration}"
            )
            
            await client.disconnect()
            
        except Exception as e:
            console.print(f"[red]SHUTDOWN ERROR: {e}[/red]")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[dim]ENTERPRISE SESSION: User initiated emergency shutdown[/dim]")
        audit_system.log_event(
            "EMERGENCY_SHUTDOWN", "HIGH",
            "User initiated emergency shutdown via keyboard interrupt"
        )
    except Exception as e:
        console.print(f"\n[red]ENTERPRISE CRITICAL FAILURE: {e}[/red]")
        audit_system.log_event(
            "CRITICAL_FAILURE", "HIGH",
            f"Enterprise system critical failure: {e}",
            metadata={"error": str(e)}
        )
