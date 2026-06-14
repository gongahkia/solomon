async function renderStatus() {
  const statusMessage = document.querySelector("#status-message");
  const { decorumSettings } = await chrome.storage.local.get("decorumSettings");

  statusMessage.textContent = decorumSettings?.enabled
    ? "Decorum is enabled for LinkedIn pages."
    : "Decorum is currently disabled.";
}

renderStatus().catch((error) => {
  console.error("[decorum] Failed to render panel", error);
});
