// SPDX-License-Identifier: MIT

import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const native = require("./index.cjs");

export const { RecallStream, Shibahama, version } = native;
export default native;
