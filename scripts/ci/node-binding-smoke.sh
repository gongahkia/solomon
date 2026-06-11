#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

node --input-type=module <<'JS'
import { readFileSync } from "node:fs";
import { stat } from "node:fs/promises";

const root = "bindings/node";
const readme = `${root}/README.md`;

if (!(await stat(root)).isDirectory()) {
  throw new Error("bindings/node directory is missing");
}

if (!readFileSync(readme, "utf8").includes("Node")) {
  throw new Error("bindings/node README.md is missing expected content");
}

console.log("node binding lane present");
JS
