import { signToken, verifyToken } from './auth';

describe('Auth Service', () => {
  it('should sign and verify a JWT token', async () => {
    const payload = { id: 1, email: 'test@test.com', role: 'admin' };
    const token = await signToken(payload);
    
    expect(typeof token).toBe('string');
    
    const decoded = await verifyToken(token) as any;
    expect(decoded.id).toBe(1);
    expect(decoded.email).toBe('test@test.com');
    expect(decoded.role).toBe('admin');
  });

  it('should return null for invalid token', async () => {
    const result = await verifyToken('invalid.token.123');
    expect(result).toBeNull();
  });
});
