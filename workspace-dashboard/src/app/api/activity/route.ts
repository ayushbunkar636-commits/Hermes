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
    const events = JSON.parse(data);
    // Reverse the events so the newest is first
    return NextResponse.json({ events: events.reverse() });
  } catch (err: any) {
    console.error("Error reading activity log:", err);
    return NextResponse.json({ events: [] });
  }
}
