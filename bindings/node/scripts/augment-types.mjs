// SPDX-License-Identifier: MIT

import { readFile, writeFile } from "node:fs/promises";

const path = new URL("../index.d.ts", import.meta.url);
const marker = "// Shibahama JavaScript shims";
const additions = `
${marker}
export type EmbedFunction = (text: string) => Array<number> | Promise<Array<number>>

export interface LangChainMemoryOptions {
  embed: EmbedFunction
  memoryKey?: string
  inputKey?: string
  outputKey?: string
  topK?: number
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
