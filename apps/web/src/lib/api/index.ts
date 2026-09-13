/** Public façade for the FastAPI client layer.
 *
 *      import { settings, automations, usage, parseSSE, ApiError } from '@/lib/api';
 */

export { api, ApiError } from './client';
export { parseSSE } from './sse';
export { settings, automations, tools, usage } from './endpoints';
