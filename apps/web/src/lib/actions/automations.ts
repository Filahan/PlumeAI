/** @deprecated Re-export shim — import from `@/lib/api` instead. */
import { automations } from '@/lib/api';
export const listTasks = automations.list;
export const createTask = automations.create;
export const updateTask = automations.update;
export const deleteTask = automations.delete;
