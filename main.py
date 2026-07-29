import time
import argparse
import asyncio
from typing import Dict, Any

import config
from sheets_client import SheetsClient
from agent import run_recruitment_sync

# Map current stages and triggering status values to their target stage
STAGE_TRANSITIONS = {
    "Inbound_Screening": {
        "Proceed to Tech Interview": "Technical_Interview",
        "Move to Technical Interview": "Technical_Interview"
    },
    "Technical_Interview": {
        "Proceed to Cultural Fit": "Cultural_Fit_Interview",
        "Move to Cultural Fit": "Cultural_Fit_Interview"
    },
    "Cultural_Fit_Interview": {
        "Proceed to Offer": "Offer_Stage",
        "Move to Offer": "Offer_Stage"
    },
    "Offer_Stage": {
        "Proceed to Onboarding": "Onboarding",
        "Move to Onboarding": "Onboarding"
    }
}

def scan_and_sync_pipeline(sheets: SheetsClient):
    """
    Scans each stage worksheet for candidates triggering progression status,
    and runs the sync pipeline for each match.
    """
    print("Scanning recruitment worksheets for status changes...")
    
    # 1. Scan the "Entries" tab (for the live recruitment workflow)
    try:
        entries = sheets.read_stage_data("Entries")
        demo_rows = sheets.read_stage_data("Demo Task Status")
        existing_names = set()
        
        # Populate in-memory lookup set of already synced candidate names
        for r in demo_rows:
            eval_col = r.get("Demo Task Evaluation", "")
            if eval_col:
                if "Demo Task Evaluation - " in eval_col:
                    name = eval_col.replace("Demo Task Evaluation - ", "").strip()
                    existing_names.add(name.lower())
                elif "Task Evaluation - " in eval_col:
                    name = eval_col.replace("Task Evaluation - ", "").strip()
                    existing_names.add(name.lower())
                    
        sync_count = 0
        max_syncs_per_sweep = 3
        
        for candidate in entries:
            status = candidate.get("Status", "").strip().lower()
            stage = candidate.get("Stage", "").strip().lower()
            
            # Condition: Status is Pending or Open, and Stage is Demo Tasks
            if status in ("pending", "open") and stage in ("demo tasks", "demo task"):
                first_name = candidate.get("First Name", "").strip()
                last_name = candidate.get("Last Name", "").strip()
                name = f"{first_name} {last_name}".strip()
                
                email = ""
                for k in candidate.keys():
                    if k.strip().lower() in ("contact email", "email", "email address"):
                        email = str(candidate[k]).strip()
                        break
                        
                # Prevent duplicate entries in Demo Task Status
                if name.lower() in existing_names:
                    continue
                
                if sync_count >= max_syncs_per_sweep:
                    print(f"\n[INFO] Safety limit reached ({max_syncs_per_sweep} syncs). Pausing further syncs for this sweep.")
                    break
                    
                print(f"\n[TRIGGERED] Candidate '{name}' ({email}) in 'Entries' meets criteria: Status='{candidate.get('Status')}', Stage='{candidate.get('Stage')}'")
                print("Propagating to stage 'Demo Task Status'...")
                
                # Invoke the LangGraph automation agent
                res = run_recruitment_sync(candidate, "Entries", "Demo Task Status")
                
                if res.get("sync_success", False):
                    print(f"[SUCCESS] Synced candidate '{name}' ({email}) to 'Demo Task Status' tab.")
                    existing_names.add(name.lower())
                    sync_count += 1
                else:
                    print(f"[FAILED] Failed to sync candidate '{name}' ({email}). Refer to logs above.")
    except Exception as e:
        print(f"Error scanning 'Entries' tab: {e}")

    # 2. Scan the "Demo Task Status" tab for transitions to "Next Steps"
    try:
        demo_rows = sheets.read_stage_data("Demo Task Status")
        next_steps_rows = sheets.read_stage_data("Next Steps")
        existing_next_names = set(r.get("Name", "").strip().lower() for r in next_steps_rows)
        
        # Build email lookup mapping from Entries tab
        entries_data = sheets.read_stage_data("Entries")
        name_to_email = {}
        for entry in entries_data:
            f_name = entry.get("First Name", "").strip()
            l_name = entry.get("Last Name", "").strip()
            full_name = f"{f_name} {l_name}".strip().lower()
            for k in entry.keys():
                if k.strip().lower() in ("contact email", "email", "email address"):
                    name_to_email[full_name] = str(entry[k]).strip()
                    break

        sync_count = 0
        max_syncs_per_sweep = 3
        for row in demo_rows:
            state_of_demo = str(row.get("State of demo task") or "").strip().lower()
            second_interview = str(row.get("2rd interview state") or "").strip().lower()
            status = str(row.get("Status") or "").strip().lower()
            
            eval_col = row.get("Demo Task Evaluation", "")
            name = ""
            if "Demo Task Evaluation - " in eval_col:
                name = eval_col.replace("Demo Task Evaluation - ", "").strip()
            elif "Task Evaluation - " in eval_col:
                name = eval_col.replace("Task Evaluation - ", "").strip()
                
            if not name:
                continue
                
            # Clean name for matching (e.g., "Berna Ozen .docx" -> "Berna Ozen")
            clean_name = name
            for suffix in (".docx", ".pdf", ".doc", ".zip"):
                if clean_name.lower().endswith(suffix):
                    clean_name = clean_name[:-len(suffix)].strip()
            # Strip trailing numbers or spaces
            clean_name = clean_name.rstrip("0123456789. ")
            
            # Trigger Condition: State of demo task is Evaluated, 2rd interview is Done, and Status is Coming
            if state_of_demo == "evaluated" and second_interview == "done" and status == "coming":
                if clean_name.lower() in existing_next_names or name.lower() in existing_next_names:
                    continue
                    
                if sync_count >= max_syncs_per_sweep:
                    print(f"\n[INFO] Safety limit reached ({max_syncs_per_sweep} syncs). Pausing further Next Steps syncs for this sweep.")
                    break
                    
                print(f"\n[TRIGGERED] Candidate '{name}' (Cleaned: '{clean_name}') in 'Demo Task Status' meets progression criteria: State of demo='Evaluated', 2rd interview='Done', Status='Coming'")
                print("Propagating to stage 'Next Steps'...")
                
                email = name_to_email.get(clean_name.lower(), "") or name_to_email.get(name.lower(), "")
                candidate_data = {
                    "Name": clean_name,  # Map cleaned name to Next Steps
                    "Role": row.get("Position", ""),
                    "Notes": row.get("Notes", ""),
                    "Email": email
                }
                
                # Invoke the LangGraph automation agent
                res = run_recruitment_sync(candidate_data, "Demo Task Status", "Next Steps")
                
                if res.get("sync_success", False):
                    print(f"[SUCCESS] Synced candidate '{name}' to 'Next Steps' tab.")
                    existing_next_names.add(name.lower())
                    sync_count += 1
                else:
                    print(f"[FAILED] Failed to sync candidate '{name}' to 'Next Steps'.")
    except Exception as e:
        print(f"Error scanning 'Demo Task Status' tab: {e}")

    # 3. Iterate through each original stage that can transition to a next stage
    for current_stage, transitions in STAGE_TRANSITIONS.items():
        try:
            candidates = sheets.read_stage_data(current_stage)
            for candidate in candidates:
                status = candidate.get("Status", "").strip()
                
                # Check if this status triggers a transition
                if status in transitions:
                    target_stage = transitions[status]
                    email = candidate.get("Email", "")
                    name = candidate.get("Name", "Unknown")
                    
                    print(f"\n[TRIGGERED] Candidate {name} ({email}) at stage '{current_stage}' has status '{status}'.")
                    print(f"Propagating to stage '{target_stage}'...")
                    
                    # Invoke the LangGraph automation agent
                    res = run_recruitment_sync(candidate, current_stage, target_stage)
                    
                    # If sync was successful, mark candidate as synced in current sheet
                    if res.get("sync_success", False):
                        new_status = f"Synced to {target_stage}"
                        sheets.update_candidate_status(current_stage, email, new_status)
                        print(f"[SUCCESS] Updated status for {email} to '{new_status}' in '{current_stage}' sheet.")
                    else:
                        print(f"[FAILED] Failed to sync candidate {email}. Refer to logs above.")
        except Exception as e:
            print(f"Error scanning stage '{current_stage}': {e}")

async def main_loop(run_once: bool):
    sheets = SheetsClient()
    
    # Log out-of-the-box mode info
    if sheets.mock_mode:
        print("💡 Running in MOCK MODE (local CSV files).")
        print(f"Mock sheets directory: {sheets.mock_dir}\n")
    else:
        print("💡 Running in LIVE MODE (Google Sheets API).")
        print(f"Spreadsheet ID: {sheets.sheet_id}\n")
        
    while True:
        try:
            scan_and_sync_pipeline(sheets)
        except Exception as e:
            print(f"Error during poll execution: {e}")
            
        if run_once:
            print("\nRun-once execution completed.")
            break
            
        print(f"Sleeping for {config.POLL_INTERVAL_SECONDS} seconds before next poll...")
        await asyncio.sleep(config.POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HR Recruitment Pipeline Automation Service")
    parser.add_argument("--once", action="store_true", help="Run a single scan and exit")
    args = parser.parse_args()
    
    try:
        asyncio.run(main_loop(args.once))
    except KeyboardInterrupt:
        print("\nService stopped by user.")
