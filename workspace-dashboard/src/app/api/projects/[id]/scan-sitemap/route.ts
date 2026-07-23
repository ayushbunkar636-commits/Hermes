import { NextResponse } from 'next/server';
import pool from '@/lib/db';
import { getSession } from '@/lib/auth';
import { exec } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execAsync = promisify(exec);

export const dynamic = 'force-dynamic';

// POST /api/projects/[id]/scan-sitemap
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { id } = await params;
  const client = await pool.connect();

  try {
    const result = await client.query('SELECT project_url FROM projects WHERE id = $1', [id]);
    const projectUrl = result.rows[0]?.project_url;

    if (!projectUrl) {
      return NextResponse.json({ error: 'Project not found' }, { status: 404 });
    }

    const scannerPath = path.join(process.cwd(), '..', 'workspace-bl-orchestrator', 'skills', 'search', 'sitemap_scanner.py');
    const pythonPath = 'python';

    // Run sitemap scanner as a background process (non-blocking)
    const cmd = `${pythonPath} "${scannerPath}" ${projectUrl} --project-id ${id}`;
    execAsync(cmd).catch(err => {
      console.warn(`[scan-sitemap] Background scan error:`, err.message);
    });

    return NextResponse.json({ message: `Sitemap scan started for ${projectUrl}` });
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  } finally {
    client.release();
  }
}

// GET /api/projects/[id]/scan-sitemap — return saved sitemap pages for this project
export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { id } = await params;
  const client = await pool.connect();

  try {
    const result = await client.query(
      `SELECT url, title, page_type, created_at FROM project_sitemaps WHERE project_id = $1 ORDER BY page_type, created_at DESC`,
      [id]
    );
    return NextResponse.json(result.rows, { headers: { 'Cache-Control': 'no-store' } });
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  } finally {
    client.release();
  }
}
