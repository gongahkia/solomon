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
  let scanTimer = null;

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

  async function scan(root = document) {
    const settings = await getSettings();

    if (!settings.enabled) {
      return [];
    }

    const elements = [...root.querySelectorAll(postSelector)].filter(isTopLevelPost);
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

    return posts;
  }

  function scheduleScan() {
    if (scanTimer) {
      window.clearTimeout(scanTimer);
    }

    scanTimer = window.setTimeout(() => {
      scanTimer = null;
      scan().catch((error) => console.error("[decorum] Post scan failed", error));
    }, 250);
  }

  const observer = new MutationObserver(scheduleScan);
  observer.observe(document.documentElement, {
    childList: true,
    subtree: true
  });

  window.Decorum = window.Decorum ?? {};
  window.Decorum.detector = {
    scan,
    getDetectedPosts: () => [...detectedPosts.values()]
  };

  scan().catch((error) => console.error("[decorum] Initial post scan failed", error));
})();
