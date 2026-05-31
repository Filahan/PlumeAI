import 'server-only';

import type { ToolResult } from '@/lib/agent/tools';

export type { ToolResult };

/** OpenAI function-calling schema shape (matches what the agent passes to the LLM). */
export interface ToolSchema {
  type: 'function';
  function: {
    name: string;
    description: string;
    parameters: {
      type: 'object';
      properties: Record<string, unknown>;
      required?: string[];
      additionalProperties?: boolean;
    };
  };
}

/** A first-party tool integration (e.g. Gmail). Each tool owns its OAuth state, its function
 *  schemas, and its execute dispatcher. The registry exposes only configured tools to the agent. */
export interface Tool {
  /** Unique identifier — matches the @ mention (e.g. 'gmail'). */
  name: string;
  /** Display name for UI. */
  label: string;
  /** Sentence-long description injected into the interviewer system prompt. */
  description: string;
  /** OpenAI function schemas. Function names should be namespaced (e.g. 'gmail_search'). */
  schemas: ToolSchema[];
  /** Execute one of this tool's functions by name. */
  execute(name: string, args: Record<string, unknown>, signal: AbortSignal): Promise<ToolResult>;
  /** True if the user has completed setup (e.g. OAuth tokens present). */
  isConfigured(): Promise<boolean>;
  /** Browser-facing URL that starts the setup flow (typically OAuth redirect). */
  setupUrl: string;
}
