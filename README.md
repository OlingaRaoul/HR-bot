# HR Recruitment Agent

This directory contains the codebase, assets, and documentation for the **Automated HR Recruitment AI Agent** at Startup Greece.

## Contents
- **Blueprint & Requirements**: See the blueprint details in this README.

---

## 1. Objective & Scope
The HR Recruitment Agent acts as an automated pipeline orchestrator. It monitors candidate stage transitions across spreadsheets and automates data propagation, eliminating manual copy-paste errors and maintaining database integrity.

---

## 2. Key Features
- **Single Source of Entry**: Candidate information is entered only once in the primary/inbound worksheet.
- **Automatic Pipeline Progression**: Automatically detects stage changes (e.g., from "Screening" to "Technical Interview") and populates the corresponding worksheet.
- **Bi-directional Sync**: Syncs notes and updates across stages to maintain consistency.
- **GDPR Compliance**: Real-time lookups without persistent storage of Personally Identifiable Information (PII) on the agent hosting server.

---

## 3. Recruitment Pipeline Stages
The agent tracks candidates through the following sequential worksheets:
1. `Inbound / Screening`
2. `Technical Interview`
3. `Cultural Fit Interview`
4. `Offer Stage`
5. `Onboarding`

---

## 4. Technical Stack (Recommended)
- **Data Layer**: Google Sheets API or Microsoft Graph API (OneDrive/SharePoint).
- **Automation / Orchestration**: Python-based script (FastAPI) or Make.com / n8n.
- **Notifications & Communication**: Slack Bolt SDK (for HR channel alerts) & Resend / SMTP for automated emails.
