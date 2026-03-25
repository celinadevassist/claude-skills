---
name: "API Platform Builder"
description: "Build production-ready API key management, auto-generated API documentation with interactive Try It panels, and dual auth (JWT + API key) for NestJS + React projects. Use when adding API key authentication, building API docs pages, adding Swagger decorators, or setting up dual auth guards."
---

# API Platform Builder

## What This Skill Does

Builds three integrated features for any NestJS + React project:

1. **API Key Management** — Generate, list, revoke API keys with bcrypt hashing
2. **Interactive API Documentation** — Stripe-level docs auto-generated from Swagger/OpenAPI with "Try It" panels
3. **Dual Authentication** — JwtOrApiKeyGuard pattern accepting both Bearer tokens and X-API-Key headers

## Prerequisites

- NestJS backend with `@nestjs/swagger`, `@nestjs/passport`, `bcryptjs`, `mongoose`
- React frontend (Mantine optional — the API docs use raw HTML/CSS for full control)
- MongoDB for API key storage

---

## Quick Start

### 1. Backend: API Key System
```bash
# Files to create:
# src/auth/api-key.schema.ts      — Mongoose schema
# src/auth/api-key.middleware.ts   — X-API-Key header middleware
# src/guards/jwt-or-apikey.guard.ts — Dual auth guard
# Add endpoints to auth controller: generate, list, revoke
```

### 2. Backend: Swagger Decorators
```bash
# Add to EVERY controller endpoint:
# @ApiOperation({ summary: '...' })
# @ApiResponse({ status: 200/201, description: '...' })
# @ApiBody({ type: DtoClass }) for POST/PATCH
# @ApiParam({ name: '...', description: '...' }) for path params
```

### 3. Frontend: API Docs Page
```bash
# Create: src/pages/Settings/ApiDocs/index.jsx
# Auto-generates from /swagger-json endpoint
# Two-column layout: info left, curl examples right
# Interactive Try It panels per endpoint
```

---

## Architecture Decisions & Patterns

### Pattern 1: API Key Schema (MongoDB)

```typescript
// api-key.schema.ts
@Schema({ timestamps: true })
export class ApiKey {
  @Prop({ required: true })
  name: string;                    // Human label: "CI/CD Bot"

  @Prop({ required: true })
  keyHash: string;                 // bcrypt hash of full key

  @Prop({ required: true, index: true })
  prefix: string;                  // First 12 chars for lookup: "ems_abc12345"

  @Prop({ type: Types.ObjectId, ref: 'User', required: true })
  creator: Types.ObjectId;

  @Prop({ default: true })
  isActive: boolean;

  @Prop()
  lastUsedAt: Date;
}
```

**Key decisions:**
- Store bcrypt hash, NEVER the raw key
- Store prefix (first 12 chars) for efficient DB lookup without scanning all keys
- Key format: `{prefix}_{random}` (e.g., `ems_abc123def456...`)
- Show full key ONCE at creation, never again

### Pattern 2: API Key Middleware

```typescript
// api-key.middleware.ts — runs BEFORE guards
async use(req, res, next) {
  const apiKey = req.headers['x-api-key'];
  if (!apiKey || req.user || !apiKey.startsWith('ems_')) return next();

  const prefix = apiKey.substring(0, 12);
  const candidates = await this.apiKeyModel.find({ prefix, isActive: true }).lean();

  for (const candidate of candidates) {
    if (await bcrypt.compare(apiKey, candidate.keyHash)) {
      req.user = await this.userModel.findById(candidate.creator).lean();
      req.isApiKey = true;                    // Flag for guard
      await this.apiKeyModel.updateOne(
        { _id: candidate._id },
        { $set: { lastUsedAt: new Date() } }
      );
      break;
    }
  }
  next();
}
```

**Critical:** Register as middleware in module, NOT as guard:
```typescript
export class AuthModule implements NestModule {
  configure(consumer: MiddlewareConsumer) {
    consumer.apply(ApiKeyMiddleware).forRoutes('*');
  }
}
```

### Pattern 3: JwtOrApiKeyGuard (Dual Auth)

```typescript
// jwt-or-apikey.guard.ts
@Injectable()
export class JwtOrApiKeyGuard extends AuthGuard('jwt') {
  canActivate(context: ExecutionContext) {
    const request = context.switchToHttp().getRequest();
    // API key middleware already authenticated? Allow through.
    if (request.user && request.isApiKey) return true;
    // Otherwise, try JWT
    return super.canActivate(context);
  }

  handleRequest(err, user, info, context) {
    const request = context.switchToHttp().getRequest();
    if (request.user && request.isApiKey) return request.user;
    if (err || !user) throw err || new UnauthorizedException(
      'Provide a Bearer token or X-API-Key header.'
    );
    return user;
  }
}
```

**Why not just `AuthGuard('jwt')`?**
Passport's JWT guard extracts and validates a JWT token. If there's no Bearer header, it rejects — even if the middleware already set `req.user` via API key. The custom guard checks for API key auth first, only falling back to JWT if needed.

**Migration:** Replace `AuthGuard()` with `JwtOrApiKeyGuard` in all controllers:
```typescript
// BEFORE
@UseGuards(AuthGuard())
// AFTER
@UseGuards(JwtOrApiKeyGuard)

// With RolesGuard:
@UseGuards(JwtOrApiKeyGuard, RolesGuard)
```

---

## Critical Fixes & Gotchas

### Fix 1: CORS Must Allow X-API-Key Header

```typescript
// config.manager.ts or main.ts
app.enableCors({
  allowedHeaders: 'Content-Type, Authorization, X-API-Key',  // <-- MUST include
  // ...
});
```

**Why:** Without this, browser preflight (OPTIONS) requests reject the X-API-Key header, causing API key auth to silently fail from frontend clients.

### Fix 2: Swagger JSON Must Be Available in All Environments

```typescript
// Serve swagger-json BEFORE the dev-only check
const document = SwaggerModule.createDocument(app, config);
app.use('/swagger-json', (req, res) => res.json(document));

// Only serve Swagger UI in development
if (process.env.NODE_ENV === 'production') return;
setUpSwagger(app);
```

**Why:** The API docs page fetches `/swagger-json`. If it's behind a dev-only check, production users can't see docs.

### Fix 3: Vite Proxy for /swagger-json

```javascript
// vite.config.js
proxy: {
  '/api': { target: 'http://localhost:3041', changeOrigin: true },
  '/swagger-json': { target: 'http://localhost:3041', changeOrigin: true },  // <-- Add this
}
```

**Why:** Without this, the dev server returns the SPA HTML for `/swagger-json` instead of proxying to the backend.

### Fix 4: Guard Debug Endpoints in Production

```typescript
@Get('debug/check-data')
async debugCheck(@User() user) {
  if (process.env.NODE_ENV === 'production') {
    return { success: false, message: 'Not available in production' };
  }
  return this.service.debugData(user);
}
```

**Why:** Debug/cleanup endpoints expose internal data. Mark them with `Debug:` prefix in Swagger summary for visibility.

### Fix 5: Path Params Not Always Listed in Swagger

NestJS controllers with `:lang` in the path don't always emit `lang` as a Swagger parameter. The "Try It" panel must handle this:

```javascript
// Always substitute {lang} even if not in parameters list
let url = path;
url = url.replace('{lang}', pathValues.lang || 'en');
Object.entries(pathValues).forEach(([key, val]) => {
  url = url.replaceAll(`{${key}}`, encodeURIComponent(val || key));
});
```

### Fix 6: Mantine 8 + React 19 Modal/Drawer Pattern

```jsx
// WRONG — causes infinite render loops
<Modal opened={isOpen} onClose={() => setIsOpen(false)}>

// CORRECT — conditionally mount
{isOpen && <Modal opened onClose={() => setIsOpen(false)}>}
```

### Fix 7: Redux Selector Stable References

```javascript
// WRONG — creates new [] reference every render
const items = useSelector(state => state.data.items || []);

// CORRECT — module-level constant
const EMPTY_ARRAY = [];
const items = useSelector(state => state.data.items || EMPTY_ARRAY);
```

### Fix 8: Persist API Key in localStorage for Try It Panel

```javascript
// Save auth when changed
useEffect(() => {
  if (globalAuthValue) {
    localStorage.setItem('apidoc_auth', JSON.stringify({
      type: globalAuthType, value: globalAuthValue
    }));
  }
}, [globalAuthType, globalAuthValue]);

// Restore on mount (before falling back to session token)
const savedAuth = localStorage.getItem('apidoc_auth');
if (savedAuth) {
  const { type, value } = JSON.parse(savedAuth);
  setGlobalAuthType(type);
  setGlobalAuthValue(value);
}
```

**Why:** API keys entered in the Try It panel are lost on page refresh without this. Store under a dedicated key (`apidoc_auth`), separate from session auth.

### Fix 9: Copy Button on Response Panel

Always include a copy button on the Try It response so users can easily extract response data. Use a `responseCopied` state with a 1.5s timeout for visual feedback.

---

## Swagger Decorator Patterns

### Standard CRUD Controller

```typescript
import { ApiTags, ApiOperation, ApiResponse, ApiParam, ApiBody, ApiBearerAuth } from '@nestjs/swagger';

@ApiTags('EMS - Campaigns')
@ApiBearerAuth()
@Controller(':lang/email-marketing/campaign')
@UseGuards(JwtOrApiKeyGuard)
export class CampaignController {

  @Post()
  @ApiOperation({ summary: 'Create a new campaign' })
  @ApiParam({ name: 'lang', description: 'Language code', example: 'en' })
  @ApiBody({ type: CreateCampaignDto })
  @ApiResponse({ status: 201, description: 'Campaign created successfully' })
  @ApiResponse({ status: 400, description: 'Invalid request body' })
  @ApiResponse({ status: 401, description: 'Unauthorized' })
  async create(@Body() dto: CreateCampaignDto, @User() user) { ... }

  @Get()
  @ApiOperation({ summary: 'List all campaigns with filters' })
  @ApiResponse({ status: 200, description: 'Paginated campaign list' })
  @ApiResponse({ status: 401, description: 'Unauthorized' })
  async findAll(@Query() query, @User() user) { ... }

  @Get(':id')
  @ApiOperation({ summary: 'Get a campaign by ID' })
  @ApiParam({ name: 'id', description: 'Campaign ID' })
  @ApiResponse({ status: 200, description: 'Campaign details' })
  @ApiResponse({ status: 401, description: 'Unauthorized' })
  @ApiResponse({ status: 404, description: 'Campaign not found' })
  async findById(@Param('id') id: string, @User() user) { ... }
}
```

### Checklist for Every Endpoint
- [ ] `@ApiOperation({ summary: '...' })` — concise, professional
- [ ] `@ApiParam()` for each path parameter
- [ ] `@ApiBody({ type: DtoClass })` for POST/PATCH/PUT
- [ ] `@ApiResponse()` for success (200/201) and errors (400/401/404)
- [ ] `@ApiBearerAuth()` on class or protected methods
- [ ] Debug endpoints marked with `Debug:` prefix in summary

---

## Frontend: API Documentation Page

### Design Principles

- **Two-column layout**: Left = endpoint info + params, Right = dark code panel with curl + response
- **Raw HTML/CSS with prefixed classes** (`apidoc-*`) — NOT Mantine components (avoids spacing/theming conflicts)
- **Sidebar navigation** with IntersectionObserver for active section tracking
- **Syntax highlighting** for curl commands and JSON responses
- **"Try It" panel** expands below each endpoint with form fields + live response
- **Auto-fills auth** from Redux persist localStorage (`persist:root` → `auth.token`)
- **Resource-specific response examples** — campaigns show title/status/stats, emails show email/source, etc.

### Key Frontend Architecture

```
ApiDocs/index.jsx
├── Constants: METHOD_COLORS, METHOD_LABELS, RESOURCE_EXAMPLES, SPECIAL_RESPONSES
├── Helpers: escapeHtml, highlightCurl, highlightJson, buildResponseExample, buildPayload
├── Global auth bar (set once, shared by all Try It panels, persisted in localStorage)
├── TryItPanel component (receives global auth as props)
│   ├── Path param inputs (pre-filled, lang='en')
│   ├── Query param inputs
│   ├── Request body textarea (pre-filled from Swagger schema)
│   ├── Send button (method-colored, with spinner)
│   └── Response display (status badge + time + JSON + copy button)
└── ApiDocs main component
    ├── Fetch /swagger-json on mount
    ├── Group endpoints by @ApiTags
    ├── Search filter
    ├── Sidebar with scrollToSection
    └── Endpoint cards (info left + code right + expandable TryIt)
```

### CSS Class Naming Convention

All classes prefixed with `apidoc-` (docs) or `tryit-` (interactive panel) to avoid conflicts:
```css
.apidoc-root, .apidoc-sidebar, .apidoc-main
.apidoc-endpoint, .apidoc-info, .apidoc-code-panel
.apidoc-method-badge, .apidoc-path, .apidoc-summary
.apidoc-params-table, .apidoc-param-name
.tryit-panel, .tryit-input, .tryit-textarea
.tryit-send-btn, .tryit-response, .tryit-status-badge
```

### Response Example Strategy

Don't use generic `{ _id: '...', createdAt: '...' }` for all endpoints. Map each resource to realistic examples:

```javascript
const RESOURCE_EXAMPLES = {
  'email-marketing/campaign': {
    single: { _id: '69c1b2...', title: 'My Campaign', status: 'READY', stats: {...} },
    listItem: { _id: '69c1b2...', title: 'My Campaign', status: 'READY' },
  },
  // ... per resource
};

const SPECIAL_RESPONSES = {
  '/stats': { totalRecipients: 150, sent: 120, openRate: '37.5%' },
  '/signin': { token: 'eyJ...', user: { _id: '...', name: '...' } },
  '/send-batch': { success: true, sent: 10, failed: 0, remaining: 140 },
  // ... per special endpoint
};
```

---

## Step-by-Step Implementation Order

### Phase 1: Backend API Key System
1. Create `api-key.schema.ts` with Mongoose schema
2. Add generate/list/revoke methods to auth service
3. Add endpoints to auth controller with Swagger decorators
4. Create `api-key.middleware.ts` and register in AuthModule
5. Create `jwt-or-apikey.guard.ts`
6. Replace all `AuthGuard()` with `JwtOrApiKeyGuard`
7. Add `X-API-Key` to CORS `allowedHeaders`

### Phase 2: Swagger Documentation
1. Add `@ApiOperation`, `@ApiResponse`, `@ApiBody`, `@ApiParam` to ALL controller endpoints
2. Ensure `/swagger-json` is served in ALL environments
3. Add `/swagger-json` to Vite proxy config
4. Guard debug endpoints with production check
5. Build backend and verify zero missing summaries

### Phase 3: Frontend API Keys Page
1. Create API Keys page with Mantine components
2. Generate key → show once with copy button
3. List keys showing prefix, status, lastUsed, created
4. Revoke with confirmation dialog
5. Link to API Docs page

### Phase 4: Frontend API Docs Page
1. Fetch `/swagger-json` on mount
2. Build sidebar navigation with search
3. Build two-column endpoint cards
4. Add syntax-highlighted curl examples with copy
5. Build resource-specific response examples
6. Add "Try It" panel with auth auto-fill
7. Add response display with copy button
8. Test with real API key authentication

---

## Verification Checklist

### Backend
- [ ] API key generates with `ems_` prefix
- [ ] Key shown only once at creation
- [ ] `X-API-Key` header authenticates successfully
- [ ] Bearer token still works (no regression)
- [ ] All 100% of endpoints have Swagger summaries
- [ ] `/swagger-json` accessible in production
- [ ] Debug endpoints blocked in production
- [ ] CORS allows `X-API-Key` header

### Frontend
- [ ] API Keys page: generate, list, revoke all work
- [ ] API Docs page loads from `/swagger-json`
- [ ] Search filters endpoints by path, summary, and tag
- [ ] Sidebar highlights active section on scroll
- [ ] Curl examples have correct syntax highlighting
- [ ] Response examples are resource-specific (not generic)
- [ ] "Try It" panel: auth auto-fills from session
- [ ] "Try It" panel: path params substitute correctly (especially `{lang}`)
- [ ] "Try It" panel: API key auth works
- [ ] "Try It" panel: response shows status, time, and formatted JSON
- [ ] "Try It" panel: copy response button works
- [ ] Mobile responsive layout

---

## Template Files

For complete implementation templates, see:
- `resources/templates/backend/` — NestJS files (schema, middleware, guard, controller patterns)
- `resources/templates/frontend/` — React component (full API docs page)
- `docs/TROUBLESHOOTING.md` — Extended troubleshooting guide
