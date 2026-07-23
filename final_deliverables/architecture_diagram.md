# Hermes SaaS Architecture

```mermaid
graph TD
    subgraph Frontend [Next.js (App Router)]
        UI[React UI / Tailwind]
        Middleware[JWT Auth Middleware]
        API[Next.js API Routes]
        UI --> Middleware
        Middleware --> API
    end

    subgraph Backend [Python Orchestrator (Multi-Tenant)]
        Daemon[nexus_daemon.py]
        Scraper[News / Reddit Scraper]
        AIEngine[Gemini AI Grader]
        Telegram[Telegram Bot]
        
        Daemon --> Scraper
        Daemon --> AIEngine
        Daemon --> Telegram
    end

    subgraph Database [Supabase Postgres]
        Users[(users)]
        Settings[(system_settings)]
        Opps[(opportunities)]
        Notifs[(notifications)]
    end

    API -- Reads/Writes --> Database
    Daemon -- Reads/Writes --> Database
    
    AIEngine -.-> GoogleVertex[Google Vertex AI]
```
