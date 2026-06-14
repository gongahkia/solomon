(() => {
  const DEFAULT_SETTINGS = {
    enabled: true,
    tonalClassifierEnabled: true,
    minimumConfidence: 0.75
  };

  const knownPosts = new Map();
  const renderedPosts = new Map();
  let reevaluateTimer = null;

  function formatConfidence(value) {
    return `${Math.round(value * 100)}%`;
  }

  async function getSettings() {
    try {
      const { decorumSettings } = await chrome.storage.local.get("decorumSettings");
      return {
        ...DEFAULT_SETTINGS,
        ...decorumSettings
      };
    } catch (error) {
      console.warn("[decorum] Falling back to default note settings", error);
      return DEFAULT_SETTINGS;
    }
  }

  async function sendRuntimeMessage(message) {
    try {
      await chrome.runtime.sendMessage(message);
    } catch (error) {
      const expectedDuringEarlyPrototype =
        error?.message?.includes("Receiving end does not exist") ||
        error?.message?.includes("Could not establish connection");

      if (!expectedDuringEarlyPrototype) {
        console.warn("[decorum] Runtime message failed", error);
      }
    }
  }

  async function requestClassification(post) {
    try {
      const response = await chrome.runtime.sendMessage({
        type: "DECORUM_CLASSIFY_POST",
        post
      });

      if (!response?.ok) {
        throw new Error(response?.error ?? "Classification failed");
      }

      return response;
    } catch (error) {
      console.warn("[decorum] Classification request failed", error);
      return null;
    }
  }

  function createTrace(note, post) {
    const details = document.createElement("details");
    details.className = "decorum-note-trace";

    const summary = document.createElement("summary");
    summary.textContent = "Why flagged";

    const list = document.createElement("dl");
    const rows = [
      ["Trace ID", note.traceId],
      ["Signal", note.kind],
      ["Confidence", formatConfidence(note.confidence)],
      ["Model", note.model],
      ["Post ID", post.id],
      ["Evidence", note.evidence?.join(", ") || "none"]
    ];

    for (const [label, value] of rows) {
      const term = document.createElement("dt");
      term.textContent = label;

      const description = document.createElement("dd");
      description.textContent = value;

      list.append(term, description);
    }

    details.append(summary, list);
    return details;
  }

  function updatePressedState(card, selectedRating) {
    for (const button of card.querySelectorAll(".decorum-note-button")) {
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.rating === selectedRating)
      );
    }
  }

  function createRatingActions(note, post) {
    const actions = document.createElement("div");
    actions.className = "decorum-note-actions";

    const label = document.createElement("span");
    label.textContent = "Rate this note";

    const ratings = [
      ["helpful", "Helpful"],
      ["incorrect", "Incorrect"],
      ["unfair_tone_read", "Unfair"],
      ["missing_context", "Missing context"],
      ["too_noisy", "Too noisy"]
    ];

    const buttons = ratings.map(([rating, text]) => {
      const button = document.createElement("button");
      button.className = "decorum-note-button";
      button.type = "button";
      button.dataset.rating = rating;
      button.setAttribute("aria-pressed", "false");
      button.textContent = text;
      return button;
    });

    actions.addEventListener("click", (event) => {
      const button = event.target.closest(".decorum-note-button");

      if (!button) {
        return;
      }

      const rating = button.dataset.rating;
      updatePressedState(actions, rating);

      sendRuntimeMessage({
        type: "DECORUM_NOTE_RATED",
        traceId: note.traceId,
        postId: post.id,
        rating,
        ratedAt: new Date().toISOString()
      });
    });

    actions.append(label, ...buttons);
    return actions;
  }

  function createNoteCard(note, post) {
    const card = document.createElement("aside");
    card.className = "decorum-note-card";
    card.dataset.decorumTraceId = note.traceId;
    card.setAttribute("aria-label", "Decorum context note");

    const header = document.createElement("div");
    header.className = "decorum-note-header";

    const icon = document.createElement("i");
    icon.className = "decorum-note-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "i";

    const headerText = document.createElement("span");
    headerText.textContent = "Readers added context they thought people might want to know.";

    const body = document.createElement("div");
    body.className = "decorum-note-body";

    const reason = document.createElement("p");
    const label = document.createElement("span");
    label.className = "decorum-note-label";
    label.textContent = `${note.label}: `;
    reason.append(label, note.reason);

    const meta = document.createElement("p");
    meta.className = "decorum-note-meta";
    meta.textContent = `Confidence ${formatConfidence(note.confidence)}. This flags a writing pattern, not the author. No factual retrieval used.`;

    header.append(icon, headerText);
    body.append(reason, meta);
    card.append(header, body, createRatingActions(note, post), createTrace(note, post));

    return card;
  }

  function appendNote(element, classification, post) {
    const note = classification.note;

    if (findExistingCard(post.id)) {
      return false;
    }

    const card = createNoteCard(note, post);
    card.dataset.decorumPostId = post.id;
    card.dataset.decorumConfidence = String(note.confidence);

    element.insertAdjacentElement("afterend", card);
    element.dataset.decorumNoteState = "shown";
    renderedPosts.set(post.id, {
      note,
      element,
      card
    });

    sendRuntimeMessage({
      type: "DECORUM_NOTE_SHOWN",
      note,
      classification,
      post,
      shownAt: new Date().toISOString()
    });

    return true;
  }

  function findExistingCard(postId) {
    return document.querySelector(
      `.decorum-note-card[data-decorum-post-id="${CSS.escape(postId)}"]`
    );
  }

  function removeRenderedNote(postId, reason) {
    const rendered = renderedPosts.get(postId);
    const card = rendered?.card ?? findExistingCard(postId);

    if (card) {
      card.remove();
    }

    if (rendered?.element) {
      rendered.element.dataset.decorumNoteState = reason;
    }

    renderedPosts.delete(postId);
  }

  function removeAllRenderedNotes(reason) {
    for (const postId of [...renderedPosts.keys()]) {
      removeRenderedNote(postId, reason);
    }

    for (const card of document.querySelectorAll(".decorum-note-card")) {
      card.remove();
    }
  }

  async function maybeRenderNote(post, element) {
    if (renderedPosts.has(post.id) || findExistingCard(post.id)) {
      return;
    }

    const classification = await requestClassification(post);
    const note = classification?.note ?? null;

    if (!note) {
      element.dataset.decorumNoteState = "skipped";
      return;
    }

    const inserted = appendNote(element, classification, post);

    if (inserted) {
      console.info("[decorum] Rendered tonal note", {
        postId: post.id,
        traceId: note.traceId
      });
    }
  }

  async function enforceSettings() {
    const settings = await getSettings();

    if (!settings.enabled || !settings.tonalClassifierEnabled) {
      removeAllRenderedNotes("hidden_by_settings");
      return;
    }

    for (const [postId, rendered] of renderedPosts) {
      if (rendered.note.confidence < settings.minimumConfidence) {
        removeRenderedNote(postId, "below_threshold");
      }
    }

    scheduleReevaluation();
  }

  function scheduleReevaluation() {
    if (reevaluateTimer) {
      window.clearTimeout(reevaluateTimer);
    }

    reevaluateTimer = window.setTimeout(() => {
      reevaluateTimer = null;

      for (const { post, element } of knownPosts.values()) {
        maybeRenderNote(post, element).catch((error) => {
          console.error("[decorum] Failed to reevaluate post", error);
        });
      }
    }, 100);
  }

  window.addEventListener("decorum:post-detected", (event) => {
    const { post, element } = event.detail ?? {};

    if (!post || !element) {
      return;
    }

    knownPosts.set(post.id, {
      post,
      element
    });

    maybeRenderNote(post, element).catch((error) => {
      console.error("[decorum] Failed to render tonal note", error);
    });
  });

  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName === "local" && changes.decorumSettings) {
      enforceSettings().catch((error) => {
        console.error("[decorum] Failed to enforce settings", error);
      });
    }
  });

  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type === "DECORUM_SETTINGS_UPDATED") {
      enforceSettings().catch((error) => {
        console.error("[decorum] Failed to enforce broadcast settings", error);
      });
    }
  });
})();
