import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Gemini configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Google Sheets Configuration
# If credentials or sheet ID is missing, we will default to mock mode to keep it running out-of-the-box
GOOGLE_SHEETS_CREDENTIALS_PATH = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_SHEET_WEBAPP_URL = os.getenv("GOOGLE_SHEET_WEBAPP_URL", "")

# Slack notifications
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# Operation parameters
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))
MOCK_MODE = os.getenv("MOCK_MODE", "True").lower() in ("true", "1", "yes")

# Pipeline Stages
PIPELINE_STAGES = [
    "Inbound_Screening",
    "Technical_Interview",
    "Cultural_Fit_Interview",
    "Offer_Stage",
    "Onboarding"
]

# Telegram parameters
TELEGRAM_IDLE_TIMEOUT_SECONDS = int(os.getenv("TELEGRAM_IDLE_TIMEOUT_SECONDS", "1800"))
