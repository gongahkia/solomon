import { cp, mkdir, rm } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const sourceDir = resolve(root, "extension");
const outputDir = resolve(root, "dist");

await rm(outputDir, { recursive: true, force: true });
await mkdir(outputDir, { recursive: true });
await cp(sourceDir, outputDir, {
  recursive: true,
  filter: (source) => !source.includes("/.DS_Store")
});

console.log(`Built extension to ${outputDir}`);
