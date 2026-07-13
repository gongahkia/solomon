// SPDX-License-Identifier: MIT

"use strict";

const native = require("./index.cjs");
const { createEmbeddedSdk } = require("./sdk-core.cjs");

module.exports = createEmbeddedSdk(native);
