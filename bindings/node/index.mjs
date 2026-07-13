// SPDX-License-Identifier: MIT

import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const native = require("./index.cjs");

export const {
  LangChainMemory,
  RecallStream,
  Shibahama,
  capabilities,
  canonicalizeExtractionCandidateJson,
  version,
} = native;
export default native;
