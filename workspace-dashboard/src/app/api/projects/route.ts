import { NextResponse } from 'next/server';
import pool from '@/lib/db';
import { getSession } from '@/lib/auth';

export const dynamic = 'force-dynamic';

export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  try {
    const client = await pool.connect();
    const result = await client.query(`
      SELECT 
        p.id, p.project_url, p.niche, p.config_json, p.created_at, p.status,
        COALESCE(
          json_agg(
            json_build_object('id', w.id, 'domain', w.domain)
          ) FILTER (WHERE w.id IS NOT NULL),
          '[]'::json
        ) as sources
      FROM projects p
      LEFT JOIN whitelist_sites w ON p.id = w.project_id
      GROUP BY p.id, p.project_url, p.niche, p.config_json, p.created_at, p.status
      ORDER BY p.created_at DESC
    `);
    client.release();
    
    return NextResponse.json({ data: result.rows }, {
      headers: { 'Cache-Control': 'no-store, no-cache, must-revalidate' }
    });
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  try {
    const { url, niche } = await request.json();
    
    if (!url || !niche) {
      return NextResponse.json({ error: 'URL and Niche are required' }, { status: 400 });
    }

    const client = await pool.connect();
    
    // Check if project already exists
    const existing = await client.query('SELECT id FROM projects WHERE project_url = $1', [url]);
    if (existing.rows.length > 0) {
      client.release();
      return NextResponse.json({ error: 'Project URL already exists' }, { status: 400 });
    }

    // Default configuration for a new project
    const default_config = {
      target_keywords: []
    };

    const result = await client.query(
      'INSERT INTO projects (project_url, niche, config_json) VALUES ($1, $2, $3) RETURNING *',
      [url, niche, JSON.stringify(default_config)]
    );
    
    client.release();

    return NextResponse.json({ data: result.rows[0], message: 'Project added successfully' });
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
