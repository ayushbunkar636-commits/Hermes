const { Pool } = require('pg');
require('dotenv').config({ path: '.env.local' });

const pool = new Pool({
  connectionString: 'postgresql://postgres.mcbuijwyxmanqjjcanme:ayushbunkar100@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres?pgbouncer=true',
});

async function migrate() {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    // 1. Create Users Table
    await client.query(`
      CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      );
    `);

    // 2. Insert Admin if not exists
    await client.query(`
      INSERT INTO users (email, password_hash, role) 
      VALUES ('admin@hermes.com', '$2a$10$YyO..J2N.E1Zq1k/K5N5H.5vOqZ/k1Q2k1Q2k1Q2k1Q2k1Q2k1Q2k', 'admin')
      ON CONFLICT (email) DO NOTHING;
    `);
    
    // Get admin ID
    const adminRes = await client.query("SELECT id FROM users WHERE email = 'admin@hermes.com'");
    const adminId = adminRes.rows[0].id;

    // 3. Alter existing tables to add user_id (if not exists)
    const tables = ['system_settings', 'notifications', 'opportunities', 'projects'];
    
    for (const table of tables) {
      try {
        const tableCheck = await client.query(`
          SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = $1
          );
        `, [table]);
        
        if (tableCheck.rows[0].exists) {
            await client.query(`
            ALTER TABLE ${table} 
            ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
            `);
            
            await client.query(`
            UPDATE ${table} SET user_id = $1 WHERE user_id IS NULL;
            `, [adminId]);
        }
      } catch (err) {
        console.log(`Error altering ${table}:`, err.message);
      }
    }

    await client.query(`
        CREATE TABLE IF NOT EXISTS system_settings (
          id SERIAL PRIMARY KEY,
          user_id INTEGER REFERENCES users(id),
          min_score INTEGER DEFAULT 80,
          platforms TEXT DEFAULT '["reddit", "news"]',
          reminder_intervals_hours TEXT DEFAULT '{"standard":48, "strong":72, "archive":168}',
          ai_model TEXT DEFAULT 'vertex/gemini-3.1-flash-lite',
          schedule_frequency_minutes INTEGER DEFAULT 60,
          telegram_formatting TEXT DEFAULT '',
          business_thresholds TEXT DEFAULT '{}',
          learning_enabled INTEGER DEFAULT 1,
          last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    `);
    
    await client.query(`
        INSERT INTO system_settings (user_id) 
        SELECT $1 WHERE NOT EXISTS (SELECT 1 FROM system_settings WHERE user_id = $1);
    `, [adminId]);

    await client.query(`
        CREATE TABLE IF NOT EXISTS notifications (
          id SERIAL PRIMARY KEY,
          user_id INTEGER REFERENCES users(id),
          type TEXT NOT NULL,
          title TEXT NOT NULL,
          message TEXT NOT NULL,
          is_read INTEGER DEFAULT 0,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    `);

    await client.query('COMMIT');
    console.log('Migration complete. Multi-tenant schema ready.');
  } catch (e) {
    await client.query('ROLLBACK');
    console.error('Migration failed:', e);
  } finally {
    client.release();
    pool.end();
  }
}

migrate();
