import os
from typing import TypedDict, List, Dict, Any, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
import requests
import json

import config
from sheets_client import SheetsClient

# ---------------------------------------------------------
# 1. State Definition
# ---------------------------------------------------------
class CandidateState(TypedDict):
    candidate: Dict[str, Any]
    current_stage: str
    target_stage: Optional[str]
    validation_passed: bool
    sync_success: bool
    logs: List[str]
    candidate_profile: Optional[Dict[str, Any]]

# ---------------------------------------------------------
# 2. Pydantic Models for Structured Output
# ---------------------------------------------------------
class CandidateProfile(BaseModel):
    name: str = Field(description="The candidate's full name, formatted and capitalized.")
    email: str = Field(description="The candidate's email address, validated.")
    role: str = Field(description="The position or role, formatted neatly.")
    overall_sentiment: str = Field(description="Assessment based on candidate notes (e.g., 'Strong Profile', 'Good cultural match').")
    summary: str = Field(description="A concise 1-sentence summary of the candidate's current recruitment standing.")
    candidate_id: str = Field(default="", description="The candidate's unique ID if present, otherwise empty.")

# Initialize the SheetsClient
sheets = SheetsClient()

# ---------------------------------------------------------
# 3. Nodes
# ---------------------------------------------------------
def validate_candidate_profile(state: CandidateState) -> Dict[str, Any]:
    """
    Validates and cleans the candidate's profile data.
    Uses Gemini structured LLM validation if API key is present,
    otherwise falls back to basic dictionary validation.
    """
    candidate = state["candidate"]
    logs = list(state.get("logs", []))
    
    # 1. Basic checks with dynamic key support for live spreadsheet (Entries)
    if "First Name" in candidate or "Last Name" in candidate:
        name = f"{candidate.get('First Name', '')} {candidate.get('Last Name', '')}".strip()
    else:
        name = candidate.get("Name", "").strip()
        
    email = ""
    for k in candidate.keys():
        if k.strip().lower() in ("contact email", "email", "email address"):
            email = str(candidate[k]).strip()
            break
            
    role = candidate.get("Position you are interested in:", "") or candidate.get("Role", "")
    role = str(role).strip()
    
    candidate_id = str(candidate.get("Candidate_ID", "") or candidate.get("Candidate ID", "")).strip()
    
    logs.append(f"Starting validation for candidate: {email or 'Unknown'} (ID: {candidate_id or 'None'})")
    
    if not name or "@" not in email:
        logs.append("Validation failed: Missing name or invalid email address.")
        return {
            "validation_passed": False,
            "logs": logs,
            "candidate_profile": None
        }

    # 2. LLM clean up & structured analysis
    profile_data = {
        "name": name,
        "email": email,
        "role": role,
        "overall_sentiment": "Not assessed (LLM key missing)",
        "summary": f"Candidate for {role} at stage {state['current_stage']}",
        "candidate_id": candidate_id
    }

    if config.GEMINI_API_KEY:
        try:
            is_openrouter = config.GEMINI_API_KEY.strip().startswith("sk-or-")
            if is_openrouter:
                llm = ChatOpenAI(
                    model="google/gemini-flash-1.5",
                    api_key=config.GEMINI_API_KEY,
                    base_url="https://openrouter.ai/api/v1",
                    temperature=0,
                    max_tokens=400
                )
            else:
                from langchain_google_genai import ChatGoogleGenerativeAI
                llm = ChatGoogleGenerativeAI(
                    model="gemini-flash-latest",
                    google_api_key=config.GEMINI_API_KEY,
                    temperature=0,
                    max_output_tokens=400
                )
            structured_llm = llm.with_structured_output(CandidateProfile)
            prompt = (
                f"Analyze and format the following candidate details. Keep the summary extremely brief (under 15 words):\n"
                f"Name: {name}\n"
                f"Email: {email}\n"
                f"Role: {role}\n"
                f"Notes: {notes}\n"
            )
            res: CandidateProfile = structured_llm.invoke(prompt)
            profile_data = res.model_dump()
            profile_data["candidate_id"] = candidate_id
            logs.append("Candidate profile successfully structured and validated via Gemini.")
        except Exception as e:
            logs.append(f"LLM validation error: {e}. Falling back to standard values.")
            profile_data["candidate_id"] = candidate_id
    else:
        logs.append("Gemini API Key missing. Proceeding with standard dictionary validation.")

    return {
        "validation_passed": True,
        "logs": logs,
        "candidate_profile": profile_data
    }

def sync_candidate_to_next_stage(state: CandidateState) -> Dict[str, Any]:
    """
    Syncs candidate data into the target stage spreadsheet.
    """
    logs = list(state.get("logs", []))
    target_stage = state["target_stage"]
    profile = state["candidate_profile"]
    
    if not target_stage or not profile:
        logs.append("Sync skipped: Target stage or profile missing.")
        return {"sync_success": False, "logs": logs}
    
    logs.append(f"Attempting to sync candidate {profile['email']} to worksheet '{target_stage}'")
    
    # Prepare row data matching target worksheet headers
    if target_stage == "Demo Task Status":
        row_data = {
            "Candidate_ID": profile.get("candidate_id", ""),
            "Close Deadline": "False",
            "Demo task": "Yes",
            "Submission deadline": "",
            "Position": profile["role"],
            "Company": "Startup Greece",
            "State of demo task": "Pending",
            "Endorsement Status": "False",
            "2rd interview state": "",
            "Arrival": "",
            "Months": "",
            "Year": "",
            "Status": "Pending",
            "Demo Task Evaluation": f"Demo Task Evaluation - {profile['name']}",
            "Strong/ Weak Profile": "",
            "Notes": profile["summary"]
        }
    elif target_stage == "Next Steps":
        row_data = {
            "Candidate_ID": profile.get("candidate_id", ""),
            "State": "Pending",
            "Name": profile["name"],
            "Start Date": "",
            "End Date": "",
            "Acceptance Letter": "",
            "Documents From University": "",
            "NDA signed (Confidentiality agreement)": "",
            "Comments for problems": "",
            "Housing Updates": "",
            "Final Steps ": "",
            "Start onboarding ": "",
            "Comments": f"{profile['summary']} | Role: {profile['role']}",
            "LA CONTRACTS ACTIVE: 5. Current Contracts": ""
        }
    else:
        row_data = {
            "Candidate_ID": profile.get("candidate_id", ""),
            "Name": profile["name"],
            "Email": profile["email"],
            "Role": profile["role"],
            "Status": "Pending",  # Reset status to Pending upon stage entry
            "Notes": f"{profile['summary']} | {profile['overall_sentiment']}"
        }
    
    success = sheets.append_candidate_to_stage(target_stage, row_data)
    
    if success:
        logs.append(f"Successfully synced candidate {profile['email']} to '{target_stage}' worksheet.")
    else:
        logs.append(f"Failed to sync candidate {profile['email']} to '{target_stage}' worksheet.")
        
    return {"sync_success": success, "logs": logs}

def notify_pipeline_update(state: CandidateState) -> Dict[str, Any]:
    """
    Logs result and optionally sends Slack notifications to team.
    """
    logs = list(state.get("logs", []))
    profile = state["candidate_profile"]
    target_stage = state["target_stage"]
    
    message = (
        f"📢 *HR Sync Update* 📢\n"
        f"• *Candidate*: {profile['name'] if profile else 'Unknown'}\n"
        f"• *Email*: {profile['email'] if profile else 'Unknown'}\n"
        f"• *Stage transition*: {state['current_stage']} ➡️ {target_stage}\n"
        f"• *Sync Status*: {'✅ Success' if state['sync_success'] else '❌ Failed'}\n"
    )
    
    # Log locally
    print(f"\n--- LOG SUMMARY ---\n" + "\n".join(logs) + "\n-------------------\n")
    
    # Send Slack webhook if URL exists
    if config.SLACK_WEBHOOK_URL:
        try:
            payload = {"text": message}
            response = requests.post(
                config.SLACK_WEBHOOK_URL,
                data=json.dumps(payload),
                headers={'Content-Type': 'application/json'}
            )
            if response.status_code == 200:
                logs.append("Slack notification sent successfully.")
            else:
                logs.append(f"Slack webhook returned status code: {response.status_code}")
        except Exception as e:
            logs.append(f"Failed to send Slack notification: {e}")
            
    # Send Telegram notification if token & chat_id exist
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if telegram_token and telegram_chat_id:
        try:
            url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
            payload = {
                "chat_id": telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                logs.append("Telegram notification sent successfully.")
            else:
                logs.append(f"Telegram returned status code: {res.status_code}")
        except Exception as e:
            logs.append(f"Failed to send Telegram notification: {e}")
            
    return {"logs": logs}

# ---------------------------------------------------------
# 4. Routing / Edge Logic
# ---------------------------------------------------------
def route_after_validation(state: CandidateState) -> str:
    if state["validation_passed"]:
        return "sync"
    return "notify"

# ---------------------------------------------------------
# 5. Build the Graph
# ---------------------------------------------------------
builder = StateGraph(CandidateState)

builder.add_node("validate", validate_candidate_profile)
builder.add_node("sync", sync_candidate_to_next_stage)
builder.add_node("notify", notify_pipeline_update)

builder.set_entry_point("validate")

builder.add_conditional_edges(
    "validate",
    route_after_validation,
    {
        "sync": "sync",
        "notify": "notify"
    }
)
builder.add_edge("sync", "notify")
builder.add_edge("notify", END)

# Compile graph
graph = builder.compile()

# ---------------------------------------------------------
# 6. Primary Execution Interface
# ---------------------------------------------------------
def run_recruitment_sync(candidate_row: Dict[str, Any], current_stage: str, target_stage: str) -> Dict[str, Any]:
    """Runs a single candidate stage transition sync."""
    initial_state = {
        "candidate": candidate_row,
        "current_stage": current_stage,
        "target_stage": target_stage,
        "validation_passed": False,
        "sync_success": False,
        "logs": [],
        "candidate_profile": None
    }
    return graph.invoke(initial_state)
