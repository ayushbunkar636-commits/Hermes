import { NextResponse } from 'next/server';
import pool from '@/lib/db';

export async function GET() {
  try {
    const client = await pool.connect();
    
    // Total
    const totalResult = await client.query('SELECT COUNT(*) FROM opportunities');
    const total = parseInt(totalResult.rows[0].count);

    // Grouped by status
    const statusResult = await client.query('SELECT status, COUNT(*) FROM opportunities GROUP BY status');
    let approved = 0;
    let rejected = 0;
    let pending = 0;
    
    statusResult.rows.forEach((row: any) => {
      if (row.status === 'approved') approved = parseInt(row.count);
      if (row.status === 'rejected') rejected = parseInt(row.count);
      if (row.status === 'pending') pending = parseInt(row.count);
    });

    // Averages
    const avgResult = await client.query('SELECT AVG(score_100) as avg_score, AVG(confidence) as avg_conf FROM opportunities WHERE score_100 IS NOT NULL');
    const averageScore = parseFloat(avgResult.rows[0].avg_score || 0).toFixed(1);
    const averageConfidence = parseFloat(avgResult.rows[0].avg_conf || 0).toFixed(1);

    // Chart Data (last 7 days)
    const chartResult = await client.query(`
      SELECT DATE(created_at) as date, COUNT(*) as count 
      FROM opportunities 
      WHERE created_at >= CURRENT_DATE - INTERVAL '6 days'
      GROUP BY DATE(created_at)
    `);

    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const chartData = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      const dateStr = d.toISOString().split('T')[0]; 
      
      const row = chartResult.rows.find((r: any) => {
        if (!r.date) return false;
        const rDate = new Date(r.date);
        return rDate.toISOString().split('T')[0] === dateStr;
      });

      chartData.push({
        name: days[d.getDay()],
        opps: row ? parseInt(row.count) : 0
      });
    }

    client.release();

    return NextResponse.json({
      total,
      approved,
      rejected,
      pending,
      averageScore: Number(averageScore),
      averageConfidence: Number(averageConfidence),
      chartData
    });
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
