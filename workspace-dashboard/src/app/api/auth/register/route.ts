import { NextResponse } from 'next/server';
import pool from '@/lib/db';
import bcrypt from 'bcryptjs';
import { signToken } from '@/lib/auth';

export async function POST(req: Request) {
  try {
    const { email, password } = await req.json();
    const hash = await bcrypt.hash(password, 10);
    
    const client = await pool.connect();
    
    // Check if exists
    const check = await client.query('SELECT id FROM users WHERE email = $1', [email]);
    if (check.rows.length > 0) {
      client.release();
      return NextResponse.json({ error: 'Email already in use' }, { status: 400 });
    }

    const result = await client.query(
      'INSERT INTO users (email, password_hash, role) VALUES ($1, $2, $3) RETURNING id, email, role',
      [email, hash, 'user']
    );
    
    const user = result.rows[0];
    
    // Create default settings for user
    await client.query('INSERT INTO system_settings (user_id) VALUES ($1)', [user.id]);
    
    client.release();

    const token = await signToken({ id: user.id, email: user.email, role: user.role });
    const response = NextResponse.json({ success: true, user });
    
    response.cookies.set('hermes_token', token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 7
    });

    return response;
  } catch (e: any) {
    console.error("REGISTER ERROR =>", e);
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
