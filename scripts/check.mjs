import { spawnSync } from "node:child_process";
import { readdir, readFile, stat } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const extensionDir = resolve(root, "extension");
const gatewayDir = resolve(root, "gateway");
const manifestPath = resolve(root, "extension", "manifest.json");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));

async function assertFileExists(path, label) {
  const stats = await stat(path).catch(() => null);

  if (!stats?.isFile()) {
    throw new Error(`${label} does not exist: ${path}`);
  }
}

async function collectFiles(directory, extension, files = []) {
  const entries = await readdir(directory, { withFileTypes: true });

  for (const entry of entries) {
    const path = resolve(directory, entry.name);

    if (entry.isDirectory()) {
      await collectFiles(path, extension, files);
    } else if (entry.isFile() && path.endsWith(extension)) {
      files.push(path);
    }
  }

  return files;
}

function checkJavaScriptSyntax(path) {
  const result = spawnSync(process.execPath, ["--check", path], {
    encoding: "utf8"
  });

  if (result.status !== 0) {
    throw new Error(result.stderr || result.stdout || `Syntax check failed: ${path}`);
  }
}

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

await assertFileExists(resolve(extensionDir, manifest.background.service_worker), "Background service worker");
await assertFileExists(resolve(extensionDir, manifest.side_panel.default_path), "Side panel");

for (const contentScript of manifest.content_scripts) {
  for (const scriptPath of contentScript.js ?? []) {
    await assertFileExists(resolve(extensionDir, scriptPath), "Content script");
  }

  for (const stylePath of contentScript.css ?? []) {
    await assertFileExists(resolve(extensionDir, stylePath), "Content stylesheet");
  }
}

const gatewayStats = await stat(gatewayDir).catch(() => null);
const JavaScriptFiles = [
  ...(await collectFiles(resolve(root, "scripts"), ".mjs")),
  ...(await collectFiles(extensionDir, ".js")),
  ...(gatewayStats?.isDirectory() ? await collectFiles(gatewayDir, ".js") : [])
];

for (const path of JavaScriptFiles) {
  checkJavaScriptSyntax(path);
}

console.log(`Extension checks passed for ${JavaScriptFiles.length} scripts.`);
