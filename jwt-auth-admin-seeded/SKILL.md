---
name: "JWT Auth (admin-seeded)"
description: "Drop-in JWT authentication for NestJS+React internal tools. Email+password login, access+refresh token rotation, bcrypt password hashing, role-based guards, an admin-seed script (no public signup), frontend AuthContext + ProtectedRoute + axios refresh-interceptor. Use when starting an internal team app where accounts are admin-created."
---

# JWT Auth (admin-seeded)

## What This Skill Does

Replaces the "I'll just write JWT auth real quick" temptation with a tested 12-file pattern that handles the parts that always bite: refresh-token rotation, bcrypt cost, ts-config issues, axios interceptor races, role guards, self-protection on user mutations, and a seed-admin script so production never starts without an admin account.

**Authentication flow:** email+password → JWT access (15m) + refresh token (7d). Refresh rotates (revoke old, issue new) on every use. No public signup — accounts come from the seed script or an admin's CRUD UI (see `users-admin-page` skill).

## When to Use

- Internal tools where you control the user list (no public signup needed).
- NestJS backend + React/Vite frontend.
- Mongo as the primary store (Mongoose schemas; adaptable to Prisma+Postgres with renaming).
- The very first thing you build in a new project — every subsequent module depends on this.

## When NOT to Use

- Public-facing apps with self-signup, email verification, social login. Use `api-platform` for dual-auth or graft on Auth.js.
- Apps where session-based cookie auth is required by stack convention (some SSR setups).
- Microservices behind a gateway that handles auth — use the gateway's identity instead.

---

## File Tree

```
backend/
├── src/
│   └── auth/
│       ├── auth.module.ts
│       ├── auth.controller.ts
│       ├── auth.service.ts
│       ├── jwt.strategy.ts
│       ├── decorators/
│       │   ├── current-user.decorator.ts
│       │   └── roles.decorator.ts
│       ├── guards/
│       │   ├── jwt-auth.guard.ts
│       │   └── roles.guard.ts
│       ├── dto/
│       │   ├── login.dto.ts
│       │   └── refresh.dto.ts
│       └── schemas/
│           ├── user.schema.ts
│           └── refresh-token.schema.ts
├── scripts/
│   └── seed-admin.ts
└── .env.example       # JWT_*, ADMIN_EMAIL, ADMIN_PASSWORD

frontend/src/
├── pages/Login.tsx
├── components/ProtectedRoute.tsx
└── services/
    ├── api/base.ts            # axios + refresh interceptor
    └── auth/AuthContext.tsx
```

## Dependencies

```bash
# Backend
npm install --legacy-peer-deps \
  @nestjs/jwt @nestjs/passport @nestjs/mongoose \
  passport passport-jwt bcrypt class-validator class-transformer
npm install --save-dev --legacy-peer-deps @types/bcrypt @types/passport-jwt ts-node

# Frontend
npm install --save axios @mantine/form
```

---

## Backend

### `.env.example`

```
NODE_ENV=development
PORT=3000
MONGO_URI=mongodb://127.0.0.1:27017/your-app

# Generate each with: openssl rand -hex 64
JWT_ACCESS_SECRET=
JWT_REFRESH_SECRET=
JWT_ACCESS_TTL=15m
JWT_REFRESH_TTL=7d

FRONTEND_URL=http://localhost:5173

# Used by `npm run seed:admin`
ADMIN_EMAIL=
ADMIN_PASSWORD=
```

### `schemas/user.schema.ts`

```ts
import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { HydratedDocument } from 'mongoose';

export type UserRole = 'admin' | 'member';
export type UserDocument = HydratedDocument<User>;

@Schema({ timestamps: true })
export class User {
  @Prop({ required: true, unique: true, lowercase: true, trim: true })
  email!: string;

  @Prop({ required: true })
  passwordHash!: string;

  @Prop({ required: true, enum: ['admin', 'member'], default: 'member' })
  role!: UserRole;

  @Prop({ default: false })
  emailVerified!: boolean;

  @Prop({ default: true })
  active!: boolean;       // soft-delete via active=false; login rejects when false

  @Prop()
  displayName?: string;

  @Prop()
  lastLoginAt?: Date;
}

export const UserSchema = SchemaFactory.createForClass(User);
```

### `schemas/refresh-token.schema.ts`

```ts
import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import { Document, Types } from 'mongoose';

export type RefreshTokenDocument = Document & RefreshToken;

@Schema({ timestamps: true })
export class RefreshToken {
  @Prop({ type: Types.ObjectId, ref: 'User', required: true, index: true })
  userId!: Types.ObjectId;

  @Prop({ required: true, index: true })
  tokenHash!: string;       // sha256 of the raw refresh token

  @Prop({ required: true })
  expiresAt!: Date;

  @Prop({ default: false })
  revoked!: boolean;
}

export const RefreshTokenSchema = SchemaFactory.createForClass(RefreshToken);
```

**Why hash refresh tokens:** if your DB is dumped, raw tokens leak. Sha256 of the raw value is enough — refresh tokens are high-entropy random bytes, not user passwords, so bcrypt is unnecessary overhead.

### `dto/login.dto.ts`

```ts
import { IsEmail, IsString, MaxLength, MinLength } from 'class-validator';

export class LoginDto {
  @IsEmail() email!: string;
  @IsString() @MinLength(6) @MaxLength(128)
  password!: string;
}
```

### `dto/refresh.dto.ts`

```ts
import { IsString, Length } from 'class-validator';

export class RefreshDto {
  @IsString() @Length(32, 256)
  refreshToken!: string;
}
```

### `jwt.strategy.ts`

```ts
import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { PassportStrategy } from '@nestjs/passport';
import { ExtractJwt, Strategy } from 'passport-jwt';

export interface JwtPayload {
  sub: string;
  email: string;
  role: 'admin' | 'member';
}

@Injectable()
export class JwtStrategy extends PassportStrategy(Strategy) {
  constructor(config: ConfigService) {
    super({
      jwtFromRequest: ExtractJwt.fromAuthHeaderAsBearerToken(),
      secretOrKey: config.getOrThrow<string>('JWT_ACCESS_SECRET'),
      ignoreExpiration: false,
    });
  }

  async validate(payload: JwtPayload): Promise<JwtPayload> {
    return payload;     // attached as req.user; controllers see {sub, email, role}
  }
}
```

### `guards/jwt-auth.guard.ts`

```ts
import { Injectable } from '@nestjs/common';
import { AuthGuard } from '@nestjs/passport';

@Injectable()
export class JwtAuthGuard extends AuthGuard('jwt') {}
```

### `guards/roles.guard.ts` + `decorators/roles.decorator.ts`

```ts
// roles.decorator.ts
import { SetMetadata } from '@nestjs/common';
export const ROLES_KEY = 'roles';
export const Roles = (...roles: ('admin' | 'member')[]) => SetMetadata(ROLES_KEY, roles);
```

```ts
// roles.guard.ts
import { CanActivate, ExecutionContext, ForbiddenException, Injectable } from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { ROLES_KEY } from '../decorators/roles.decorator';

@Injectable()
export class RolesGuard implements CanActivate {
  constructor(private reflector: Reflector) {}
  canActivate(ctx: ExecutionContext): boolean {
    const required = this.reflector.getAllAndOverride<string[]>(ROLES_KEY, [ctx.getHandler(), ctx.getClass()]);
    if (!required || required.length === 0) return true;
    const { user } = ctx.switchToHttp().getRequest();
    if (!user || !required.includes(user.role)) throw new ForbiddenException();
    return true;
  }
}
```

### `decorators/current-user.decorator.ts`

```ts
import { createParamDecorator, ExecutionContext } from '@nestjs/common';

export const CurrentUser = createParamDecorator(
  (_data: unknown, ctx: ExecutionContext) => ctx.switchToHttp().getRequest().user,
);
```

### `auth.service.ts`

```ts
import { Injectable, UnauthorizedException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { JwtService } from '@nestjs/jwt';
import { InjectModel } from '@nestjs/mongoose';
import * as bcrypt from 'bcrypt';
import * as crypto from 'crypto';
import { Model, Types } from 'mongoose';
import { JwtPayload } from './jwt.strategy';
import { RefreshToken, RefreshTokenDocument } from './schemas/refresh-token.schema';
import { User, UserDocument } from './schemas/user.schema';

@Injectable()
export class AuthService {
  constructor(
    @InjectModel(User.name) private readonly userModel: Model<UserDocument>,
    @InjectModel(RefreshToken.name) private readonly refreshModel: Model<RefreshTokenDocument>,
    private readonly jwt: JwtService,
    private readonly config: ConfigService,
  ) {}

  async login(email: string, password: string) {
    const user = await this.userModel.findOne({ email: email.toLowerCase().trim() });
    if (!user) throw new UnauthorizedException('Invalid credentials');
    if (user.active === false) throw new UnauthorizedException('Account deactivated');
    const ok = await bcrypt.compare(password, user.passwordHash);
    if (!ok) throw new UnauthorizedException('Invalid credentials');
    user.lastLoginAt = new Date();
    await user.save();
    return this.issueTokens(user);
  }

  async refresh(refreshToken: string) {
    const tokenHash = this.hashToken(refreshToken);
    const stored = await this.refreshModel.findOne({ tokenHash, revoked: false });
    if (!stored) throw new UnauthorizedException('Invalid refresh token');
    if (stored.expiresAt.getTime() < Date.now()) throw new UnauthorizedException('Refresh token expired');
    const user = await this.userModel.findById(stored.userId);
    if (!user) throw new UnauthorizedException('User no longer exists');
    stored.revoked = true;          // ROTATE: revoke old, issue new pair
    await stored.save();
    return this.issueTokens(user);
  }

  async logout(refreshToken: string) {
    const tokenHash = this.hashToken(refreshToken);
    await this.refreshModel.updateOne({ tokenHash }, { $set: { revoked: true } });
    return { success: true };
  }

  private async issueTokens(user: UserDocument) {
    const payload: JwtPayload = { sub: String(user._id), email: user.email, role: user.role };
    const accessToken = await this.jwt.signAsync(payload, {
      secret: this.config.getOrThrow<string>('JWT_ACCESS_SECRET'),
      expiresIn: this.config.get<string>('JWT_ACCESS_TTL', '15m'),
    });
    const refreshToken = crypto.randomBytes(48).toString('hex');
    await this.refreshModel.create({
      userId: new Types.ObjectId(String(user._id)),
      tokenHash: this.hashToken(refreshToken),
      expiresAt: new Date(Date.now() + this.parseTtlMs(this.config.get<string>('JWT_REFRESH_TTL', '7d'))),
    });
    return {
      accessToken, refreshToken,
      user: { id: String(user._id), email: user.email, role: user.role, displayName: user.displayName },
    };
  }

  private hashToken(token: string): string {
    return crypto.createHash('sha256').update(token).digest('hex');
  }

  private parseTtlMs(ttl: string): number {
    const m = /^(\d+)([smhd])$/.exec(ttl);
    if (!m) return 7 * 86_400_000;
    const n = parseInt(m[1], 10);
    return m[2] === 's' ? n * 1000 : m[2] === 'm' ? n * 60_000 : m[2] === 'h' ? n * 3_600_000 : n * 86_400_000;
  }
}
```

### `auth.controller.ts`

```ts
import { Body, Controller, Get, Post, UseGuards } from '@nestjs/common';
import { Throttle } from '@nestjs/throttler';
import { AuthService } from './auth.service';
import { CurrentUser } from './decorators/current-user.decorator';
import { LoginDto } from './dto/login.dto';
import { RefreshDto } from './dto/refresh.dto';
import { JwtAuthGuard } from './guards/jwt-auth.guard';

@Controller('auth')
export class AuthController {
  constructor(private readonly auth: AuthService) {}

  @Post('login')
  @Throttle({ default: { ttl: 60_000, limit: 5 } })
  login(@Body() dto: LoginDto) { return this.auth.login(dto.email, dto.password); }

  @Post('refresh')
  @Throttle({ default: { ttl: 60_000, limit: 30 } })
  refresh(@Body() dto: RefreshDto) { return this.auth.refresh(dto.refreshToken); }

  @Post('logout')
  logout(@Body() dto: RefreshDto) { return this.auth.logout(dto.refreshToken); }

  @Get('me')
  @UseGuards(JwtAuthGuard)
  me(@CurrentUser() user: { sub: string; email: string; role: string }) { return { user }; }
}
```

Pair the rate-limit decorators with the `nestjs-throttle` skill — the auth endpoints are the prime brute-force target.

### `auth.module.ts`

```ts
import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { JwtModule } from '@nestjs/jwt';
import { MongooseModule } from '@nestjs/mongoose';
import { PassportModule } from '@nestjs/passport';
import { AuthController } from './auth.controller';
import { AuthService } from './auth.service';
import { JwtStrategy } from './jwt.strategy';
import { RefreshToken, RefreshTokenSchema } from './schemas/refresh-token.schema';
import { User, UserSchema } from './schemas/user.schema';

@Module({
  imports: [
    PassportModule,
    JwtModule.registerAsync({
      imports: [ConfigModule],
      inject: [ConfigService],
      useFactory: (config: ConfigService) => ({
        secret: config.getOrThrow<string>('JWT_ACCESS_SECRET'),
      }),
    }),
    MongooseModule.forFeature([
      { name: User.name, schema: UserSchema },
      { name: RefreshToken.name, schema: RefreshTokenSchema },
    ]),
  ],
  controllers: [AuthController],
  providers: [AuthService, JwtStrategy],
  exports: [AuthService, JwtStrategy, MongooseModule],
})
export class AuthModule {}
```

### `scripts/seed-admin.ts`

```ts
import 'dotenv/config';
import * as bcrypt from 'bcrypt';
import mongoose from 'mongoose';
import { UserSchema } from '../src/auth/schemas/user.schema';

async function main() {
  const uri = process.env.MONGO_URI;
  const email = (process.env.ADMIN_EMAIL || 'admin@local').toLowerCase().trim();
  const password = process.env.ADMIN_PASSWORD;
  if (!uri) { console.error('MONGO_URI required'); process.exit(1); }
  if (!password || password.length < 8) { console.error('ADMIN_PASSWORD must be set (min 8)'); process.exit(1); }

  await mongoose.connect(uri);
  const UserModel = mongoose.model('User', UserSchema);

  const existing = await UserModel.findOne({ email });
  if (existing) {
    existing.passwordHash = await bcrypt.hash(password, 12);
    existing.role = 'admin';
    existing.emailVerified = true;
    existing.active = true;
    await existing.save();
    console.log(`Updated admin: ${email}`);
  } else {
    await UserModel.create({
      email,
      passwordHash: await bcrypt.hash(password, 12),
      role: 'admin', emailVerified: true, active: true,
      displayName: 'Administrator',
    });
    console.log(`Created admin: ${email}`);
  }
  await mongoose.disconnect();
}

main().catch(err => { console.error('Seed failed:', err); process.exit(1); });
```

Add to `backend/package.json`:
```json
{ "scripts": { "seed:admin": "ts-node scripts/seed-admin.ts" } }
```

---

## Frontend

### `services/api/base.ts` — axios with refresh interceptor

```ts
import axios, { AxiosError, AxiosRequestConfig } from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
});

let accessToken: string | null = localStorage.getItem('mc.access');
let refreshToken: string | null = localStorage.getItem('mc.refresh');
let refreshing: Promise<string | null> | null = null;

export function setTokens(access: string | null, refresh: string | null) {
  accessToken = access; refreshToken = refresh;
  if (access) localStorage.setItem('mc.access', access); else localStorage.removeItem('mc.access');
  if (refresh) localStorage.setItem('mc.refresh', refresh); else localStorage.removeItem('mc.refresh');
}
export function getAccessToken() { return accessToken; }

api.interceptors.request.use(config => {
  if (accessToken) {
    config.headers = config.headers ?? {};
    (config.headers as Record<string, string>).Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

async function refreshAccess(): Promise<string | null> {
  if (!refreshToken) return null;
  try {
    const { data } = await axios.post('/api/auth/refresh', { refreshToken });
    setTokens(data.accessToken, data.refreshToken);
    return data.accessToken;
  } catch {
    setTokens(null, null);
    return null;
  }
}

api.interceptors.response.use(
  res => res,
  async (err: AxiosError) => {
    const original = err.config as AxiosRequestConfig & { _retry?: boolean };
    const status = err.response?.status;
    const url = original?.url || '';
    if (status === 401 && !original._retry && !url.endsWith('/auth/login') && !url.endsWith('/auth/refresh')) {
      original._retry = true;
      refreshing = refreshing ?? refreshAccess();
      const newToken = await refreshing;
      refreshing = null;
      if (newToken) {
        original.headers = original.headers ?? {};
        (original.headers as Record<string, string>).Authorization = `Bearer ${newToken}`;
        return api(original);
      }
    }
    return Promise.reject(err);
  },
);

export default api;
```

**The `refreshing` lock** is the bug-prevention bit. If 5 concurrent requests all 401 simultaneously, they all try to refresh and you get a race that revokes valid tokens. The shared promise ensures only one refresh in flight; the others await its result.

### `services/auth/AuthContext.tsx`

```tsx
import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from 'react';
import api, { setTokens } from '../api/base';

export interface User { id: string; email: string; role: 'admin' | 'member'; displayName?: string; }

interface AuthCtx {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}
const AuthContext = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/api/auth/me')
      .then(r => setUser(r.data.user as User))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { data } = await api.post('/api/auth/login', { email, password });
    setTokens(data.accessToken, data.refreshToken);
    setUser(data.user as User);
  }, []);

  const logout = useCallback(async () => {
    const refreshToken = localStorage.getItem('mc.refresh');
    if (refreshToken) await api.post('/api/auth/logout', { refreshToken }).catch(() => {});
    setTokens(null, null);
    setUser(null);
  }, []);

  return <AuthContext.Provider value={{ user, loading, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
```

### `components/ProtectedRoute.tsx`

```tsx
import { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../services/auth/AuthContext';

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return null;     // splash optional
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />;
  return <>{children}</>;
}
```

### `pages/Login.tsx` — minimal Mantine form

(See your project's LoginPage; the only auth-specific bit is `await login(values.email, values.password)` and redirect to `location.state?.from?.pathname || '/'`.)

---

## Bootstrap order

1. Set env vars in `backend/.env` (use `openssl rand -hex 64` for both JWT secrets).
2. Run `npm run seed:admin` to create the first user.
3. `nest start` — log in via API: `curl -X POST http://localhost:3000/api/auth/login -d '{"email":"…","password":"…"}'`.
4. Hit `/login` in the frontend, log in, see `useAuth().user` populated.

---

## Verification Checklist

- [ ] `.env` gitignored — never committed.
- [ ] Both JWT secrets are 64+ random bytes (NOT the same string).
- [ ] `bcrypt.hash(password, 12)` — cost 12, not 10.
- [ ] Refresh token is hashed (sha256) before storing in Mongo.
- [ ] Logging in with a deactivated account returns 401, not a confused 500.
- [ ] Refresh rotates: after using a refresh token, calling refresh AGAIN with the same token fails.
- [ ] Logout marks the refresh token revoked (subsequent refresh fails).
- [ ] Five concurrent 401s only fire ONE `/auth/refresh` (test with browser DevTools Network tab).
- [ ] Routes wrapped in `<ProtectedRoute>` redirect to /login when no user.
- [ ] `@UseGuards(JwtAuthGuard, RolesGuard) @Roles('admin')` returns 403 for member calls.
- [ ] Restarting the backend doesn't log users out (refresh tokens persist in Mongo).

---

## Pairs Well With

- **`audit-log`** — audit `auth.login`, `auth.refresh`, `auth.logout` (redact tokens in payload).
- **`users-admin-page`** — CRUD on the User collection from the UI.
- **`nestjs-throttle`** — protect `/api/auth/login` and `/api/auth/signup` (if any).
- **`api-platform`** — if you need API-key auth alongside JWT, layer `api-platform` on top.

---

## Tradeoffs

- **No public signup.** Intentional — internal tools only. If you need self-signup, add a separate `signup.dto.ts` + `auth.signup()` method but think hard about email verification, anti-bot, and rate limits first.
- **localStorage tokens, not httpOnly cookies.** Tradeoff: simpler axios setup, but vulnerable to XSS exfiltration. Mitigations: aggressive CSP headers, no third-party scripts, token TTLs short. For higher-security regimes, switch to httpOnly cookies + CSRF token.
- **Single refresh-token rotation, not refresh-token reuse detection.** If a refresh token is stolen and used, the legitimate user gets logged out next time they try to refresh (two clients can't share). Add reuse detection (mark whole token family revoked on conflict) when stakes warrant it.
- **bcrypt cost 12.** ~250ms per login on commodity CPUs. Slow enough to deter brute force, fast enough not to bother users. Crank to 14 for high-stakes apps; drop to 10 only if your CPU is genuinely a bottleneck.
