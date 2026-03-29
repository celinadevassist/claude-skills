---
name: "Logging Setup"
description: "Set up production-grade structured logging for NestJS backend projects. JSON file-based logs with rotation, proper error serialization, and exception filters that capture full stack traces. Use when creating a new project, fixing empty error logs, or standardizing logging across projects."
---

# Logging Setup

## What This Skill Does

Configures structured, file-based logging for NestJS backends with:
1. **JSON log files** — `application.log`, `error.log`, `debug.log`
2. **Log rotation** — 10MB per file, keeps last 5 rotations
3. **Proper error serialization** — stack traces, error names, and nested causes
4. **Exception filter** — catches all errors and logs them properly (no more `{}`)
5. **Console + file output** — see logs in terminal AND persisted to disk

## When to Use

- Setting up a new NestJS project
- Fixing empty error logs (the `"trace":{}` problem)
- Adding file-based logging to a project that only has console output
- Standardizing logging across multiple projects

---

## Step 1: Logger Service

Create `backend/src/logger/logger.service.ts`:

```typescript
import { ConsoleLogger } from '@nestjs/common';
import * as fs from 'fs';
import * as path from 'path';

export class LoggerService extends ConsoleLogger {
  private logDir: string;
  private streams: Record<string, fs.WriteStream> = {};
  private maxFileSize = 10 * 1024 * 1024; // 10MB

  constructor(context?: string) {
    super(context || 'Application');
    this.logDir = path.resolve(process.cwd(), 'logs');
    this.ensureLogDir();
    this.initStreams();
  }

  private ensureLogDir() {
    if (!fs.existsSync(this.logDir)) {
      fs.mkdirSync(this.logDir, { recursive: true });
    }
  }

  private initStreams() {
    const files = ['application.log', 'error.log', 'debug.log'];
    for (const file of files) {
      const filePath = path.join(this.logDir, file);
      this.streams[file] = fs.createWriteStream(filePath, { flags: 'a' });
    }
  }

  private serializeError(err: unknown): { message: string; stack?: string; name?: string; details?: any } {
    if (err instanceof Error) {
      return {
        name: err.name,
        message: err.message,
        stack: err.stack,
        ...(err['details'] ? { details: err['details'] } : {}),
      };
    }
    if (typeof err === 'string') return { message: err };
    if (typeof err === 'object' && err !== null) {
      try {
        return { message: JSON.stringify(err) };
      } catch {
        return { message: String(err) };
      }
    }
    return { message: String(err) };
  }

  private formatJson(level: string, message: string, context?: string, trace?: any) {
    const entry: any = {
      timestamp: new Date().toISOString(),
      level,
      context: context || this.context || 'Application',
      message,
      pid: process.pid,
    };

    if (trace) {
      if (typeof trace === 'string') {
        entry.trace = trace;
      } else {
        entry.error = this.serializeError(trace);
      }
    }

    return JSON.stringify(entry) + '\n';
  }

  private writeToFile(filename: string, entry: string) {
    const stream = this.streams[filename];
    if (stream && !stream.destroyed) {
      stream.write(entry);
      this.rotateIfNeeded(filename);
    }
  }

  private rotateIfNeeded(filename: string) {
    const filePath = path.join(this.logDir, filename);
    try {
      const stats = fs.statSync(filePath);
      if (stats.size > this.maxFileSize) {
        const stream = this.streams[filename];
        if (stream) stream.end();
        const rotated = filePath + '.' + Date.now();
        fs.renameSync(filePath, rotated);
        this.streams[filename] = fs.createWriteStream(filePath, { flags: 'a' });
        this.cleanOldRotations(filename);
      }
    } catch {
      // File may not exist yet
    }
  }

  private cleanOldRotations(filename: string) {
    try {
      const files = fs.readdirSync(this.logDir)
        .filter(f => f.startsWith(filename + '.'))
        .sort()
        .reverse();
      for (const f of files.slice(5)) {
        fs.unlinkSync(path.join(this.logDir, f));
      }
    } catch {
      // Ignore cleanup errors
    }
  }

  log(message: string, context?: string) {
    super.log(message, context);
    this.writeToFile('application.log', this.formatJson('info', message, context));
  }

  error(message: string, trace?: any, context?: string) {
    super.error(message, trace, context);
    const entry = this.formatJson('error', message, context, trace);
    this.writeToFile('error.log', entry);
    this.writeToFile('application.log', entry);
  }

  warn(message: string, context?: string) {
    super.warn(message, context);
    this.writeToFile('application.log', this.formatJson('warning', message, context));
  }

  debug(message: string, context?: string) {
    super.debug(message, context);
    this.writeToFile('debug.log', this.formatJson('debug', message, context));
  }

  verbose(message: string, context?: string) {
    super.verbose(message, context);
    this.writeToFile('debug.log', this.formatJson('debug', message, context));
  }

  onApplicationShutdown() {
    for (const stream of Object.values(this.streams)) {
      if (stream && !stream.destroyed) stream.end();
    }
  }
}
```

**Key difference from broken implementations**: The `serializeError()` method handles all error types — `Error` objects get their `name`, `message`, and `stack` extracted properly. Plain objects get JSON-stringified. This fixes the `"trace":{}` problem.

## Step 2: Logger Module

Create `backend/src/logger/logger.module.ts`:

```typescript
import { Module, Global } from '@nestjs/common';
import { LoggerService } from './logger.service';

@Global()
@Module({
  providers: [LoggerService],
  exports: [LoggerService],
})
export class LoggerModule {}
```

## Step 3: Exception Filters

### AllExceptionsFilter

The catch-all filter must serialize errors properly. Create `backend/src/filters/http-exception.filter.ts`:

```typescript
import {
  ExceptionFilter,
  Catch,
  ArgumentsHost,
  HttpException,
  HttpStatus,
  Logger,
} from '@nestjs/common';

@Catch()
export class AllExceptionsFilter implements ExceptionFilter {
  private readonly logger = new Logger('ExceptionFilter');

  catch(exception: unknown, host: ArgumentsHost) {
    const ctx = host.switchToHttp();
    const response = ctx.getResponse();
    const request = ctx.getRequest();

    let status = HttpStatus.INTERNAL_SERVER_ERROR;
    let message = 'Internal server error';

    if (exception instanceof HttpException) {
      status = exception.getStatus();
      const res = exception.getResponse();
      message = typeof res === 'string' ? res : (res as any).message || exception.message;
    }

    // Log the FULL error with stack trace
    if (exception instanceof Error) {
      this.logger.error(
        `${request.method} ${request.url} -> ${status}: ${exception.message}`,
        exception.stack,
      );
    } else {
      this.logger.error(
        `${request.method} ${request.url} -> ${status}: ${String(exception)}`,
      );
    }

    response.status(status).json({
      statusCode: status,
      message,
      timestamp: new Date().toISOString(),
      path: request.url,
    });
  }
}
```

### BusinessErrorFilter (if using business exceptions)

```typescript
import {
  ExceptionFilter,
  Catch,
  ArgumentsHost,
  HttpException,
  HttpStatus,
  Logger,
} from '@nestjs/common';
import { BusinessException } from './business.exception';

@Catch()
export class BusinessErrorFilter implements ExceptionFilter {
  private readonly logger = new Logger(BusinessErrorFilter.name);

  catch(exception: unknown, host: ArgumentsHost) {
    const ctx = host.switchToHttp();
    const response = ctx.getResponse();
    const request = ctx.getRequest();

    let status = HttpStatus.INTERNAL_SERVER_ERROR;
    let errorResponse: any;

    if (exception instanceof BusinessException) {
      status = exception.getStatus();
      const res = exception.getResponse() as any;
      errorResponse = {
        statusCode: status,
        errorCode: res.errorCode,
        message: res.message,
        details: res.details,
        timestamp: new Date().toISOString(),
        path: request.url,
      };
    } else if (exception instanceof HttpException) {
      status = exception.getStatus();
      const res = exception.getResponse();
      errorResponse = {
        statusCode: status,
        message: typeof res === 'string' ? res : (res as any).message || exception.message,
        timestamp: new Date().toISOString(),
        path: request.url,
      };
    } else {
      // CRITICAL: Properly serialize the error — don't pass raw object
      const errMsg = exception instanceof Error
        ? exception.message
        : String(exception);
      const errStack = exception instanceof Error
        ? exception.stack
        : undefined;

      this.logger.error(
        `Unhandled: ${request.method} ${request.url} -> ${errMsg}`,
        errStack,
      );

      errorResponse = {
        statusCode: status,
        message: 'Internal server error',
        timestamp: new Date().toISOString(),
        path: request.url,
      };
    }

    response.status(status).json(errorResponse);
  }
}
```

**The fix**: Instead of `this.logger.error('Unhandled exception:', exception)` (which serializes the Error object as `{}`), we extract `exception.message` and pass `exception.stack` as the trace parameter.

## Step 4: Register in main.ts

```typescript
import { LoggerService } from './logger/logger.service';

async function bootstrap() {
  const logger = new LoggerService('Bootstrap');

  const app = await NestFactory.create(AppModule, {
    bodyParser: false,
    logger,  // Use our logger for all NestJS internal logs
  });

  // ... middleware setup ...

  app.useGlobalFilters(new AllExceptionsFilter(), new BusinessErrorFilter());
  app.useLogger(logger);

  const port = process.env.PORT || 3041;
  await app.listen(port);
  logger.log(`Application running on port ${port}`);
}
```

## Step 5: Docker & .gitignore

Ensure the logs directory is handled:

**Dockerfile** — create writable logs dir:
```dockerfile
RUN mkdir -p /app/logs && chown -R nodejs:nodejs /app/logs
```

**docker-compose.yml** — persist logs:
```yaml
volumes:
  - 'app_logs:/app/logs'
```

**.gitignore** — don't commit logs:
```
logs/
```

---

## Log File Structure

| File | Contents | Level |
|------|----------|-------|
| `logs/application.log` | All info, warning, and error logs | info + warn + error |
| `logs/error.log` | Errors only with stack traces | error |
| `logs/debug.log` | Debug and verbose output | debug + verbose |

Each line is a JSON object:
```json
{"timestamp":"2026-03-29T12:00:00.000Z","level":"error","context":"ExceptionFilter","message":"POST /api/en/auth/signin -> 500: Not allowed by CORS","error":{"name":"Error","message":"Not allowed by CORS","stack":"Error: Not allowed by CORS\n    at origin (/app/src/config.manager.ts:62:16)\n    ..."},"pid":368826}
```

---

## Common Problems This Fixes

| Problem | Cause | Fix |
|---------|-------|-----|
| Error log shows `"trace":{}` | Passing Error object to `logger.error()` as second arg — gets serialized as empty object | `serializeError()` extracts `name`, `message`, `stack` from Error objects |
| No file logs in EMS | LoggerService only wraps ConsoleLogger without file output | Replace with the full file-based logger |
| CORS errors show as 500 with no detail | Exception filter logs `exception` object directly | Extract `exception.message` and `exception.stack` separately |
| Logs lost on container restart | No volume mount for `/app/logs` | Add `app_logs:/app/logs` volume in docker-compose |
| Log files grow forever | No rotation configured | 10MB max per file, keeps last 5 rotations |

---

## Checklist

- [ ] `LoggerService` in `backend/src/logger/logger.service.ts` with `serializeError()`
- [ ] `LoggerModule` in `backend/src/logger/logger.module.ts` (Global)
- [ ] `AllExceptionsFilter` uses `exception.message` + `exception.stack` (not raw object)
- [ ] `BusinessErrorFilter` same pattern for unhandled exceptions
- [ ] `main.ts` creates `LoggerService` and passes to `NestFactory.create({ logger })`
- [ ] `main.ts` registers both exception filters via `app.useGlobalFilters()`
- [ ] `/logs` directory in `.gitignore`
- [ ] Docker creates `/app/logs` dir with correct ownership
- [ ] docker-compose mounts `app_logs:/app/logs` volume
- [ ] Verify: trigger an error and check `logs/error.log` has full stack trace
