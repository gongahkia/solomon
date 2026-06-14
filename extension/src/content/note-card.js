(() => {
  const DEFAULT_SETTINGS = {
    enabled: true,
    mockNotesEnabled: true,
    minimumConfidence: 0.75
  };

  const MOCK_NOTE = {
    traceId: "trace:prototype-note-card",
    kind: "tonal_flag",
    label: "Prototype tonal flag",
    reason:
      "This is a placement test. Real notes stay hidden unless Decorum clears the confidence gate.",
    confidence: 0.91,
    model: "static-mock",
    sources: []
  };

  let mockNotePlaced = false;

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
      ["Post ID", post.id]
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

    const helpfulButton = document.createElement("button");
    helpfulButton.className = "decorum-note-button";
    helpfulButton.type = "button";
    helpfulButton.dataset.rating = "helpful";
    helpfulButton.setAttribute("aria-pressed", "false");
    helpfulButton.textContent = "Helpful";

    const notHelpfulButton = document.createElement("button");
    notHelpfulButton.className = "decorum-note-button";
    notHelpfulButton.type = "button";
    notHelpfulButton.dataset.rating = "not_helpful";
    notHelpfulButton.setAttribute("aria-pressed", "false");
    notHelpfulButton.textContent = "Not helpful";

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

    actions.append(label, helpfulButton, notHelpfulButton);
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
    meta.textContent = `Confidence ${formatConfidence(note.confidence)}. No retrieval sources used for this prototype note.`;

    header.append(icon, headerText);
    body.append(reason, meta);
    card.append(header, body, createRatingActions(note, post), createTrace(note, post));

    return card;
  }

  function appendNote(element, note, post) {
    if (element.querySelector(".decorum-note-card")) {
      return false;
    }

    const card = createNoteCard(note, post);
    element.append(card);
    element.dataset.decorumNoteState = "shown";

    sendRuntimeMessage({
      type: "DECORUM_NOTE_SHOWN",
      note,
      post,
      shownAt: new Date().toISOString()
    });

    return true;
  }

  async function maybeRenderMockNote(post, element) {
    const settings = await getSettings();

    if (
      mockNotePlaced ||
      !settings.enabled ||
      !settings.mockNotesEnabled ||
      MOCK_NOTE.confidence < settings.minimumConfidence
    ) {
      return;
    }

    const inserted = appendNote(element, MOCK_NOTE, post);

    if (inserted) {
      mockNotePlaced = true;
      console.info("[decorum] Rendered prototype note", {
        postId: post.id,
        traceId: MOCK_NOTE.traceId
      });
    }
  }

  window.addEventListener("decorum:post-detected", (event) => {
    const { post, element } = event.detail ?? {};

    if (!post || !element) {
      return;
    }

    maybeRenderMockNote(post, element).catch((error) => {
      console.error("[decorum] Failed to render prototype note", error);
    });
  });
})();
