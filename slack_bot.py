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
            sheets = SheetsClient()
            entries = sheets.read_stage_data("Entries")
            demo_tasks = sheets.read_stage_data("Demo Task Status")
            next_steps = sheets.read_stage_data("Next Steps")
            
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

            next_list = []
            for row in next_steps:
                name = str(row.get("Name") or "").strip()
                if name:
                    next_list.append(f"• Candidate: {name} | State: {row.get('State', 'N/A')} | Start: {row.get('Start Date')} | End: {row.get('End Date')}")
                    
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
                "You are a helpful, professional, and warm AI HR Coordinator at Startup Greece. "
                "Your tone should be conversational, natural, and friendly (like talking to a real human colleague), "
                "while remaining precise and accurate with candidate facts and names. "
                "Never sound robotic, cold, or overly structured unless specifically asked. Avoid repeating the same rigid template.\n\n"
                "Here is the LIVE candidate database retrieved from our Google Sheets:\n\n"
                "=== 1. CANDIDATES IN DEMO TASK STATUS TAB ===\n"
                + ("\n".join(demo_list[:25]) if demo_list else "No candidates currently in Demo Task Status.") + "\n\n"
                "=== 2. ALL QUEUED PENDING/OPEN CANDIDATES IN ENTRIES TAB ===\n"
                + ("\n".join(entries_pending_list[:25]) if entries_pending_list else "No pending candidates in Entries.") + "\n\n"
                "=== 3. CANDIDATES IN NEXT STEPS TAB (Onboarding & Schedules) ===\n"
                + ("\n".join(next_list[:20]) if next_list else "No candidates in Next Steps.") + "\n\n"
                "=== 4. PRE-COMPUTED MONTHLY PIPELINE STATISTICS ===\n"
                + (stats_summary if stats_summary else "No monthly stats data available.") + "\n\n"
                f"QUESTION FROM COLLEAGUE: {prompt}\n\n"
                "INSTRUCTIONS FOR YOUR RESPONSE:\n"
                "- Answer the question naturally in complete, friendly sentences. Write like a real HR colleague responding to a team member.\n"
                "- Include specific details like candidate names, positions, and current statuses when answering questions about candidates.\n"
                "- Do not output raw data dumps. Keep it clear, engaging, and professional."
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
