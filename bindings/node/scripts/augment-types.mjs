// SPDX-License-Identifier: MIT

import { readFile, writeFile } from "node:fs/promises";

const path = new URL("../index.d.ts", import.meta.url);
const marker = "// Shibahama JavaScript shims";
const additions = `
${marker}
export interface CapabilityDocument {
  schemaVersion: number
  version: string
  memorySchemaVersion: number
  capabilities: Array<string>
}

export declare function capabilities(): CapabilityDocument

export interface ShibahamaError extends Error {
  code: string
  severity: "recoverable" | "fatal"
  retryable: boolean
}

export type EmbedFunction = (text: string) => Array<number> | Promise<Array<number>>

export interface LangChainMemoryOptions {
  embed: EmbedFunction
  memoryKey?: string
  inputKey?: string
  outputKey?: string
  topK?: number
}

export interface Shibahama {
  eventRecords(): Record<string, unknown>
  audit(memoryId: string, nowUnix?: number | undefined | null): Record<string, unknown>
  consolidate(nowUnix?: number | undefined | null): Record<string, unknown>
  challenge(
    memoryId: string,
    reason: string,
    actor?: string | undefined | null,
    timestampUnix?: number | undefined | null,
  ): Record<string, unknown>
  affirm(
    memoryId: string,
    reason?: string | undefined | null,
    actor?: string | undefined | null,
    timestampUnix?: number | undefined | null,
  ): Record<string, unknown>
  correct(
    memoryId: string,
    proposedContent: string,
    reason?: string | undefined | null,
    actor?: string | undefined | null,
    timestampUnix?: number | undefined | null,
  ): Record<string, unknown>
  pin(
    memoryId: string,
    reason?: string | undefined | null,
    actor?: string | undefined | null,
    timestampUnix?: number | undefined | null,
  ): Record<string, unknown>
  unpin(
    memoryId: string,
    reason?: string | undefined | null,
    actor?: string | undefined | null,
    timestampUnix?: number | undefined | null,
  ): Record<string, unknown>
}

export declare class LangChainMemory {
  constructor(engine: Shibahama, options: LangChainMemoryOptions)
  readonly engine: Shibahama
  readonly embed: EmbedFunction
  readonly memoryKey: string
  readonly inputKey: string
  readonly outputKey: string
  readonly topK: number
  readonly memoryKeys: Array<string>
  readonly memoryVariables: Array<string>
  loadMemoryVariables(inputs: Record<string, unknown>): Promise<Record<string, string>>
  saveContext(inputs: Record<string, unknown>, outputs: Record<string, unknown>): Promise<void>
  clear(): Promise<void>
}
`;

const current = await readFile(path, "utf8");
const base = current.includes(marker) ? current.slice(0, current.indexOf(marker)).trimEnd() : current.trimEnd();

await writeFile(path, `${base}\n\n${additions.trimStart()}`);
