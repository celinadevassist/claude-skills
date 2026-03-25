# API Platform Troubleshooting

## API Key Auth Returns 401

**Symptom:** `{ "statusCode": 401, "message": "Unauthorized" }` when using X-API-Key header

**Causes & Fixes:**

1. **Using `AuthGuard()` instead of `JwtOrApiKeyGuard`**
   - Passport's `AuthGuard('jwt')` only validates JWT tokens
   - Replace all `AuthGuard()` with `JwtOrApiKeyGuard` in controllers

2. **CORS blocking X-API-Key header**
   - Add `X-API-Key` to `allowedHeaders` in CORS config
   - Check browser console for CORS preflight errors

3. **Middleware not registered**
   - `ApiKeyMiddleware` must be in `AuthModule.configure()` with `.forRoutes('*')`

4. **Key prefix mismatch**
   - Middleware checks `apiKey.startsWith('ems_')` — ensure your prefix matches
   - Prefix stored in DB must be first 12 chars of the full key

## Try It Panel Shows Wrong URL

**Symptom:** URL contains `{lang}` literally: `/api/%7Blang%7D/...`

**Cause:** Many NestJS endpoints have `{lang}` in path but don't declare it as a Swagger parameter.

**Fix:** Always replace `{lang}` before iterating over declared params:
```javascript
url = url.replace('{lang}', pathValues.lang || 'en');
```

## /swagger-json Returns HTML

**Symptom:** API docs page shows "Failed to load" or gets HTML instead of JSON

**Fixes:**
1. Add `/swagger-json` to Vite proxy config
2. Ensure swagger-json endpoint is served before the dev-only check in config.manager.ts
3. Set `Accept: application/json` header (ServeStaticModule may intercept otherwise)

## Infinite Re-renders on API Keys Page

**Cause:** Mantine 8 + React 19 Drawer/Modal rendered while `opened={false}`

**Fix:** Conditionally mount: `{isOpen && <Modal opened ... />}`

## API Key Not Matching

**Symptom:** Valid key returns 401, middleware doesn't find match

**Debug:**
1. Check `prefix` in DB matches first 12 chars of key
2. Check `isActive: true` in DB
3. Test bcrypt compare manually
4. Check middleware logs: `ApiKeyMiddleware.debug`
