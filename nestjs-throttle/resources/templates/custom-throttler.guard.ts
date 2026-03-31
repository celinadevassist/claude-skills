import { Injectable, ExecutionContext } from '@nestjs/common';
import { ThrottlerGuard } from '@nestjs/throttler';

/**
 * Custom throttler guard for NestJS monolith apps that serve both static assets and API routes.
 *
 * IMPORTANT design decisions:
 * 1. Skip static assets: ServeStaticModule requests don't need rate limiting.
 *    Without this, a page refresh loads 20+ JS/CSS/image files simultaneously,
 *    easily exceeding the short-window throttle limit and causing 429 errors.
 *
 * 2. Check Authorization header, NOT req.user: This guard runs as APP_GUARD (global),
 *    which executes BEFORE controller-level auth guards (JwtOrApiKeyGuard, AuthGuard).
 *    At this point req.user is always undefined — checking it would throttle ALL requests.
 *    The Bearer header is available immediately from the raw request.
 *
 * 3. Still throttle: unauthenticated requests and API key requests (brute-force protection).
 */
@Injectable()
export class CustomThrottlerGuard extends ThrottlerGuard {
  protected async shouldSkip(context: ExecutionContext): Promise<boolean> {
    const req = context.switchToHttp().getRequest();

    // Skip throttling for non-API requests (static assets served by ServeStaticModule)
    const url = req.url || req.originalUrl || '';
    if (!url.startsWith('/api')) {
      return true;
    }

    // Skip throttling for JWT-authenticated frontend users
    // Check the Authorization header directly since this guard runs before auth guards populate req.user
    const authHeader = req.headers?.authorization;
    if (authHeader && authHeader.startsWith('Bearer ')) {
      return true;
    }

    return false;
  }

  protected async getTracker(req: Record<string, any>): Promise<string> {
    // Extract real client IP, handling reverse proxy (Caddy/nginx) scenarios
    const forwarded = req.headers['x-forwarded-for'];
    const realIp = req.headers['x-real-ip'];
    const ip = req.ip;

    // Priority: x-forwarded-for > x-real-ip > req.ip
    if (forwarded) {
      return typeof forwarded === 'string'
        ? forwarded.split(',')[0].trim()
        : forwarded[0];
    }

    if (realIp) {
      return typeof realIp === 'string' ? realIp : realIp[0];
    }

    return ip || 'unknown';
  }
}
