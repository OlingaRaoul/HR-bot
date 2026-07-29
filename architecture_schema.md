# AI Agent Swarm Orchestration Architecture

![AI Agent Swarm Orchestration Architecture Diagram](file:///Users/olingajoseph/Documents/My%20projects/startup%20greece/HR/agent_orchestration_architecture.png)

This document describes the architectural flow and agentic orchestration of the **HR Recruitment Pipeline Automation** at Startup Greece.

---

## 1. System Overview

The system uses a **polling trigger** to monitor state transitions in Google Sheets via a Google Apps Script Web App, then runs a stateful **LangGraph pipeline** (powered by LangChain and Gemini 3.5 Flash) to validate candidates, structure profiles, sync data to corresponding stages, and notify HR staff.

```mermaid
graph TD
    %% System boundaries & actors
    subgraph Google Sheets Workspace
        S1[Entries Sheet]
        S2[Demo Task Status Sheet]
        S3[Other Stage Sheets]
    end
    
    subgraph Python Automation Service
        P1[main.py: Loop Poller]
        P2[sheets_client.py: WebApp Client]
        
        subgraph LangGraph Agent Orchestrator
            node_val[Node: validate_candidate_profile]
            node_sync[Node: sync_candidate_to_next_stage]
            node_notify[Node: notify_pipeline_update]
            
            LLM[Gemini 3.5 Flash via ChatOpenAI]
        end
    end
    
    subgraph Communications
        Slack[Slack HR Channel Webhook]
    end

    %% Process flow
    P1 -->|1. Periodic Scan| P2
    P2 -->|2. Read Rows| S1
    S1 -->|3. Data returned| P2
    P2 -->|4. Detect Trigger Status| P1
    
    P1 -->|5. Invoke Graph| node_val
    node_val -->|6. Profile Extraction & Validation| LLM
    LLM -->|7. Structured CandidateProfile| node_val
    
    node_val -->|8. Validation Passed| node_sync
    node_sync -->|9. Write mapping data| P2
    P2 -->|10. Append Row / Update Status| S2
    
    node_sync --> node_notify
    node_val -->|Validation Failed| node_notify
    
    node_notify -->|11. Post log summary| Slack
```

---

## 2. Component Descriptions

### A. Poller (`main.py`)
- Executes continuously (or once with `--once` flag).
- Reads candidate rows from the primary **`Entries`** tab.
- Filters candidates based on trigger status (`Status` = `OPEN`/`Pending` and `Stage` = `Demo Task`).
- Maintains an in-memory name lookup from the target sheet (`Demo Task Status`) to prevent duplicates.

### B. Client Driver (`sheets_client.py`)
- Dynamically acts as the transport layer.
- Handles requests through the **Google Apps Script Web App** (HTTP REST GET/POST) to read, append, and update rows.
- Safely falls back to local mock CSV worksheets if the Web App is offline.

### C. LangGraph State Workflow (`agent.py`)
LangGraph structures the lifecycle of a candidate sync sweep into state nodes:

1. **State Definition (`CandidateState`)**:
   Holds the candidate row details, current and target stages, validation statuses, validation profiles, and log registries.
2. **Validation Node (`validate_candidate_profile`)**:
   Extracts candidate fields (Name, Email, Role) dynamically to support split name columns. Invokes the Gemini LLM with a Pydantic `CandidateProfile` model schema to clean, standardize, and summarize the candidate profile.
3. **Sync Node (`sync_candidate_to_next_stage`)**:
   Maps candidate fields to target worksheet headers (e.g. constructing columns for `Demo Task Status` like `Demo Task Evaluation = Demo Task Evaluation - Name`).
4. **Notification Node (`notify_pipeline_update`)**:
   Consolidates execution logs and posts a formatted markdown message to the team's Slack channel webhook.

---

## 3. Future Multi-Agent Expansion (Orchestration Swarm)

As the HR pipeline matures, we can transition this single-agent graph into a **Multi-Agent Swarm** where specialized agents cooperate:

```mermaid
graph TD
    Manager[Recruitment Swarm Supervisor]
    
    A_Eval[Demo Task Evaluator Agent]
    A_Sched[Interview Scheduler Agent]
    A_Outreach[Outreach Email Agent]
    
    Manager -->|Delegates Evaluation| A_Eval
    Manager -->|Delegates Scheduling| A_Sched
    Manager -->|Delegates Communications| A_Outreach
    
    A_Eval -->|Reads submitted git/drive links| Manager
    A_Sched -->|Proposes slots based on HR calendar| Manager
    A_Outreach -->|Drafts tailored follow-ups| Manager
```

1. **Recruitment Supervisor Agent**:
   Tracks the overarching stage transitions and delegates candidate profiles to subagents.
2. **Demo Task Evaluator Agent**:
   Monitors submission folders or links, reviews candidate code/demo task submissions, and updates evaluations.
3. **Interview Scheduler Agent**:
   Interacts with calendars to coordinate interview dates and updates worksheets.
4. **Outreach Agent**:
   Drafts personalized stage transition emails or invitations and requests human review in Slack before sending.
