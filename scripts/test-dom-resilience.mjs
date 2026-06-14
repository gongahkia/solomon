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

const server = await startStaticServer(fixturesDir);
const fixtureUrl = `${server.origin}/linkedin-feed-variants.html`;
const extensionDir = await buildTestExtension(root, [`${server.origin}/*`]);
const chromium = await startChromium({
  extensionDir,
  startUrl: fixtureUrl
});

let page;
let serviceWorker;

try {
  page = await chromium.page();
  await page.send("Runtime.enable");
  await waitForExpression(page, "document.readyState === 'complete'", "variant fixture page load");
  await waitForExpression(
    page,
    "Number(document.documentElement.dataset.decorumDetectedPostCount) === 4",
    "variant post detection"
  );
  await waitForExpression(
    page,
    "document.querySelectorAll('.decorum-note-card').length === 3",
    "variant note rendering"
  );

  serviceWorker = await chromium.serviceWorker();
  await serviceWorker.send("Runtime.enable");

  const detectedState = await waitForExpression(
    serviceWorker,
    `chrome.storage.local.get('decorumDetectedPosts').then(({ decorumDetectedPosts }) => {
      const posts = decorumDetectedPosts ?? [];
      const ids = posts.map((post) => post.id);
      return posts.length === 4 &&
        ids.includes('urn:li:activity:2001') &&
        ids.includes('urn:li:activity:2002') &&
        ids.includes('urn:li:activity:2003') &&
        !ids.includes('urn:li:activity:should-not-detect')
          ? JSON.stringify({ ids, posts })
          : '';
    })`,
    "stored variant detections"
  );
  const parsedState =
    typeof detectedState === "string" ? JSON.parse(detectedState) : detectedState;

  assert(parsedState.posts.length === 4, "variant fixture should persist exactly four posts");
  assert(
    parsedState.posts.some((post) => post.id.startsWith("decorum:")),
    "variant fixture should exercise fallback post IDs"
  );

  const beforeChurn = await evaluate(page, `(() => ({
    scanCount: Number(document.documentElement.dataset.decorumScanCount),
    candidateCount: Number(document.documentElement.dataset.decorumScannedCandidateCount)
  }))()`);

  await evaluate(page, `(() => {
    const container = document.createElement('section');
    container.id = 'unrelated-dom-churn';
    for (let index = 0; index < 30; index += 1) {
      const div = document.createElement('div');
      div.textContent = 'unrelated ' + index;
      container.append(div);
    }
    document.body.append(container);
    return true;
  })()`);

  await new Promise((resolveWait) => setTimeout(resolveWait, 500));

  const afterChurn = await evaluate(page, `(() => ({
    scanCount: Number(document.documentElement.dataset.decorumScanCount),
    candidateCount: Number(document.documentElement.dataset.decorumScannedCandidateCount)
  }))()`);

  assert(
    afterChurn.scanCount === beforeChurn.scanCount,
    "unrelated DOM churn should not schedule a post scan"
  );
  assert(
    afterChurn.candidateCount === beforeChurn.candidateCount,
    "unrelated DOM churn should not add candidate scans"
  );

  console.log("DOM resilience test passed.");
} finally {
  page?.close();
  serviceWorker?.close();
  await chromium.close().catch(() => {});
  await server.close();
}
