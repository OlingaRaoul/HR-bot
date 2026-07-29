import os
import sys
import io
import time
import asyncio
import logging
import re
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import config
from sheets_client import SheetsClient
from main import scan_and_sync_pipeline
from langchain_openai import ChatOpenAI

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Dictionary to track last message timestamps and nudge state
chat_states = {}

def update_chat_activity(chat_id):
    """Resets the inactivity timer for a chat."""
    chat_states[chat_id] = {
        "timestamp": time.time(),
        "nudged": False
    }

def parse_sheet_date(date_str):
    """
    Parses various date formats from the spreadsheet into a python date object.
    Supports ISO formats, standard strings, and month names (e.g. "March 2nd", "June 1st").
    """
    if not date_str:
        return None
        
    date_str = str(date_str).strip()
    
    # 1. ISO format e.g. "2026-02-02T00:00:00.000Z"
    if "t" in date_str.lower():
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
        except:
            pass
            
    # 2. Standard YYYY-MM-DD
    match = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", date_str)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except:
            pass
            
    # 3. Text dates like "March 2nd", "June 1st", "March 1st 2026"
    months_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
    }
    
    lower_str = date_str.lower()
    month_val = None
    for m_name, m_num in months_map.items():
        if m_name in lower_str:
            month_val = m_num
            break
            
    if month_val:
        digits = re.findall(r"\d+", date_str)
        day_val = 1
        year_val = date.today().year  # default to current year
        
        if len(digits) == 1:
            day_val = int(digits[0])
        elif len(digits) >= 2:
            day_val = int(digits[0])
            year_val = int(digits[1])
            if year_val < 100:  # 2-digit year
                year_val += 2000
                
        try:
            return date(year_val, month_val, day_val)
        except:
            pass
            
    return None

async def check_and_send_reminders(app, specific_chat_id=None):
    """Scan spreadsheet tabs and compile a report of alerts/reminders."""
    chat_id = specific_chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        print("⚠️ TELEGRAM_CHAT_ID is not configured. Skipping automated reminders.")
        return False
        
    try:
        sheets = SheetsClient()
        entries = sheets.read_stage_data("Entries")
        demo_tasks = sheets.read_stage_data("Demo Task Status")
        next_steps = sheets.read_stage_data("Next Steps")
        
        today = date.today()
        reminders = []
        
        # 1. Profiles not updated in the last 30 days (Stale Pending/Open profiles)
        for row in entries:
            entry_date_str = row.get("Entry Date")
            entry_date = parse_sheet_date(entry_date_str)
            if entry_date:
                days_since = (today - entry_date).days
                status = str(row.get("Status") or "").strip().lower()
                stage = str(row.get("Stage") or "").strip().lower()
                if status in ("pending", "open") and days_since >= 30:
                    f_name = row.get("First Name", "")
                    l_name = row.get("Last Name", "")
                    name = f"{f_name} {l_name}".strip()
                    reminders.append(f"⚠️ *Stale Profile Alert*: '{name}' (Stage: {row.get('Stage')}) has been pending/open for {days_since} days (since {entry_date.strftime('%Y-%m-%d')}).")

        # 2. Database Mismatches
        # e.g., Demo Task Status mentions "Coming" but Entries Sheet is not updated
        demo_statuses = {}
        for row in demo_tasks:
            eval_col = str(row.get("Demo Task Evaluation") or "")
            name = eval_col.replace("Demo Task Evaluation - ", "").replace("Task Evaluation - ", "").strip().lower()
            if name:
                demo_statuses[name] = str(row.get("Status") or "").strip().lower()
                
        for row in entries:
            f_name = row.get("First Name", "")
            l_name = row.get("Last Name", "")
            name = f"{f_name} {l_name}".strip()
            entry_status = str(row.get("Status") or "").strip().lower()
            
            if name.lower() in demo_statuses:
                demo_status = demo_statuses[name.lower()]
                if demo_status == "coming" and entry_status != "coming" and entry_status != "closed":
                    reminders.append(f"🔄 *Status Mismatch*: Candidate '{name}' is marked 'Coming' in Demo Task Status, but Status in Entries tab is still '{row.get('Status') or 'N/A'}'.")

        # 3. Incoming Interns (1 month in advance)
        for row in next_steps:
            name = row.get("Name", "")
            start_date_str = row.get("Start Date")
            start_date = parse_sheet_date(start_date_str)
            
            if start_date:
                days_to_start = (start_date - today).days
                if 25 <= days_to_start <= 35:
                    reminders.append(f"📅 *Incoming Intern*: '{name}' is scheduled to start their internship on {start_date.strftime('%Y-%m-%d')} (in {days_to_start} days).")

        # 4. End of Internship (2 weeks in advance)
        for row in next_steps:
            name = row.get("Name", "")
            end_date_str = row.get("End Date") or row.get("End_Date")
            end_date = parse_sheet_date(end_date_str)
            
            if end_date:
                days_to_end = (end_date - today).days
                if 10 <= days_to_end <= 18:
                    reminders.append(f"🎓 *Internship Ending*: '{name}' is finishing their internship on {end_date.strftime('%Y-%m-%d')} (in {days_to_end} days).")

        # Send compiled reminders to Telegram
        if reminders:
            header = "🔔 *HR Pipeline Alert Summary* 🔔\n\n"
            msg = header + "\n\n".join(reminders[:15])  # limit list to prevent chat sizing overflow
            await app.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
            return True
        else:
            await app.bot.send_message(chat_id=chat_id, text="🔔 *HR Pipeline Alert*: No stale profiles, status mismatches, or upcoming starts/ends detected.")
            return True
    except Exception as e:
        print(f"Error checking reminders: {e}")
        return False

async def reminder_checker(app):
    """Background task running every 24 hours to automatically send reminders."""
    print("⏳ Daily reminder checker task started.")
    while True:
        await check_and_send_reminders(app)
        await asyncio.sleep(86400)  # Sleep for 24 hours

async def idle_checker(app):
    """Background loop to check idle states and nudge chats."""
    print("⏳ Idle checker task started.")
    while True:
        await asyncio.sleep(5)  # check every 5 seconds for high responsiveness
        now = time.time()
        timeout = config.TELEGRAM_IDLE_TIMEOUT_SECONDS
        
        for chat_id, state in list(chat_states.items()):
            if not state["nudged"] and (now - state["timestamp"]) >= timeout:
                state["nudged"] = True
                try:
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "👋 It's been a while since we chatted! I am here to help you manage the Startup Greece HR pipeline.\n\n"
                            "Please reply with a number to choose an option, or write any custom question:\n"
                            "1️⃣ Show live pipeline status & counts\n"
                            "2️⃣ Manually trigger the candidate sync sweep\n"
                            "3️⃣ Show instructions & help menu"
                        )
                    )
                except Exception as e:
                    print(f"Error sending idle nudge to chat {chat_id}: {e}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    update_chat_activity(chat_id)
    
    user_name = update.effective_user.first_name if update.effective_user else "there"
    message = (
        f"👋 Hello {user_name}! I am your **HR Recruitment Automation Bot** for Startup Greece.\n\n"
        f"Please reply with a number to choose an option, or write any custom question:\n"
        f"1️⃣ Show live pipeline status & counts\n"
        f"2️⃣ Manually trigger the candidate sync sweep\n"
        f"3️⃣ Show instructions & help menu"
    )
    await update.message.reply_text(message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_command(update, context)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    update_chat_activity(chat_id)
    
    await update.message.reply_text("📊 Fetching live pipeline status from Google Sheets...")
    
    try:
        sheets = SheetsClient()
        entries = sheets.read_stage_data("Entries")
        demo_tasks = sheets.read_stage_data("Demo Task Status")
        next_steps = sheets.read_stage_data("Next Steps")
        
        pending_entries = len([
            x for x in entries 
            if str(x.get("Status") or "").strip().lower() in ("pending", "open") 
            and str(x.get("Stage") or "").strip().lower() in ("demo tasks", "demo task")
        ])
        eval_tasks = len([
            x for x in demo_tasks 
            if str(x.get("State of demo task") or "").strip().lower() == "for evaluation"
        ])
        coming_tasks = len([
            x for x in demo_tasks 
            if str(x.get("Status") or "").strip().lower() == "coming"
        ])
        
        message = (
            f"📈 *Live Pipeline Dashboard*:\n\n"
            f"• *Entries Sheet*: {len(entries)} total candidates ({pending_entries} pending for Demo Tasks).\n"
            f"• *Demo Task Status*: {len(demo_tasks)} total tasks ({eval_tasks} awaiting evaluation, {coming_tasks} marked 'Coming').\n"
            f"• *Next Steps (Onboarding)*: {len(next_steps)} candidates enrolled."
        )
        await update.message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error fetching status: {e}")

async def sync_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    update_chat_activity(chat_id)
    
    await update.message.reply_text("🔄 Starting manual synchronization sweep...")
    
    try:
        sheets = SheetsClient()
        
        old_stdout = sys.stdout
        sys.stdout = mystdout = io.StringIO()
        
        try:
            scan_and_sync_pipeline(sheets)
        finally:
            sys.stdout = old_stdout
            
        output_logs = mystdout.getvalue()
        lines = output_logs.split("\n")
        summary = []
        for line in lines:
            if "[TRIGGERED]" in line or "[SUCCESS]" in line or "[FAILED]" in line or "[INFO]" in line:
                summary.append(line)
                
        if summary:
            message = "✅ *Sync Sweep Complete*:\n\n" + "\n".join(summary)
        else:
            message = "✅ *Sync Sweep Complete*: No new candidate transitions detected."
            
        await update.message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error executing sync: {e}")

async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Directly triggers check and send reminders command on Telegram chat."""
    chat_id = update.effective_chat.id
    update_chat_activity(chat_id)
    await update.message.reply_text("🔎 Scanning database for stale profiles, mismatches, and schedule alerts...")
    await check_and_send_reminders(context.application, specific_chat_id=chat_id)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    update_chat_activity(chat_id)
    
    user_text = update.message.text
    if not user_text:
        return
        
    # Route option selections
    cleaned_input = user_text.strip()
    if cleaned_input in ("1", "1️⃣"):
        await status_command(update, context)
        return
    elif cleaned_input in ("2", "2️⃣"):
        await sync_command(update, context)
        return
    elif cleaned_input in ("3", "3️⃣"):
        await help_command(update, context)
        return
        
    if not config.GEMINI_API_KEY:
        await update.message.reply_text("🤖 Gemini AI engine is not configured (API key missing).")
        return
        
    # Determine if the query requires live database search
    needs_excel = False
    is_openrouter = config.GEMINI_API_KEY.strip().startswith("sk-or-")
    
    try:
        if is_openrouter:
            decision_llm = ChatOpenAI(
                model="google/gemini-2.5-flash",
                api_key=config.GEMINI_API_KEY,
                base_url="https://openrouter.ai/api/v1",
                temperature=0,
                max_tokens=10
            )
        else:
            from langchain_google_genai import ChatGoogleGenerativeAI
            decision_llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                google_api_key=config.GEMINI_API_KEY,
                temperature=0,
                max_output_tokens=10
            )
            
        decision_prompt = (
            "Identify if answering the user question requires reading live candidate status, "
            "recruitment lists, trainee names, start/end dates, monthly statistics, or pipeline data from the Google Sheets database. "
            f"Question: '{user_text}'\n"
            "Reply with ONLY 'YES' or 'NO' and nothing else."
        )
        decision_res = decision_llm.invoke(decision_prompt)
        needs_excel = "yes" in str(decision_res.content).strip().lower()
    except Exception as e:
        print(f"Error classifying Excel dependency: {e}")
        # Default fallback to checking query keywords
        keywords = ("candidate", "trainee", "demo", "status", "people", "names", "who", "stage", "onboarding", "position", "sheet", "excel", "list", "progress", "month", "summary", "percentage", "accepted", "pending", "may", "june", "july", "august")
        needs_excel = any(kw in user_text.lower() for kw in keywords)

    if needs_excel:
        await update.message.reply_text("🔎 Accessing live HR database...")
        try:
            sheets = SheetsClient()
            entries = sheets.read_stage_data("Entries")
            demo_tasks = sheets.read_stage_data("Demo Task Status")
            next_steps = sheets.read_stage_data("Next Steps")
            
            # Format Demo Task Status candidates
            demo_list = []
            for row in demo_tasks:
                eval_col = str(row.get("Demo Task Evaluation") or "")
                name = eval_col.replace("Demo Task Evaluation - ", "").replace("Task Evaluation - ", "").strip()
                if name:
                    pos = str(row.get("Position") or "N/A").strip()
                    demo_state = str(row.get("State of demo task") or "N/A").strip()
                    status = str(row.get("Status") or "N/A").strip()
                    interview = str(row.get("2rd interview state") or "N/A").strip()
                    demo_list.append(f"• Candidate: {name} | Position: {pos} | Demo State: {demo_state} | 2nd Interview: {interview} | Status: {status}")

            # Format pending candidates in Entries sheet
            entries_pending_list = []
            for row in entries:
                status = str(row.get("Status") or "").strip().lower()
                stage = str(row.get("Stage") or "").strip().lower()
                if status in ("pending", "open") and stage in ("demo tasks", "demo task"):
                    f_name = str(row.get("First Name") or "").strip()
                    l_name = str(row.get("Last Name") or "").strip()
                    name = f"{f_name} {l_name}".strip()
                    pos = str(row.get("Position you are interested in:") or "").strip()
                    entry_date_str = str(row.get("Entry Date") or "N/A").strip()
                    if name:
                        entries_pending_list.append(f"• Candidate: {name} | Position: {pos} | Stage: {row.get('Stage')} | Status: {row.get('Status')} | Entry Date: {entry_date_str}")

            # Format Next Steps candidates
            next_list = []
            for row in next_steps:
                name = str(row.get("Name") or "").strip()
                if name:
                    next_list.append(f"• Candidate: {name} | State: {row.get('State', 'N/A')} | Start: {row.get('Start Date')} | End: {row.get('End Date')}")
                    
            # Pre-compute monthly statistics
            monthly_stats = {}
            for row in entries:
                entry_date_str = row.get("Entry Date")
                entry_date = parse_sheet_date(entry_date_str)
                if entry_date:
                    month_key = entry_date.strftime("%B %Y")
                    if month_key not in monthly_stats:
                        monthly_stats[month_key] = {"total": 0, "accepted": 0, "pending": 0}
                    monthly_stats[month_key]["total"] += 1
                    
                    status = str(row.get("Status") or "").strip().lower()
                    if status in ("pending", "open"):
                        monthly_stats[month_key]["pending"] += 1
                    elif status == "closed" or "synced" in status or "coming" in status:
                        monthly_stats[month_key]["accepted"] += 1
                        
            stats_lines = []
            for m_key, counts in monthly_stats.items():
                pct = (counts["accepted"] / counts["total"] * 100) if counts["total"] > 0 else 0
                stats_lines.append(f"- {m_key}: {counts['total']} total entries, {counts['accepted']} accepted ({pct:.1f}% acceptance rate), {counts['pending']} left pending.")
            stats_summary = "\n".join(stats_lines)

            prompt_context = (
                "You are the official AI HR Assistant for Startup Greece.\n"
                "Below is the LIVE candidate data retrieved directly from the Google Sheets database:\n\n"
                "=== 1. CANDIDATES IN DEMO TASK STATUS TAB ===\n"
                + ("\n".join(demo_list[:25]) if demo_list else "No candidates currently in Demo Task Status.") + "\n\n"
                "=== 2. ALL QUEUED PENDING/OPEN CANDIDATES IN ENTRIES TAB ===\n"
                + ("\n".join(entries_pending_list[:25]) if entries_pending_list else "No pending candidates in Entries.") + "\n\n"
                "=== 3. CANDIDATES IN NEXT STEPS TAB (Onboarding & Schedules) ===\n"
                + ("\n".join(next_list[:20]) if next_list else "No candidates in Next Steps.") + "\n\n"
                "=== 4. PRE-COMPUTED MONTHLY PIPELINE STATISTICS ===\n"
                + (stats_summary if stats_summary else "No monthly stats data available.") + "\n\n"
                f"USER QUESTION: {user_text}\n\n"
                "INSTRUCTIONS:\n"
                "- Answer the user's question accurately using ONLY the live data and monthly summaries above.\n"
                "- If asked about a candidate left pending from May, search the Entries and Pipeline stats for May.\n"
                "- List specific candidate names, positions, and current statuses when asked.\n"
                "- Be direct, helpful, and concise."
            )
            
            if is_openrouter:
                llm = ChatOpenAI(
                    model="google/gemini-2.5-flash",
                    api_key=config.GEMINI_API_KEY,
                    base_url="https://openrouter.ai/api/v1",
                    temperature=0.3,
                    max_tokens=500
                )
            else:
                from langchain_google_genai import ChatGoogleGenerativeAI
                llm = ChatGoogleGenerativeAI(
                    model="gemini-2.5-flash",
                    google_api_key=config.GEMINI_API_KEY,
                    temperature=0.3,
                    max_output_tokens=500
                )
                
            res = llm.invoke(prompt_context)
            await update.message.reply_text(res.content)
        except Exception as e:
            await update.message.reply_text(f"🤖 Error querying live database: {e}")
    else:
        # Just answer directly without loading Excel!
        try:
            if is_openrouter:
                llm = ChatOpenAI(
                    model="google/gemini-2.5-flash",
                    api_key=config.GEMINI_API_KEY,
                    base_url="https://openrouter.ai/api/v1",
                    temperature=0.7,
                    max_tokens=500
                )
            else:
                from langchain_google_genai import ChatGoogleGenerativeAI
                llm = ChatGoogleGenerativeAI(
                    model="gemini-2.5-flash",
                    google_api_key=config.GEMINI_API_KEY,
                    temperature=0.7,
                    max_output_tokens=500
                )
            res = llm.invoke(f"You are the HR Assistant for Startup Greece. Answer the following question: {user_text}")
            await update.message.reply_text(res.content)
        except Exception as e:
            await update.message.reply_text(f"🤖 Error: {e}")

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN is missing in your .env file!")
        print("Please add TELEGRAM_BOT_TOKEN=your_token to .env and try again.")
        return
        
    async def post_init(application):
        asyncio.create_task(idle_checker(application))
        asyncio.create_task(reminder_checker(application))
        
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("sync", sync_command))
    app.add_handler(CommandHandler("reminders", reminders_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🚀 Telegram Bot is running! Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
