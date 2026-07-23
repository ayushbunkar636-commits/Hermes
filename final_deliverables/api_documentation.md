# Hermes AI API Documentation

Base URL: `/api`
Authentication: JWT Cookie (`hermes_token`) required for all endpoints except `/auth/login` and `/auth/register`.

## 1. Auth API
- `POST /auth/login`: Accepts `{email, password}`. Sets HTTP-only cookie.
- `POST /auth/register`: Accepts `{email, password}`. Creates tenant account.
- `GET /auth/me`: Returns current session `{id, email, role}`.

## 2. Settings API
- `GET /settings`: Fetches the `system_settings` for the current `user_id`.
- `POST /settings`: Updates the `system_settings` for the current `user_id`. 
  - Payload: `{ min_score: number, ai_model: string, learning_enabled: boolean, ... }`

## 3. Opportunities API
- `GET /opportunities?status=[STATUS]`: Fetches opportunities for the logged-in user. Includes aggregation stats (total, pending, approved, rejected).

## 4. Notifications API
- `GET /notifications`: Fetches top 50 notifications for the current user.
- `POST /notifications`: Marks a notification as read. Payload `{ action: 'mark_read', id: number }`.

## 5. System Health API
- `GET /health`: Admin-only route. Returns realtime CPU, RAM load, Database Ping latency, and Python Scheduler Heartbeat age.
