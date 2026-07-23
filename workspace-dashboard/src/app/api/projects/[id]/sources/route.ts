import { NextResponse } from 'next/server';
import pool from '@/lib/db';
import { getSession } from '@/lib/auth';

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  try {
    const { domain, site_type = 'forum', scan_priority = 10 } = await request.json();
    const resolvedParams = await params;
    const projectId = resolvedParams.id;

    if (!domain) {
      return NextResponse.json({ error: 'Domain is required' }, { status: 400 });
    }

    const client = await pool.connect();
    
    try {
      await client.query('BEGIN');
      
      // Insert or get site
      let siteResult = await client.query(
        'SELECT id FROM whitelist_sites WHERE project_id = $1 AND domain = $2',
        [projectId, domain]
      );
      
      let siteId;
      if (siteResult.rows.length === 0) {
        siteResult = await client.query(
          'INSERT INTO whitelist_sites (project_id, domain, status, scan_priority) VALUES ($1, $2, $3, $4) RETURNING id',
          [projectId, domain, 'active', scan_priority]
        );
      }
      siteId = siteResult.rows[0].id;
      
      await client.query('COMMIT');
      return NextResponse.json({ success: true, site_id: siteId });
    } catch (err) {
      await client.query('ROLLBACK');
      throw err;
    } finally {
      client.release();
    }
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
