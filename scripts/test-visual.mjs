import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import {
  assert,
  buildTestExtension,
  evaluate,
  startChromium,
  startStaticServer,
  waitForExpression
} from "./lib/chromium-extension-harness.mjs";

const root = resolve(import.meta.dirname, "..");
const fixturesDir = resolve(root, "tests", "fixtures");
const snapshotPath = resolve(root, "tests", "visual", "note-card.snapshot.json");
const visualArtifactPath = resolve(root, ".tmp", "visual", "note-card.png");
const referencePath = resolve(root, "tests", "visual", "x-community-notes-reference.json");
const updateSnapshot = process.env.DECORUM_UPDATE_VISUAL === "1";
const strictScreenshotHash = process.env.DECORUM_STRICT_VISUAL !== "0";

function normalizeMetricSnapshot(actual) {
  return {
    viewport: actual.viewport,
    card: {
      width: actual.card.width,
      height: actual.card.height,
      marginTop: actual.card.marginTop,
      marginRight: actual.card.marginRight,
      marginBottom: actual.card.marginBottom,
      marginLeft: actual.card.marginLeft,
      borderRadius: actual.card.borderRadius,
      borderColor: actual.card.borderColor,
      backgroundColor: actual.card.backgroundColor,
      color: actual.card.color,
      fontFamily: actual.card.fontFamily,
      fontSize: actual.card.fontSize,
      lineHeight: actual.card.lineHeight
    },
    header: actual.header,
    screenshot: actual.screenshot
  };
}

function hashBuffer(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

async function readSnapshot() {
  try {
    return JSON.parse(await readFile(snapshotPath, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") {
      return null;
    }

    throw error;
  }
}

function compareSnapshot(expected, actual) {
  const expectedForComparison = strictScreenshotHash
    ? expected
    : {
        ...expected,
        screenshot: {
          ...expected.screenshot,
          sha256: actual.screenshot.sha256,
          bytes: actual.screenshot.bytes
        }
      };
  const expectedJson = JSON.stringify(expected, null, 2);
  const comparisonJson = JSON.stringify(expectedForComparison, null, 2);
  const actualJson = JSON.stringify(actual, null, 2);

  assert(
    comparisonJson === actualJson,
    `visual snapshot mismatch\nExpected:\n${expectedJson}\nActual:\n${actualJson}\nArtifact: ${visualArtifactPath}`
  );
}

async function compareReference(actual) {
  const reference = JSON.parse(await readFile(referencePath, "utf8"));

  assert(
    actual.header.text === reference.headerText,
    "note header should match the Community Notes reference wording"
  );
  assert(actual.card.borderColor === reference.card.borderColor, "note border color drifted");
  assert(
    actual.card.backgroundColor === reference.card.backgroundColor,
    "note background color drifted"
  );
  assert(actual.card.color === reference.card.textColor, "note text color drifted");
  assert(actual.card.borderRadius === reference.card.borderRadius, "note radius drifted");
  assert(actual.header.color === reference.header.color, "note header color drifted");
  assert(
    actual.header.backgroundColor === reference.header.backgroundColor,
    "note header background drifted"
  );
  assert(actual.header.fontSize === reference.header.fontSize, "note header font size drifted");
  assert(actual.header.fontWeight === reference.header.fontWeight, "note header weight drifted");
  assert(actual.header.iconColor === reference.header.iconColor, "note icon color drifted");
  assert(actual.header.iconWidth === reference.header.iconWidth, "note icon width drifted");
  assert(actual.header.iconHeight === reference.header.iconHeight, "note icon height drifted");
}

const server = await startStaticServer(fixturesDir);
const fixtureUrl = `${server.origin}/linkedin-feed.html`;
const extensionDir = await buildTestExtension(root, [`${server.origin}/*`]);
const chromium = await startChromium({
  extensionDir,
  startUrl: fixtureUrl,
  viewport: "1100,900"
});

let page;

try {
  page = await chromium.page();
  await page.send("Runtime.enable");
  await page.send("Page.enable");
  await waitForExpression(page, "document.readyState === 'complete'", "fixture page load");
  await waitForExpression(
    page,
    "document.querySelectorAll('.decorum-note-card').length === 1",
    "visual note insertion"
  );

  const metrics = await evaluate(page, `(() => {
    const card = document.querySelector('.decorum-note-card');
    const header = card.querySelector('.decorum-note-header span');
    const icon = card.querySelector('.decorum-note-icon');
    const style = getComputedStyle(card);
    const headerStyle = getComputedStyle(header);
    const iconStyle = getComputedStyle(icon);
    const rect = card.getBoundingClientRect();

    return {
      viewport: {
        width: window.innerWidth,
        height: window.innerHeight,
        devicePixelRatio: window.devicePixelRatio
      },
      card: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        marginTop: style.marginTop,
        marginRight: style.marginRight,
        marginBottom: style.marginBottom,
        marginLeft: style.marginLeft,
        borderRadius: style.borderRadius,
        borderColor: style.borderColor,
        backgroundColor: style.backgroundColor,
        color: style.color,
        fontFamily: style.fontFamily,
        fontSize: style.fontSize,
        lineHeight: style.lineHeight
      },
      header: {
        text: header.textContent,
        color: headerStyle.color,
        backgroundColor: getComputedStyle(card.querySelector('.decorum-note-header')).backgroundColor,
        fontSize: headerStyle.fontSize,
        fontWeight: headerStyle.fontWeight,
        iconColor: iconStyle.fill,
        iconText: icon.textContent,
        iconWidth: iconStyle.width,
        iconHeight: iconStyle.height
      }
    };
  })()`);

  const screenshot = await page.send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: true,
    clip: {
      x: metrics.card.x,
      y: metrics.card.y,
      width: metrics.card.width,
      height: metrics.card.height,
      scale: 1
    }
  });
  const screenshotBuffer = Buffer.from(screenshot.data, "base64");
  await mkdir(resolve(root, ".tmp", "visual"), { recursive: true });
  await writeFile(visualArtifactPath, screenshotBuffer);

  const actual = normalizeMetricSnapshot({
    ...metrics,
    screenshot: {
      sha256: hashBuffer(screenshotBuffer),
      bytes: screenshotBuffer.length,
      width: metrics.card.width,
      height: metrics.card.height
    }
  });

  const expected = await readSnapshot();

  if (updateSnapshot || !expected) {
    await mkdir(resolve(root, "tests", "visual"), { recursive: true });
    await writeFile(snapshotPath, `${JSON.stringify(actual, null, 2)}\n`);
    console.log(`Visual snapshot ${expected ? "updated" : "created"} at ${snapshotPath}`);
  } else {
    await compareReference(actual);
    compareSnapshot(expected, actual);
    console.log(`Visual snapshot test passed. Artifact: ${visualArtifactPath}`);
  }
} finally {
  page?.close();
  await chromium.close().catch(() => {});
  await server.close();
}
