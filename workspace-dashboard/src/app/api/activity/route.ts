import { NextResponse } from 'next/server';
import fs from 'fs';
import os from 'os';
import path from 'path';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const logPath = path.join(os.homedir(), '.openclaw-backlink', 'data', 'activity_log.json');
    if (!fs.existsSync(logPath)) {
      return NextResponse.json({ events: [] });
    }
    const data = fs.readFileSync(logPath, 'utf-8');
    if (!data || data.trim() === '') {
      return NextResponse.json({ events: [] });
    }
    
    let events = [];
    try {
      events = JSON.parse(data);
    } catch (parseErr) {
      console.error("JSON parse error for activity log:", parseErr);
      return NextResponse.json({ events: [] });
    }
    
    if (!Array.isArray(events)) {
      events = [];
    }
    
    // Reverse the events so the newest is first
    const headers = {
      'Cache-Control': 'no-store, max-age=0',
    };
    return NextResponse.json({ events: events.reverse() }, { headers });
  } catch (err: any) {
    console.error("Error reading activity log:", err);
    return NextResponse.json({ events: [] });
  }
}
