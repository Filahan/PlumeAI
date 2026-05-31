/** Public façade for the FastAPI client layer.
 *
 *      import { settings, conversations, chat, parseSSE, ApiError } from '@/lib/api';
 */

export { api, ApiError } from './client';
export { parseSSE } from './sse';
export {
  settings,
  conversations,
  automations,
  usage,
  chat,
  type ChatStreamRequest,
  type ContentPart,
  type ChatContent,
} from './endpoints';
