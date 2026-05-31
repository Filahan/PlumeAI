/** @deprecated Re-export shim — import from `@/lib/api` instead. */
import { conversations } from '@/lib/api';
export const listConversations = conversations.list;
export const createConversation = conversations.create;
export const addMessage = conversations.addMessage;
export const updateMessage = conversations.updateMessage;
export const renameConversation = conversations.rename;
export const setConversationModel = conversations.setModel;
export const deleteConversation = conversations.delete;
