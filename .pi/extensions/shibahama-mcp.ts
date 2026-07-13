// SPDX-License-Identifier: MIT

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { registerPiShibahama } from "../../integrations/pi/shibahama-mcp-core.mjs";

export default function (pi: ExtensionAPI) {
  registerPiShibahama(pi, { Type });
}
