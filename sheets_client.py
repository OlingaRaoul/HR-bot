import os
import csv
import requests
from typing import List, Dict, Any
from google.oauth2 import service_account
from googleapiclient.discovery import build
import config

class SheetsClient:
    """
    Unified client for Google Sheets (Web App / Service Account) and local CSV Mock Sheets.
    """
    def __init__(self):
        self.mock_mode = config.MOCK_MODE
        self.credentials_path = config.GOOGLE_SHEETS_CREDENTIALS_PATH
        self.sheet_id = config.GOOGLE_SHEET_ID
        self.webapp_url = config.GOOGLE_SHEET_WEBAPP_URL
        self.mock_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data")
        
        # Ensure mock dir exists
        if self.mock_mode and not os.path.exists(self.mock_dir):
            os.makedirs(self.mock_dir)
            
        self.service = None
        self.use_webapp = bool(self.webapp_url)
        
        if self.use_webapp:
            print(f"Using Google Apps Script Web App Mode (Free bypass). URL: {self.webapp_url}")
            self.mock_mode = False
        elif not self.mock_mode:
            try:
                if not os.path.exists(self.credentials_path):
                    print(f"Warning: Credentials file not found at {self.credentials_path}. Falling back to MOCK_MODE.")
                    self.mock_mode = True
                else:
                    scopes = ['https://www.googleapis.com/auth/spreadsheets']
                    creds = service_account.Credentials.from_service_account_file(
                        self.credentials_path, scopes=scopes
                    )
                    self.service = build('sheets', 'v4', credentials=creds)
                    print("Google Sheets API connection established successfully.")
            except Exception as e:
                print(f"Failed to connect to Google Sheets API: {e}. Falling back to MOCK_MODE.")
                self.mock_mode = True

    def _get_mock_filepath(self, stage_name: str) -> str:
        return os.path.join(self.mock_dir, f"{stage_name}.csv")

    def read_stage_data(self, stage_name: str) -> List[Dict[str, str]]:
        """Reads row data from the specified stage spreadsheet."""
        if self.use_webapp:
            try:
                r = requests.get(f"{self.webapp_url}?action=read&sheet={stage_name}", timeout=45)
                if r.status_code == 200:
                    res_json = r.json()
                    if res_json.get("status") == "success":
                        return res_json.get("data", [])
                print(f"Web App read failed for '{stage_name}': {r.text}")
                return []
            except Exception as e:
                print(f"Error reading via Web App '{stage_name}': {e}")
                return []

        if self.mock_mode:
            filepath = self._get_mock_filepath(stage_name)
            if not os.path.exists(filepath):
                # Create empty template if not exists
                headers = ["Candidate_ID", "Name", "Email", "Role", "Status", "Notes"]
                with open(filepath, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(headers)
                return []
            
            with open(filepath, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                return list(reader)
        else:
            try:
                # Read from Google Sheets range (Stage name matches Sheet/Tab name)
                result = self.service.spreadsheets().values().get(
                    spreadsheetId=self.sheet_id,
                    range=f"'{stage_name}'!A:Z"
                ).execute()
                values = result.get('values', [])
                if not values:
                    return []
                
                headers = values[0]
                rows = []
                for val_row in values[1:]:
                    # Align row values to headers (fill empty strings if row is short)
                    row_dict = {}
                    for i, h in enumerate(headers):
                        row_dict[h] = val_row[i] if i < len(val_row) else ""
                    rows.append(row_dict)
                return rows
            except Exception as e:
                print(f"Error reading from Google Sheet '{stage_name}': {e}")
                return []

    def append_candidate_to_stage(self, stage_name: str, candidate_data: Dict[str, str]) -> bool:
        """Appends candidate details to the target stage sheet."""
        if self.use_webapp:
            try:
                payload = {
                    "action": "append",
                    "sheet": stage_name,
                    "data": candidate_data
                }
                r = requests.post(self.webapp_url, json=payload, timeout=45)
                if r.status_code == 200:
                    res_json = r.json()
                    return res_json.get("status") == "success"
                print(f"Web App append failed for '{stage_name}': {r.text}")
                return False
            except Exception as e:
                print(f"Error appending via Web App to '{stage_name}': {e}")
                return False

        if self.mock_mode:
            filepath = self._get_mock_filepath(stage_name)
            existing_data = self.read_stage_data(stage_name)
            
            # Make sure we have headers
            headers = ["Candidate_ID", "Name", "Email", "Role", "Status", "Notes"]
            if existing_data:
                headers = list(existing_data[0].keys())
                
            # Check for duplicate email in this stage
            for row in existing_data:
                if row.get("Email") == candidate_data.get("Email"):
                    # Candidate already in this stage
                    return True
            
            with open(filepath, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writerow(candidate_data)
            return True
        else:
            try:
                # Get the headers of the target sheet first to match fields
                existing_rows = self.read_stage_data(stage_name)
                headers = []
                if existing_rows:
                    headers = list(existing_rows[0].keys())
                else:
                    # Let's get header row values from sheet cell range A1:Z1
                    header_res = self.service.spreadsheets().values().get(
                        spreadsheetId=self.sheet_id,
                        range=f"'{stage_name}'!A1:Z1"
                    ).execute()
                    val = header_res.get('values', [])
                    if val:
                        headers = val[0]
                    else:
                        headers = ["Candidate_ID", "Name", "Email", "Role", "Status", "Notes"]
                        # Write headers first
                        self.service.spreadsheets().values().append(
                            spreadsheetId=self.sheet_id,
                            range=f"'{stage_name}'!A1",
                            valueInputOption='USER_ENTERED',
                            body={'values': [headers]}
                        ).execute()

                # Align candidate_data to headers
                row_to_append = [candidate_data.get(h, "") for h in headers]
                
                # Check for duplicate
                for r in existing_rows:
                    if r.get("Email") == candidate_data.get("Email"):
                        return True
                
                self.service.spreadsheets().values().append(
                    spreadsheetId=self.sheet_id,
                    range=f"'{stage_name}'!A:A",
                    valueInputOption='USER_ENTERED',
                    insertDataOption='INSERT_ROWS',
                    body={'values': [row_to_append]}
                ).execute()
                return True
            except Exception as e:
                print(f"Error appending candidate to Google Sheet '{stage_name}': {e}")
                return False

    def update_candidate_status(self, stage_name: str, email: str, new_status: str) -> bool:
        """Updates status of a candidate in a specific stage sheet."""
        if self.use_webapp:
            try:
                payload = {
                    "action": "update_status",
                    "sheet": stage_name,
                    "email": email,
                    "status": new_status
                }
                r = requests.post(self.webapp_url, json=payload, timeout=45)
                if r.status_code == 200:
                    res_json = r.json()
                    return res_json.get("status") == "success"
                print(f"Web App status update failed for '{stage_name}': {r.text}")
                return False
            except Exception as e:
                print(f"Error updating status via Web App in '{stage_name}': {e}")
                return False

        if self.mock_mode:
            filepath = self._get_mock_filepath(stage_name)
            rows = self.read_stage_data(stage_name)
            updated = False
            for row in rows:
                if row.get("Email") == email:
                    row["Status"] = new_status
                    updated = True
            
            if updated and rows:
                headers = list(rows[0].keys())
                with open(filepath, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=headers)
                    writer.writeheader()
                    writer.writerows(rows)
            return updated
        else:
            try:
                # Read all values including header to locate column and row
                res = self.service.spreadsheets().values().get(
                    spreadsheetId=self.sheet_id,
                    range=f"'{stage_name}'!A:Z"
                ).execute()
                values = res.get('values', [])
                if not values:
                    return False
                
                headers = values[0]
                if "Email" not in headers or "Status" not in headers:
                    return False
                
                email_col_idx = headers.index("Email")
                status_col_idx = headers.index("Status")
                
                # Find matching row
                for idx, val_row in enumerate(values[1:], start=2): # 1-indexed header is row 1
                    if len(val_row) > email_col_idx and val_row[email_col_idx] == email:
                        # Col index to A1 notation letter
                        col_letter = chr(65 + status_col_idx) # Works for A-Z
                        cell_range = f"'{stage_name}'!{col_letter}{idx}"
                        
                        self.service.spreadsheets().values().update(
                            spreadsheetId=self.sheet_id,
                            range=cell_range,
                            valueInputOption='USER_ENTERED',
                            body={'values': [[new_status]]}
                        ).execute()
                        return True
                return False
            except Exception as e:
                print(f"Error updating status in Google Sheet '{stage_name}': {e}")
                return False
