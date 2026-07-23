Backlink Agent — Windows deploy (Docker Desktop)
================================================

Deploy folder (after extract):
  C:\Users\TheOne\Downloads\backlink-agent-deploy\backlink-agent-deploy

Prerequisite: news-agent Bifrost must be running on port 8888.
  Start "Start News Agent.bat" on desktop FIRST, then Backlink.

First install:
  1. Extract zip to Downloads\backlink-agent-deploy  2. Copy .env.example to .env
  3. Double-click deploy.bat ONCE
  4. Copy "Start Backlink Agent.bat" to Desktop

Daily use (after reboot):
  1. Start News Agent.bat  (Bifrost + news)
  2. Start Backlink Agent.bat

URLs:
  Backlink UI:  http://localhost:19789
  Bifrost UI:   http://localhost:8888  (from news-agent)

Do NOT run deploy.bat again on a live machine.
