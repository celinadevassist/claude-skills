import { ExecutionContext, Injectable, UnauthorizedException } from '@nestjs/common';
import { AuthGuard } from '@nestjs/passport';

/**
 * Accepts EITHER a valid JWT Bearer token OR a valid API key.
 * The ApiKeyMiddleware must run before this guard to populate req.user.
 */
@Injectable()
export class JwtOrApiKeyGuard extends AuthGuard('jwt') {
  canActivate(context: ExecutionContext) {
    const request = context.switchToHttp().getRequest();
    if (request.user && request.isApiKey) return true;
    return super.canActivate(context);
  }

  handleRequest(err: any, user: any, info: any, context: ExecutionContext) {
    const request = context.switchToHttp().getRequest();
    if (request.user && request.isApiKey) return request.user;
    if (err || !user) {
      throw err || new UnauthorizedException(
        'Authentication required. Provide a Bearer token or X-API-Key header.'
      );
    }
    return user;
  }
}
