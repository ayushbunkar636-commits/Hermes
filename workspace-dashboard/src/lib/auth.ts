import jwt from 'jsonwebtoken';
import { cookies } from 'next/headers';

const JWT_SECRET = process.env.JWT_SECRET || 'hermes-super-secret-key-123';

export async function signToken(payload: any) {
  return jwt.sign(payload, JWT_SECRET, { expiresIn: '7d' });
}

export async function verifyToken(token: string) {
  try {
    return jwt.verify(token, JWT_SECRET);
  } catch (e) {
    return null;
  }
}

export async function getSession(): Promise<any> {
  const cookieStore = await cookies();
  const token = cookieStore.get('hermes_token')?.value;
  if (!token) return null;
  return verifyToken(token) as any;
}
