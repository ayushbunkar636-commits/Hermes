import { NextResponse } from 'next/server';
import pool from '@/lib/db';
import bcrypt from 'bcryptjs';
import { signToken } from '@/lib/auth';

const rateLimit = new Map<string, { count: number; resetTime: number }>();

export async function POST(req: Request) {
  try {
    const ip = req.headers.get('x-forwarded-for') || '127.0.0.1';
    const now = Date.now();
    
    // Basic Rate Limiting: Max 5 attempts per 15 minutes
    const record = rateLimit.get(ip) || { count: 0, resetTime: now + 15 * 60 * 1000 };
    if (now > record.resetTime) {
      record.count = 0;
      record.resetTime = now + 15 * 60 * 1000;
    }
    if (record.count >= 5) {
      return NextResponse.json({ error: 'Too many login attempts. Try again later.' }, { status: 429 });
    }
    record.count++;
    rateLimit.set(ip, record);

    const { email, password } = await req.json();
    const client = await pool.connect();
    const result = await client.query('SELECT * FROM users WHERE email = $1', [email]);
    client.release();

    if (result.rows.length === 0) {
      return NextResponse.json({ error: 'User not found' }, { status: 401 });
    }

    const user = result.rows[0];
    const match = await bcrypt.compare(password, user.password_hash);

    if (!match) {
      return NextResponse.json({ error: 'Invalid password' }, { status: 401 });
    }

    const token = await signToken({ id: user.id, email: user.email, role: user.role });
    const response = NextResponse.json({ success: true, user: { id: user.id, email: user.email, role: user.role } });
    
    response.cookies.set('hermes_token', token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 7 // 7 days
    });

    return response;
  } catch (e: any) {
    console.error("LOGIN ERROR =>", e);
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
