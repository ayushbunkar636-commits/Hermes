import { NextResponse } from 'next/server';
import pool from '@/lib/db';
import { getSession } from '@/lib/auth';

export async function GET() {
  try {
    const session = await getSession();
    if (!session) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

    const client = await pool.connect();
    const result = await client.query('SELECT * FROM system_settings WHERE user_id = $1', [session.id]);
    client.release();

    if (result.rows.length === 0) {
      return NextResponse.json({ error: 'Settings not found' }, { status: 404 });
    }

    const row = result.rows[0];
    return NextResponse.json({
      min_score: row.min_score,
      schedule_frequency_minutes: row.schedule_frequency_minutes,
      learning_enabled: row.learning_enabled === 1,
      platforms: typeof row.platforms === 'string' ? JSON.parse(row.platforms) : row.platforms,
      reminder_intervals_hours: typeof row.reminder_intervals_hours === 'string' ? JSON.parse(row.reminder_intervals_hours) : row.reminder_intervals_hours,
      ai_model: row.ai_model,
      last_heartbeat: row.last_heartbeat
    });
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}

export async function POST(req: Request) {
  try {
    const session = await getSession();
    if (!session) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

    const body = await req.json();
    const client = await pool.connect();

    const updates = [];
    const values = [];
    let idx = 1;

    for (const [k, v] of Object.entries(body)) {
      if (['min_score', 'schedule_frequency_minutes', 'learning_enabled', 'ai_model'].includes(k)) {
        updates.push(`${k} = $${idx}`);
        values.push(k === 'learning_enabled' ? (v ? 1 : 0) : v);
        idx++;
      } else if (['platforms', 'reminder_intervals_hours', 'business_thresholds'].includes(k)) {
        updates.push(`${k} = $${idx}`);
        values.push(JSON.stringify(v));
        idx++;
      }
    }

    if (updates.length > 0) {
      values.push(session.id);
      await client.query(
        `UPDATE system_settings SET ${updates.join(', ')} WHERE user_id = $${idx}`,
        values
      );
    }

    client.release();
    return NextResponse.json({ success: true });
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
