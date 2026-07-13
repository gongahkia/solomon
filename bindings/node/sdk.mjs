// SPDX-License-Identifier: MIT

import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const native = require("./index.cjs");
const { createEmbeddedSdk } = require("./sdk-core.cjs");
const sdk = createEmbeddedSdk(native);

export const { EmbeddedShibahama, createEmbeddedShibahama } = sdk;
export default sdk;
