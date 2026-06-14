import { mkdir } from "node:fs/promises";
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
await mkdir(resolve(root, ".tmp"), { recursive: true });

const server = await startStaticServer(fixturesDir);
const fixtureUrl = `${server.origin}/linkedin-feed.html`;
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
  await waitForExpression(page, "document.readyState === 'complete'", "fixture page load");

  await waitForExpression(
    page,
    "document.querySelectorAll('.decorum-note-card').length === 1",
    "initial tonal note insertion"
  );

  const initialDomState = await evaluate(page, `(() => {
    const flaggedPost = document.querySelector('[data-urn="urn:li:activity:1001"]');
    const neutralPost = document.querySelector('[data-urn="urn:li:activity:1002"]');
    const card = document.querySelector('.decorum-note-card');

    return {
      cardCount: document.querySelectorAll('.decorum-note-card').length,
      flaggedPostState: flaggedPost?.dataset.decorumNoteState,
      neutralPostState: neutralPost?.dataset.decorumNoteState,
      insertedAfterFlaggedPost: flaggedPost?.nextElementSibling === card,
      header: card?.querySelector('.decorum-note-header span')?.textContent,
      label: card?.querySelector('.decorum-note-label')?.textContent,
      traceId: card?.dataset.decorumTraceId,
      confidence: Number(card?.dataset.decorumConfidence)
    };
  })()`);

  assert(initialDomState.cardCount === 1, "exactly one note should render initially");
  assert(initialDomState.insertedAfterFlaggedPost, "note should be inserted directly under the flagged post");
  assert(initialDomState.neutralPostState !== "shown", "neutral post should not get a note");
  assert(
    initialDomState.header === "Readers added context they thought people might want to know.",
    "note header should match the intended Community Notes wording"
  );
  assert(initialDomState.label === "Engagement-bait: ", "first matching tonal label should be rendered");
  assert(initialDomState.traceId?.startsWith("trace:"), "rendered note should have a trace ID");
  assert(initialDomState.confidence >= 0.75, "rendered note should clear default confidence threshold");

  serviceWorker = await chromium.serviceWorker();
  await serviceWorker.send("Runtime.enable");

  await evaluate(
    serviceWorker,
    "chrome.storage.local.set({ decorumSettings: { enabled: true, tonalClassifierEnabled: true, minimumConfidence: 0.99 } })",
    { awaitPromise: true }
  );
  await waitForExpression(
    page,
    "document.querySelectorAll('.decorum-note-card').length === 0",
    "threshold should remove visible note"
  );

  await evaluate(
    serviceWorker,
    "chrome.storage.local.set({ decorumSettings: { enabled: true, tonalClassifierEnabled: true, minimumConfidence: 0.75 } })",
    { awaitPromise: true }
  );
  await waitForExpression(
    page,
    "document.querySelectorAll('.decorum-note-card').length === 1",
    "lowering threshold should re-render eligible note"
  );

  const secondTraceId = await evaluate(
    page,
    "document.querySelector('.decorum-note-card')?.dataset.decorumTraceId"
  );
  assert(secondTraceId !== initialDomState.traceId, "re-rendered note should get a unique trace ID");

  await evaluate(
    serviceWorker,
    "chrome.storage.local.set({ decorumSettings: { enabled: false, tonalClassifierEnabled: true, minimumConfidence: 0.75 } })",
    { awaitPromise: true }
  );
  await waitForExpression(
    page,
    "document.querySelectorAll('.decorum-note-card').length === 0",
    "disabling Decorum should remove visible notes"
  );

  await evaluate(
    serviceWorker,
    "chrome.storage.local.set({ decorumSettings: { enabled: true, tonalClassifierEnabled: true, minimumConfidence: 0.75 } })",
    { awaitPromise: true }
  );
  await waitForExpression(
    page,
    "document.querySelectorAll('.decorum-note-card').length === 1",
    "re-enabling Decorum should re-run classifier for known posts"
  );

  await evaluate(
    page,
    `(() => {
      const button = [...document.querySelectorAll('.decorum-note-button')]
        .find((candidate) => candidate.textContent === 'Not helpful');
      button.click();
      return true;
    })()`
  );

  const ledgerStateJson = await waitForExpression(
    serviceWorker,
    `chrome.storage.local.get('decorumNoteLedger').then(({ decorumNoteLedger }) => {
      const entries = decorumNoteLedger ?? [];
      const currentTraceId = entries[0]?.traceId;
      const traceIds = entries.map((entry) => entry.traceId);
      const uniqueTraceIds = new Set(traceIds);

      return entries.length >= 3 &&
        uniqueTraceIds.size === traceIds.length &&
        entries.some((entry) => entry.rating === 'not_helpful' && entry.falsePositive === true) &&
        entries.every((entry) => entry.postId === 'urn:li:activity:1001')
          ? JSON.stringify({ entries, currentTraceId })
          : '';
    })`,
    "rated ledger entry with unique traces",
    10000
  );
  const ledgerState =
    typeof ledgerStateJson === "string" ? JSON.parse(ledgerStateJson) : ledgerStateJson;

  assert(ledgerState.entries.length >= 3, "ledger should preserve each shown note as its own trace");
  assert(
    ledgerState.entries.some((entry) => entry.model === "local-tonal-rules-v1"),
    "ledger should record the local classifier model"
  );

  console.log("Runtime fixture test passed.");
} finally {
  page?.close();
  serviceWorker?.close();
  await chromium.close().catch(() => {});
  await server.close();
}
