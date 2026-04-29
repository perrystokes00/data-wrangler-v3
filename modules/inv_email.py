"""
modules/inv_email.py
Office 365 SMTP email notifications for File Inventory governance.

Required .env keys:
    SMTP_SERVER   = smtp.office365.com
    SMTP_PORT     = 587
    SMTP_USER     = you@domain.com
    SMTP_PASSWORD = your_app_password
    NOTIFY_FROM   = notifications@datawranglersolutions.com   (can equal SMTP_USER)
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

def _smtp_config() -> dict:
    return {
        "server":   os.getenv("SMTP_SERVER",   "smtp.office365.com"),
        "port":     int(os.getenv("SMTP_PORT", "587")),
        "user":     os.getenv("SMTP_USER",     ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "from":     os.getenv("NOTIFY_FROM",   os.getenv("SMTP_USER", "")),
    }


def smtp_configured() -> bool:
    cfg = _smtp_config()
    return bool(cfg["user"] and cfg["password"])


# ─────────────────────────────────────────────────────────────────────────────
# Low-level send
# ─────────────────────────────────────────────────────────────────────────────

def _send(to_email: str, subject: str, html_body: str) -> bool:
    cfg = _smtp_config()
    if not cfg["user"] or not cfg["password"]:
        log.warning("SMTP not configured — skipping email to %s", to_email)
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = cfg["from"]
        msg["To"]      = to_email
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(cfg["server"], cfg["port"], timeout=15) as s:
            s.starttls()
            s.login(cfg["user"], cfg["password"])
            s.sendmail(cfg["from"], [to_email], msg.as_string())
        log.info("Email sent to %s: %s", to_email, subject)
        return True
    except Exception as ex:
        log.error("Email send failed to %s: %s", to_email, ex)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Templates
# ─────────────────────────────────────────────────────────────────────────────

_STYLE = """
<style>
body { font-family: Segoe UI, Arial, sans-serif; background:#f8fafc; color:#1e293b; }
.card { background:#fff; border-radius:8px; padding:28px 32px; max-width:560px;
        margin:32px auto; border:1px solid #e2e8f0; }
.header { font-size:1.25rem; font-weight:700; margin-bottom:4px; }
.sub { color:#64748b; font-size:0.9rem; margin-bottom:20px; }
.detail { background:#f1f5f9; border-radius:6px; padding:14px 18px;
          margin:16px 0; font-size:0.95rem; }
.detail b { display:inline-block; width:130px; color:#475569; }
.badge { display:inline-block; padding:3px 10px; border-radius:99px;
         font-size:0.8rem; font-weight:600; }
.open     { background:#dbeafe; color:#1d4ed8; }
.warn     { background:#fef9c3; color:#92400e; }
.extended { background:#ede9fe; color:#5b21b6; }
.complete { background:#dcfce7; color:#166534; }
footer { color:#94a3b8; font-size:0.78rem; margin-top:28px; }
</style>
"""


def notify_assignment_created(assignee_email: str, assignee_name: str,
                               group_name: str, file_type: str,
                               file_count: int, due_date: date,
                               assigned_by_name: str) -> bool:
    subject = f"📂 New Cataloging Assignment: {group_name}"
    html = f"""{_STYLE}
<div class="card">
  <div class="header">You have a new cataloging assignment</div>
  <div class="sub">Data Wrangler · File Inventory Governance</div>
  <div class="detail">
    <b>Group:</b> {group_name}<br>
    <b>File Type:</b> {file_type}<br>
    <b>Your Files:</b> {file_count:,}<br>
    <b>Due Date:</b> {due_date}<br>
    <b>Assigned By:</b> {assigned_by_name}
  </div>
  <p>Sign in to Data Wrangler and open the <strong>My Work</strong> tab to view your files.</p>
  <footer>Data Wrangler · File Inventory Governance</footer>
</div>"""
    return _send(assignee_email, subject, html)


def notify_due_date_approaching(assignee_email: str, assignee_name: str,
                                 group_name: str, due_date: date,
                                 days_remaining: int, remaining_files: int) -> bool:
    subject = f"⚠️ Assignment due in {days_remaining} day(s): {group_name}"
    html = f"""{_STYLE}
<div class="card">
  <div class="header">Assignment due soon <span class="badge warn">{days_remaining} day(s)</span></div>
  <div class="sub">Data Wrangler · File Inventory Governance</div>
  <div class="detail">
    <b>Group:</b> {group_name}<br>
    <b>Due Date:</b> {due_date}<br>
    <b>Remaining Files:</b> {remaining_files:,}
  </div>
  <p>Open the <strong>My Work</strong> tab in Data Wrangler to continue.</p>
  <footer>Data Wrangler · File Inventory Governance</footer>
</div>"""
    return _send(assignee_email, subject, html)


def notify_due_date_extended(assignee_email: str, assignee_name: str,
                              group_name: str, original_due: date,
                              new_due: date, extended_by: str, reason: str) -> bool:
    subject = f"📅 Due date extended: {group_name}"
    html = f"""{_STYLE}
<div class="card">
  <div class="header">Your due date has been extended <span class="badge extended">Extended</span></div>
  <div class="sub">Data Wrangler · File Inventory Governance</div>
  <div class="detail">
    <b>Group:</b> {group_name}<br>
    <b>Original Due:</b> {original_due}<br>
    <b>New Due Date:</b> <strong>{new_due}</strong><br>
    <b>Extended By:</b> {extended_by}<br>
    <b>Reason:</b> {reason}
  </div>
  <footer>Data Wrangler · File Inventory Governance</footer>
</div>"""
    return _send(assignee_email, subject, html)


def notify_assignment_completed(manager_email: str, group_name: str,
                                 completed_by: str) -> bool:
    subject = f"✅ Assignment completed: {group_name}"
    html = f"""{_STYLE}
<div class="card">
  <div class="header">Assignment completed <span class="badge complete">Complete</span></div>
  <div class="sub">Data Wrangler · File Inventory Governance</div>
  <div class="detail">
    <b>Group:</b> {group_name}<br>
    <b>Completed By:</b> {completed_by}
  </div>
  <p>Review in the <strong>Groups</strong> tab of Data Wrangler.</p>
  <footer>Data Wrangler · File Inventory Governance</footer>
</div>"""
    return _send(manager_email, subject, html)


def test_smtp(to_email: str) -> bool:
    """Send a test email to verify SMTP configuration."""
    return _send(to_email, "✅ Data Wrangler SMTP Test",
                 f"{_STYLE}<div class='card'><div class='header'>SMTP configured correctly</div>"
                 f"<p>Your Office 365 SMTP settings are working.</p>"
                 f"<footer>Data Wrangler · File Inventory Governance</footer></div>")
