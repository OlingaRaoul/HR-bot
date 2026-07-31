import os
import sys
import json
import re
from datetime import datetime, date
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from langchain_openai import ChatOpenAI

import config
from sheets_client import SheetsClient
from main import scan_and_sync_pipeline

# Load environment variables
load_dotenv()

# Initialize Slack App using Bolt
# Automatically uses SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET from environment
app = App(
    token=os.getenv("SLACK_BOT_TOKEN"),
    signing_secret=os.getenv("SLACK_SIGNING_SECRET")
)

def parse_sheet_date(date_str):
    """Parses various date formats from the spreadsheet into a python date object."""
    if not date_str:
        return None
    date_str = str(date_str).strip()
    
    if "t" in date_str.lower():
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
        except:
            pass
            
    match = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", date_str)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except:
            pass
            
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
        year_val = date.today().year
        
        if len(digits) == 1:
            day_val = int(digits[0])
        elif len(digits) >= 2:
            day_val = int(digits[0])
            year_val = int(digits[1])
            if year_val < 100:
                year_val += 2000
        try:
            return date(year_val, month_val, day_val)
        except:
            pass
            
    return None

@app.event("app_mention")
def handle_app_mention(event, say):
    """Processes app mentions inside Slack channels."""
    text = event.get("text", "")
    user = event.get("user", "")
    
    # Extract actual command text (remove bot tag)
    command = text.split(">", 1)[-1].strip()
    command_lower = command.lower()
    
    try:
        if not command or command_lower in ("help", "info", "/help"):
            reply_help(say, user)
        elif command_lower in ("status", "list", "/status", "/list"):
            reply_status(say)
        elif command_lower in ("sync", "run", "/sync", "/run"):
            reply_sync(say)
        else:
            # Fallback: Treat as a direct question to the AI Agent
            reply_gemini_chat(say, command)
    except Exception as e:
        print(f"Error handling Slack command '{command}': {e}")
        try:
            say(f"⚠️ Sorry, I encountered an error while processing that command: {e}")
        except Exception:
            pass

@app.event("message")
def handle_message_events(event, say):
    """Processes direct messages (DMs) to the bot."""
    channel_type = event.get("channel_type")
    
    # Ignore messages sent by bots to avoid infinite loops
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return
        
    # Process if it is a Direct Message (IM)
    if channel_type == "im" or str(event.get("channel") or "").startswith("D"):
        text = event.get("text", "")
        command = text.strip()
        command_lower = command.lower()
        
        try:
            if not command or command_lower in ("help", "info", "/help"):
                reply_help(say, event.get("user"))
            elif command_lower in ("status", "list", "/status", "/list"):
                reply_status(say)
            elif command_lower in ("sync", "run", "/sync", "/run"):
                reply_sync(say)
            else:
                reply_gemini_chat(say, command)
        except Exception as e:
            print(f"Error handling Slack DM command '{command}': {e}")
            try:
                say(f"⚠️ Sorry, I encountered an error while processing that command: {e}")
            except Exception:
                pass

def reply_help(say, user):
    message = (
        f"👋 Hello <@{user}>! I am your **HR Recruitment Automation Bot** running on Slack Bolt.\n\n"
        f"Here are the commands you can mention me with:\n"
        f"• `@HR Bot status` - Shows current candidates count and pending states.\n"
        f"• `@HR Bot sync` - Manually triggers the recruitment synchronization sweep.\n"
        f"• `@HR Bot help` - Displays this instruction menu.\n"
        f"• `@HR Bot [any question]` - Chat directly with me to analyze candidates, pipeline, or monthly metrics."
    )
    say(message)

def reply_status(say):
    say("📊 Fetching live pipeline status...")
    try:
        sheets = SheetsClient()
        entries = sheets.read_stage_data("Entries")
        demo_tasks = sheets.read_stage_data("Demo Task Status")
        next_steps = sheets.read_stage_data("Next Steps")
        
        pending_entries = len([x for x in entries if str(x.get("Status") or "").strip().lower() in ("pending", "open") and str(x.get("Stage") or "").strip().lower() in ("demo tasks", "demo task")])
        eval_tasks = len([x for x in demo_tasks if str(x.get("State of demo task") or "").strip().lower() == "for evaluation"])
        coming_tasks = len([x for x in demo_tasks if str(x.get("Status") or "").strip().lower() == "coming"])
        
        message = (
            f"📈 *Live Pipeline Dashboard*:\n"
            f"• *Entries Sheet*: {len(entries)} total entries ({pending_entries} pending/open for Demo Tasks).\n"
            f"• *Demo Task Status*: {len(demo_tasks)} total tasks ({eval_tasks} awaiting evaluation, {coming_tasks} marked 'Coming').\n"
            f"• *Next Steps (Onboarding)*: {len(next_steps)} candidates enrolled."
        )
        say(message)
    except Exception as e:
        say(f"⚠️ Error querying database: {e}")

def reply_sync(say):
    say("🔄 Starting manual synchronization sweep...")
    try:
        sheets = SheetsClient()
        
        old_stdout = sys.stdout
        sys.stdout = mystdout = io.StringIO() if sys.version_info >= (3, 0) else io.BytesIO()
        
        # StringIO needs to be imported or referenced safely
        import io as python_io
        mystdout = python_io.StringIO()
        sys.stdout = mystdout
        
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
            message = "✅ *Sync Sweep Complete*:\n" + "\n".join(summary)
        else:
            message = "✅ *Sync Sweep Complete*: No new transitions detected."
        say(message)
    except Exception as e:
        say(f"⚠️ Error executing sync: {e}")

def reply_gemini_chat(say, prompt):
    if not config.GEMINI_API_KEY:
        say("🤖 Gemini AI engine is not configured (API key missing).")
        return
        
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
            f"Question: '{prompt}'\n"
            "Reply with ONLY 'YES' or 'NO' and nothing else."
        )
        decision_res = decision_llm.invoke(decision_prompt)
        needs_excel = "yes" in str(decision_res.content).strip().lower()
    except Exception as e:
        print(f"Error classifying Excel dependency: {e}")
        keywords = ("candidate", "trainee", "demo", "status", "people", "names", "who", "stage", "onboarding", "position", "sheet", "excel", "list", "progress", "month", "summary", "percentage", "accepted")
        needs_excel = any(kw in prompt.lower() for kw in keywords)

    if needs_excel:
        say("🔎 Accessing live HR database...")
        try:
            from datetime import date
            sheets = SheetsClient()
            entries = sheets.read_stage_data("Entries")
            demo_tasks = sheets.read_stage_data("Demo Task Status")
            next_steps = sheets.read_stage_data("Next Steps")
            
            # Find specific name mentions in query to prioritize matching rows
            query_lower = prompt.lower()
            
            # 1. Pre-compute Alerts, Mismatches, and Intern Schedules
            today = date.today()
            stale_profiles = []
            mismatches = []
            starting_soon = []
            ending_soon = []
            
            # Stale Pending/Open profiles (>= 30 days old)
            for row in entries:
                status = str(row.get("Status") or "").strip().lower()
                if status in ("pending", "open"):
                    entry_date = parse_sheet_date(row.get("Entry Date"))
                    if entry_date:
                        days_since = (today - entry_date).days
                        if days_since >= 30:
                            f_name = str(row.get("First Name") or "").strip()
                            l_name = str(row.get("Last Name") or "").strip()
                            name = f"{f_name} {l_name}".strip()
                            if name:
                                stale_profiles.append(
                                    f"🔔 Stale profile — {name}\n"
                                    f"Entries row for {name} hasn't been updated in {days_since} days."
                                )
                                
            # Cross-sheet mismatches
            demo_statuses = {}
            for row in demo_tasks:
                eval_col = str(row.get("Demo Task Evaluation") or "")
                name = eval_col.replace("Demo Task Evaluation - ", "").replace("Task Evaluation - ", "").strip()
                if name:
                    demo_statuses[name.lower()] = {
                        "name": name,
                        "status": str(row.get("Status") or "").strip(),
                        "state": str(row.get("State of demo task") or "").strip()
                    }
                    
            for row in entries:
                f_name = str(row.get("First Name") or "").strip()
                l_name = str(row.get("Last Name") or "").strip()
                name = f"{f_name} {l_name}".strip()
                entry_status = str(row.get("Status") or "").strip()
                entry_stage = str(row.get("Stage") or "").strip()
                
                if name:
                    # Miriam Püschner case: marked Coming in Demo Task Status but not active at Demo Task in Entries
                    if name.lower() in demo_statuses:
                        demo_info = demo_statuses[name.lower()]
                        if demo_info["status"].lower() == "coming" and entry_status.lower() not in ("coming", "closed", "accepted"):
                            mismatches.append(
                                f"⚠️ Sheet mismatch — {demo_info['name']}\n"
                                f"{demo_info['name']} shows Status \"Coming\" in Demo Task Status, but Entries doesn't show them as active at Demo Task stage. Update Entries to match."
                            )
                    # Ahmad Hijazi case: Demo Task stage in Entries but no row in Demo Task Status
                    if entry_stage.lower() in ("demo tasks", "demo task") and entry_status.lower() in ("pending", "open"):
                        if name.lower() not in demo_statuses:
                            mismatches.append(
                                f"⚠️ Sheet mismatch — {name}\n"
                                f"{name} is at Demo Task stage in Entries (Status: {entry_status.upper()}) but has no row in Demo Task Status. Add them, or update Entries if this candidate actually dropped out."
                            )

            # Intern start/end dates
            for row in next_steps:
                name = str(row.get("Name") or "").strip()
                start_date = parse_sheet_date(row.get("Start Date"))
                end_date = parse_sheet_date(row.get("End Date") or row.get("End_Date"))
                
                if name:
                    if start_date:
                        days_to_start = (start_date - today).days
                        if 25 <= days_to_start <= 35:
                            starting_soon.append(
                                f"📅 Starting in 1 month — {name}\n"
                                f"{name} starts on {start_date.strftime('%Y-%m-%d')}."
                            )
                    if end_date:
                        days_to_end = (end_date - today).days
                        if 10 <= days_to_end <= 18:
                            ending_soon.append(
                                f"📅 Ending in 2 weeks — {name}\n"
                                f"{name}'s internship ends on {end_date.strftime('%Y-%m-%d')}."
                            )

            # 2. Filter Candidate Rows relevant to the user query
            demo_matched = []
            demo_other = []
            for row in demo_tasks:
                eval_col = str(row.get("Demo Task Evaluation") or "")
                name = eval_col.replace("Demo Task Evaluation - ", "").replace("Task Evaluation - ", "").strip()
                if name:
                    pos = str(row.get("Position") or "N/A").strip()
                    demo_state = str(row.get("State of demo task") or "N/A").strip()
                    status = str(row.get("Status") or "N/A").strip()
                    interview = str(row.get("2rd interview state") or "N/A").strip()
                    line = f"• Candidate: {name} | Position: {pos} | Demo State: {demo_state} | 2nd Interview: {interview} | Status: {status}"
                    
                    if name.lower() in query_lower:
                        demo_matched.append(line)
                    else:
                        demo_other.append(line)
            demo_list = demo_matched + demo_other

            entries_matched = []
            entries_other = []
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
                        line = f"• Candidate: {name} | Position: {pos} | Stage: {row.get('Stage')} | Status: {row.get('Status')} | Entry Date: {entry_date_str}"
                        if name.lower() in query_lower:
                            entries_matched.append(line)
                        else:
                            entries_other.append(line)
            entries_pending_list = entries_matched + entries_other

            next_matched = []
            next_other = []
            for row in next_steps:
                name = str(row.get("Name") or "").strip()
                if name:
                    line = f"• Candidate: {name} | State: {row.get('State', 'N/A')} | Start: {row.get('Start Date')} | End: {row.get('End Date')}"
                    if name.lower() in query_lower:
                        next_matched.append(line)
                    else:
                        next_other.append(line)
            next_list = next_matched + next_other

            # 3. Monthly statistics percentages
            monthly_stats = {}
            for row in entries:
                entry_date_str = row.get("Entry Date")
                entry_date = parse_sheet_date(entry_date_str)
                if entry_date:
                    month_key = entry_date.strftime("%B %Y")
                    if month_key not in monthly_stats:
                        monthly_stats[month_key] = {"total": 0, "accepted": 0, "rejected": 0, "pending": 0, "open": 0}
                    monthly_stats[month_key]["total"] += 1
                    
                    status = str(row.get("Status") or "").strip().lower()
                    if status == "pending":
                        monthly_stats[month_key]["pending"] += 1
                    elif status == "open":
                        monthly_stats[month_key]["open"] += 1
                    elif status in ("closed", "accepted", "coming") or "synced" in status:
                        monthly_stats[month_key]["accepted"] += 1
                    elif "reject" in status or "decline" in status or "fail" in status:
                        monthly_stats[month_key]["rejected"] += 1
                        
            stats_lines = []
            for m_key, counts in monthly_stats.items():
                tot = counts["total"]
                if tot > 0:
                    pct_acc = round(counts["accepted"] / tot * 100)
                    pct_rej = round(counts["rejected"] / tot * 100)
                    pct_pen = round(counts["pending"] / tot * 100)
                    pct_op = round(counts["open"] / tot * 100)
                    stats_lines.append(f"📊 {m_key} summary: {tot} entries — {pct_acc}% Accepted, {pct_rej}% Rejected, {pct_pen}% still Pending, {pct_op}% Open.")
            stats_summary = "\n".join(stats_lines)

            # 4. Construct AI prompt context with all alerts and metrics
            prompt_context = (
                "You are a helpful, professional, and warm AI HR Coordinator at Startup Greece. "
                "Your tone should be conversational, natural, and friendly (like talking to a real human colleague), "
                "while remaining precise and accurate with candidate facts and names. "
                "Never sound robotic, cold, or overly structured unless specifically asked. Avoid repeating the same rigid template.\n\n"
                
                "Below are the PRE-COMPUTED alerts, mismatches, and summaries from our database. "
                "Use them directly to answer questions about stale profiles, mismatches, intern dates, and monthly metrics:\n\n"
                
                "=== 1. PRE-COMPUTED STALE PROFILES (>= 30 days of inactivity) ===\n"
                + ("\n\n".join(stale_profiles[:15]) if stale_profiles else "No stale profiles found.") + "\n\n"
                
                "=== 2. PRE-COMPUTED CROSS-SHEET MISMATCHES ===\n"
                + ("\n\n".join(mismatches[:15]) if mismatches else "No cross-sheet mismatches found.") + "\n\n"
                
                "=== 3. PRE-COMPUTED INTERN START/END ALERTS ===\n"
                + ("\n\n".join(starting_soon + ending_soon) if (starting_soon or ending_soon) else "No upcoming start/end dates.") + "\n\n"
                
                "=== 4. PRE-COMPUTED MONTHLY PIPELINE SUMMARIES ===\n"
                + (stats_summary if stats_summary else "No monthly summary stats available.") + "\n\n"
                
                "=== 5. RETRIEVED CANDIDATE DETAIL ROWS ===\n"
                + ("\n".join(demo_list[:25]) if demo_list else "No matching demo task entries.") + "\n"
                + ("\n".join(entries_pending_list[:25]) if entries_pending_list else "No matching entry log entries.") + "\n"
                + ("\n".join(next_list[:25]) if next_list else "No matching onboarding entries.") + "\n\n"
                
                f"QUESTION FROM COLLEAGUE: {prompt}\n\n"
                "INSTRUCTIONS FOR YOUR RESPONSE:\n"
                "- If the user asks for alerts, mismatches, stale profiles, start/end dates, or monthly summaries, look at sections 1, 2, 3, or 4 and output the matching items EXACTLY in the formatting shown in the section (using emoji badges like 🔔, ⚠️, 📅, 📊).\n"
                "- If the user asks a natural language question (e.g. 'From May, is there a candidate left pending?'), answer in a warm, direct, conversational way (e.g. 'Yes — 25 candidates from May 2026 are still Pending, including...').\n"
                "- Always include specific details like candidate names, positions, and current statuses when replying.\n"
                "- Keep the response direct, natural, and clean. Do not include raw instruction names or debug labels."
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
            say(res.content)
        except Exception as e:
            say(f"⚠️ Error querying database: {e}")
    else:
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
            res = llm.invoke(f"You are a warm, helpful, and natural HR Assistant for Startup Greece. Answer the following question in a friendly, conversational way: {prompt}")
            say(res.content)
        except Exception as e:
            say(f"🤖 Sorry, I failed to ask Gemini: {e}")

if __name__ == "__main__":
    app_token = os.getenv("SLACK_APP_TOKEN")
    if not app_token:
        print("❌ SLACK_APP_TOKEN is missing in your .env file!")
        print("Please enable Socket Mode in the Slack Console, generate an App-Level Token, and add it to .env.")
        sys.exit(1)
        
    print("⚡ Slack Bolt App is running in Socket Mode!")
    handler = SocketModeHandler(app, app_token)
    handler.start()
