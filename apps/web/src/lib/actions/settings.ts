/** @deprecated Re-export shim — import from `@/lib/api` instead. */
import { settings } from '@/lib/api';
export const getSettings = settings.get;
export const updateSettings = settings.update;
export const disconnectTool = settings.disconnectTool;
