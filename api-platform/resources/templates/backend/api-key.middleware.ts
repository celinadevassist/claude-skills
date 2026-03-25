import { Injectable, NestMiddleware, Logger } from '@nestjs/common';
import { InjectModel } from '@nestjs/mongoose';
import { Model } from 'mongoose';
import * as bcrypt from 'bcryptjs';
import { ApiKey, ApiKeyDocument } from './api-key.schema';

@Injectable()
export class ApiKeyMiddleware implements NestMiddleware {
  private readonly logger = new Logger(ApiKeyMiddleware.name);

  constructor(
    @InjectModel(ApiKey.name) private apiKeyModel: Model<ApiKeyDocument>,
    @InjectModel('User') private userModel: Model<any>,
  ) {}

  async use(req: any, res: any, next: () => void) {
    const apiKey = req.headers['x-api-key'];

    // Skip if no API key, already authenticated, or wrong prefix
    if (!apiKey || req.user || !apiKey.startsWith('ems_')) {
      return next();
    }

    try {
      const prefix = apiKey.substring(0, 12);
      const candidates = await this.apiKeyModel.find({ prefix, isActive: true }).lean();

      for (const candidate of candidates) {
        const match = await bcrypt.compare(apiKey, candidate.keyHash);
        if (match) {
          await this.apiKeyModel.updateOne(
            { _id: candidate._id },
            { $set: { lastUsedAt: new Date() } },
          );
          const user = await this.userModel.findById(candidate.creator).lean();
          if (user) {
            req.user = user;
            req.isApiKey = true;
            this.logger.debug(`API key authenticated for user ${user._id}`);
          }
          break;
        }
      }
    } catch (error) {
      this.logger.error('API key middleware error:', error);
    }

    next();
  }
}
