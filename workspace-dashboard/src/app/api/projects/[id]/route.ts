import { NextResponse } from 'next/server';
import pool from '@/lib/db';
import { getSession } from '@/lib/auth';

export const dynamic = 'force-dynamic';

export async function DELETE(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { id } = await params;
  const client = await pool.connect();

  try {
    await client.query('BEGIN');

    // Get the project URL before deleting (needed for opportunities table)
    const projResult = await client.query('SELECT project_url FROM projects WHERE id = $1', [id]);
    const projectUrl = projResult.rows[0]?.project_url;

    if (!projectUrl) {
      await client.query('ROLLBACK');
      return NextResponse.json({ error: 'Project not found' }, { status: 404 });
    }

    // ── Delete in correct FK order ────────────────────────────────────────────

    // 1. Tables that reference whitelist_sites
    await client.query(
      'DELETE FROM harvest_cursors WHERE whitelist_site_id IN (SELECT id FROM whitelist_sites WHERE project_id = $1)',
      [id]
    );
    await client.query(
      'DELETE FROM site_score_history WHERE whitelist_site_id IN (SELECT id FROM whitelist_sites WHERE project_id = $1)',
      [id]
    );
    await client.query(
      'DELETE FROM harvest_leads WHERE whitelist_site_id IN (SELECT id FROM whitelist_sites WHERE project_id = $1)',
      [id]
    );

    // 2. whitelist_sites itself
    await client.query('DELETE FROM whitelist_sites WHERE project_id = $1', [id]);

    // 3. Tables that reference projects directly
    await client.query('DELETE FROM harvest_leads WHERE project_id = $1', [id]);
    await client.query('DELETE FROM domain_candidates WHERE project_id = $1', [id]);
    await client.query('DELETE FROM pipeline_runs WHERE project_id = $1', [id]);
    await client.query('DELETE FROM query_stats WHERE project_id = $1', [id]);
    await client.query('DELETE FROM seen_opportunities WHERE project_id = $1', [id]);
    await client.query('DELETE FROM vocab_terms WHERE project_id = $1', [id]);
    
    // Extra Postgres tables
    await client.query('DELETE FROM project_sitemaps WHERE project_id = $1', [id]);
    await client.query('DELETE FROM project_competitors WHERE project_id = $1', [id]);
    await client.query('DELETE FROM project_vocab WHERE project_id = $1', [id]);
    await client.query('DELETE FROM domain_scores WHERE project_id = $1', [id]);
    await client.query('DELETE FROM leads WHERE project_id = $1', [id]);

    // 4. Opportunities and feedback events
    await client.query('DELETE FROM feedback_events WHERE opportunity_id IN (SELECT id FROM opportunities WHERE project_id = $1)', [id]);
    await client.query('DELETE FROM opportunities WHERE project_id = $1', [id]);
    
    await client.query('DELETE FROM feedback_events WHERE opportunity_id IN (SELECT id FROM opportunities WHERE project_url = $1)', [projectUrl]);
    await client.query('DELETE FROM opportunities WHERE project_url = $1', [projectUrl]);

    // 5. Finally delete the project itself
    await client.query('DELETE FROM projects WHERE id = $1', [id]);

    await client.query('COMMIT');

    return NextResponse.json({ message: 'Project deleted successfully' });
  } catch (err: any) {
    await client.query('ROLLBACK');
    return NextResponse.json({ error: err.message }, { status: 500 });
  } finally {
    client.release();
  }
}
