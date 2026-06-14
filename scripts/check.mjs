import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const manifestPath = resolve(root, "extension", "manifest.json");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));

const requiredPermissions = new Set(["storage", "sidePanel"]);
const declaredPermissions = new Set(manifest.permissions ?? []);
const missingPermissions = [...requiredPermissions].filter(
  (permission) => !declaredPermissions.has(permission)
);

if (manifest.manifest_version !== 3) {
  throw new Error("manifest.json must use Manifest V3.");
}

if (!manifest.side_panel?.default_path) {
  throw new Error("manifest.json must declare side_panel.default_path.");
}

if (missingPermissions.length > 0) {
  throw new Error(`Missing permissions: ${missingPermissions.join(", ")}`);
}

if (!Array.isArray(manifest.content_scripts) || manifest.content_scripts.length === 0) {
  throw new Error("manifest.json must declare at least one content script.");
}

console.log("Extension manifest checks passed.");
