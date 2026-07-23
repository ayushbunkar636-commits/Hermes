# Deployment Checklist & Security Review

## Security Review 
- [x] **Authentication:** Custom JWT with 7-day expiry and `httpOnly` secure cookies.
- [x] **Rate Limiting:** Implemented API Rate Limiter in `/api/auth/login` (Max 5 attempts / 15 mins).
- [x] **Tenant Isolation:** All GET/POST requests enforced by `user_id = $session.id`.
- [x] **RBAC:** System health endpoints locked to `role === 'admin'`.
- [x] **Passwords:** Bcrypt hashing with Salt Factor 10.

## Production Deployment Checklist (Vercel + DigitalOcean)
1. **Database:** Deploy Postgres instance on Supabase. Disable pgbouncer if using Prisma, but since we use `pg`, standard pooling is fine.
2. **Next.js Frontend (Vercel):**
   - Push repository to GitHub.
   - Import project in Vercel.
   - Set Environment Variables:
     - `DATABASE_URL`
     - `JWT_SECRET`
   - Build Command: `npm run build`
3. **Python Daemon (DigitalOcean Droplet / AWS EC2):**
   - Provision Linux VM (Ubuntu 24.04).
   - Install Python 3.12, `psycopg2-binary`.
   - Setup Systemd Service:
     ```ini
     [Unit]
     Description=Hermes AI Daemon
     [Service]
     ExecStart=/usr/bin/python3 /path/to/nexus_daemon.py
     Environment="DATABASE_URL=..."
     Environment="GEMINI_API_KEY=..."
     Restart=always
     [Install]
     WantedBy=multi-user.target
     ```
   - Start daemon: `systemctl enable --now hermes`
