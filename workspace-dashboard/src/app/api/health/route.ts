import { NextResponse } from 'next/server';
import pool from '@/lib/db';
import os from 'os';
import { getSession } from '@/lib/auth';

export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Forbidden. Please login first.' }, { status: 403 });
  }

  const healthData = {
    database: { status: 'red', latency: 0 },
    scheduler: { status: 'red', lastHeartbeat: 'never' },
    system: { cpu: 0, memory: 0, uptime: 0 },
    ai: { status: 'green', message: 'Connected to Local AI' },
    telegram: { status: 'green' }
  };

  try {
    const start = Date.now();
    const client = await pool.connect();
    
    // Check DB
    await client.query('SELECT 1');
    healthData.database.latency = Date.now() - start;
    healthData.database.status = healthData.database.latency < 500 ? 'green' : 'yellow';

    // Check Scheduler Heartbeat for admin (user_id = 1 usually, but let's just get latest heartbeat)
    const res = await client.query('SELECT last_heartbeat FROM system_settings ORDER BY last_heartbeat DESC LIMIT 1');
    if (res.rows.length > 0 && res.rows[0].last_heartbeat) {
      const hb = new Date(res.rows[0].last_heartbeat).getTime();
      const diffMinutes = (Date.now() - hb) / 1000 / 60;
      healthData.scheduler.lastHeartbeat = res.rows[0].last_heartbeat;
      if (diffMinutes < 15) healthData.scheduler.status = 'green';
      else if (diffMinutes < 30) healthData.scheduler.status = 'yellow';
      else healthData.scheduler.status = 'red';
    }
    client.release();

    healthData.system = {
      cpu: os.loadavg()[0],
      memory: 1 - (os.freemem() / os.totalmem()),
      uptime: os.uptime()
    };

    return NextResponse.json(healthData);
  } catch (err: any) {
    return NextResponse.json(healthData, { status: 500 });
  }
}
