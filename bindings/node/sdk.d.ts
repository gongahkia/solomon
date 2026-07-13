import type {
  DegradedRecallResult,
  MemoryItem,
  MemoryScope,
  RecallCandidate,
  RecallOptions,
  Shibahama,
  WhyTrace,
  WriteOptions,
} from "shibahama";

export type EmbeddedCapturePolicy = {
  mode?: "manual" | "suggest" | "automatic";
  actors?: Partial<Record<"human" | "agent" | "automation" | "service", boolean>>;
  sources?: Partial<Record<"user" | "agent" | "file" | "web" | "tool", boolean>>;
  scopes?: Partial<Record<"repository" | "team", boolean>>;
  minimumConfidencePercent?: number;
};

export type EmbeddedRecallPolicy = {
  maxCandidates?: number;
  maxContextTokens?: number;
  allowCold?: boolean;
  allowInstructions?: boolean;
  scopes?: Partial<Record<"repository" | "team", boolean>>;
};

export type EmbeddedPolicy = {
  capture?: EmbeddedCapturePolicy;
  recall?: EmbeddedRecallPolicy;
};

export type EmbeddedShibahamaOptions = {
  path: string;
  dimensions: number;
  capacity?: number;
  scope: MemoryScope;
  policy?: EmbeddedPolicy;
};

export type EmbeddedWriteOptions = Omit<WriteOptions, "scope">;
export type EmbeddedRecallOptions = Omit<RecallOptions, "scope">;

export class EmbeddedShibahama {
  constructor(options: EmbeddedShibahamaOptions);
  readonly engine: Shibahama;
  readonly scope: MemoryScope;
  readonly policy: Readonly<Required<EmbeddedPolicy>>;
  static open(options: EmbeddedShibahamaOptions): EmbeddedShibahama;
  withScope(scope: MemoryScope): EmbeddedShibahama;
  simulateCapturePolicy(sourceKind: string, options?: Omit<EmbeddedWriteOptions, "vector">): Record<string, unknown>;
  simulateRecallPolicy(topK: number, options?: EmbeddedRecallOptions): Record<string, unknown>;
  write(content: string, options?: EmbeddedWriteOptions): MemoryItem;
  recall(queryVector: number[], topK: number, options?: EmbeddedRecallOptions): RecallCandidate[];
  recallWithDegradation(queryVector: number[], topK: number, options?: EmbeddedRecallOptions): DegradedRecallResult;
  timeline(queryVector: number[], topK: number, asOfUnix: number, options?: EmbeddedRecallOptions): RecallCandidate[];
  invalidate(memoryId: string, validToUnix: number): boolean;
  reinforce(memoryId: string, outcome?: string): boolean;
  why(memoryId: string, nowUnix?: number): WhyTrace | null;
  memoryItems(): MemoryItem[];
  eventRecords(): Record<string, unknown>;
}

export function createEmbeddedShibahama(options: EmbeddedShibahamaOptions): EmbeddedShibahama;
