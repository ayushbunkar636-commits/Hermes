const { Pool } = require('pg');
const pool = new Pool({ connectionString: 'postgresql://postgres:ayushbunkar100@db.mcbuijwyxmanqjjcanme.supabase.co:5432/postgres' });
const query = `
      SELECT 
        p.id, p.project_url, p.niche, p.config_json, p.created_at, p.status,
        COALESCE(
          json_agg(
            json_build_object('id', w.id, 'domain', w.domain, 'site_type', w.site_type)
          ) FILTER (WHERE w.id IS NOT NULL),
          '[]'::json
        ) as sources
      FROM projects p
      LEFT JOIN project_whitelist pw ON p.id = pw.project_id
      LEFT JOIN whitelist_sites w ON pw.site_id = w.id
      GROUP BY p.id
      ORDER BY p.created_at DESC
`;
pool.query(query).then(res => console.log("Success! Found rows:", res.rows.length)).catch(err => console.error("Error:", err.message)).finally(() => pool.end());
