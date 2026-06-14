(() => {
  const POST_SELECTORS = [
    "div.feed-shared-update-v2",
    "article[data-urn*='activity']",
    "div[data-urn^='urn:li:activity:']",
    "div[data-id^='urn:li:activity:']"
  ];

  const TEXT_SELECTORS = [
    ".update-components-text",
    ".feed-shared-update-v2__description",
    ".feed-shared-inline-show-more-text",
    "[data-test-id='main-feed-activity-card'] .break-words"
  ];

  const AUTHOR_SELECTORS = [
    ".update-components-actor__name",
    ".feed-shared-actor__name",
    ".update-components-actor__title"
  ];

  const DEFAULT_SETTINGS = {
    enabled: true,
    minimumConfidence: 0.75
  };

  const postSelector = POST_SELECTORS.join(",");
  const detectedPosts = new Map();
  const scannedElements = new WeakSet();
  const pendingRoots = new Set();
  const metrics = {
    scanCount: 0,
    observedMutationCount: 0,
    observedNodeCount: 0,
    scannedCandidateCount: 0,
    detectedPostCount: 0,
    lastScanDurationMs: 0
  };
  let scanTimer = null;

  function isSupportedSurface() {
    if (document.documentElement.dataset.decorumFixture === "linkedin-feed") {
      return true;
    }

    if (location.hostname !== "www.linkedin.com") {
      return false;
    }

    return location.pathname === "/feed/" || location.pathname.startsWith("/posts/");
  }

  function normalizeText(value) {
    return value.replace(/\s+/g, " ").trim();
  }

  function stableHash(input) {
    let hash = 2166136261;

    for (let index = 0; index < input.length; index += 1) {
      hash ^= input.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }

    return (hash >>> 0).toString(36);
  }

  function firstTextFrom(root, selectors) {
    for (const selector of selectors) {
      const element = root.querySelector(selector);
      const text = normalizeText(element?.innerText ?? "");

      if (text) {
        return text;
      }
    }

    return "";
  }

  function extractLinkedInId(element, text) {
    const directId =
      element.getAttribute("data-urn") ??
      element.getAttribute("data-id") ??
      element.dataset.urn ??
      element.dataset.id;

    if (directId) {
      return directId;
    }

    const descendantWithId = element.querySelector("[data-urn], [data-id]");
    const descendantId =
      descendantWithId?.getAttribute("data-urn") ??
      descendantWithId?.getAttribute("data-id");

    if (descendantId) {
      return descendantId;
    }

    return `decorum:${stableHash(`${location.href}:${text.slice(0, 500)}`)}`;
  }

  function isTopLevelPost(element) {
    const parentPost = element.parentElement?.closest(postSelector);
    return !parentPost;
  }

  function getCandidatePostElements(root) {
    const candidates = [];

    if (root.nodeType === Node.ELEMENT_NODE) {
      if (root.matches(postSelector)) {
        candidates.push(root);
      }

      candidates.push(...root.querySelectorAll(postSelector));
    } else if (root.querySelectorAll) {
      candidates.push(...root.querySelectorAll(postSelector));
    }

    return [...new Set(candidates)].filter(isTopLevelPost);
  }

  function extractPost(element) {
    const text = firstTextFrom(element, TEXT_SELECTORS);

    if (!text) {
      return null;
    }

    const id = extractLinkedInId(element, text);

    return {
      id,
      author: firstTextFrom(element, AUTHOR_SELECTORS),
      text,
      url: location.href,
      detectedAt: new Date().toISOString()
    };
  }

  async function getSettings() {
    try {
      const { decorumSettings } = await chrome.storage.local.get("decorumSettings");
      return {
        ...DEFAULT_SETTINGS,
        ...decorumSettings
      };
    } catch (error) {
      console.warn("[decorum] Falling back to default detector settings", error);
      return DEFAULT_SETTINGS;
    }
  }

  async function sendRuntimeMessage(message) {
    try {
      await chrome.runtime.sendMessage(message);
    } catch (error) {
      console.warn("[decorum] Failed to persist detected post", error);
    }
  }

  function emitPostDetected(post, element) {
    detectedPosts.set(post.id, post);
    element.dataset.decorumPostId = post.id;

    window.dispatchEvent(
      new CustomEvent("decorum:post-detected", {
        detail: {
          post,
          element
        }
      })
    );

    console.info("[decorum] Detected LinkedIn post", {
      id: post.id,
      author: post.author || "unknown",
      textPreview: post.text.slice(0, 120)
    });

    sendRuntimeMessage({
      type: "DECORUM_POST_DETECTED",
      post
    });
  }

  function publishMetrics() {
    document.documentElement.dataset.decorumScanCount = String(metrics.scanCount);
    document.documentElement.dataset.decorumDetectedPostCount = String(
      metrics.detectedPostCount
    );
    document.documentElement.dataset.decorumScannedCandidateCount = String(
      metrics.scannedCandidateCount
    );
  }

  async function scanRoots(roots) {
    const startedAt = performance.now();
    metrics.scanCount += 1;
    const settings = await getSettings();

    if (!settings.enabled || !isSupportedSurface()) {
      publishMetrics();
      return [];
    }

    const elements = [...new Set(roots.flatMap(getCandidatePostElements))];
    metrics.scannedCandidateCount += elements.length;
    const posts = [];

    for (const element of elements) {
      if (scannedElements.has(element)) {
        continue;
      }

      scannedElements.add(element);
      const post = extractPost(element);

      if (!post || detectedPosts.has(post.id)) {
        continue;
      }

      posts.push(post);
      emitPostDetected(post, element);
    }

    metrics.detectedPostCount = detectedPosts.size;
    metrics.lastScanDurationMs = Math.round((performance.now() - startedAt) * 100) / 100;
    publishMetrics();
    return posts;
  }

  function scan(root = document) {
    return scanRoots([root]);
  }

  function scheduleScan(root = document) {
    pendingRoots.add(root);

    if (scanTimer) {
      window.clearTimeout(scanTimer);
    }

    scanTimer = window.setTimeout(() => {
      scanTimer = null;
      const roots = [...pendingRoots];
      pendingRoots.clear();
      scanRoots(roots).catch((error) => console.error("[decorum] Post scan failed", error));
    }, 250);
  }

  function shouldScanAddedNode(node) {
    if (node.nodeType !== Node.ELEMENT_NODE) {
      return false;
    }

    return node.matches(postSelector) || Boolean(node.querySelector(postSelector));
  }

  const targetedObserver = new MutationObserver((mutations) => {
    metrics.observedMutationCount += mutations.length;

    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        metrics.observedNodeCount += 1;

        if (shouldScanAddedNode(node)) {
          scheduleScan(node);
        }
      }
    }
  });

  targetedObserver.observe(document.documentElement, {
    childList: true,
    subtree: true
  });

  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName === "local" && changes.decorumSettings) {
      scheduleScan();
    }
  });

  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type === "DECORUM_SETTINGS_UPDATED") {
      scheduleScan();
    }
  });

  window.Decorum = window.Decorum ?? {};
  window.Decorum.detector = {
    scan,
    getDetectedPosts: () => [...detectedPosts.values()],
    isSupportedSurface,
    getMetrics: () => ({ ...metrics })
  };

  window.setTimeout(() => {
    scan().catch((error) => console.error("[decorum] Initial post scan failed", error));
  }, 0);
})();
