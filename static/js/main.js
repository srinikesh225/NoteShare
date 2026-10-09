// Progressive enhancement only: every page works without JavaScript.

// Add a dismiss button to each flash message.
document.querySelectorAll(".flash").forEach((flash) => {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "flash-dismiss";
  button.setAttribute("aria-label", "Dismiss message");
  button.textContent = "×";
  button.addEventListener("click", () => flash.remove());
  flash.appendChild(button);
});

// Warn about files over the upload limit before they are sent. The server
// enforces the same limit (MAX_CONTENT_LENGTH) regardless.
document.querySelectorAll("input[type=file][data-max-bytes]").forEach((input) => {
  const maxBytes = Number(input.dataset.maxBytes);
  input.addEventListener("change", () => {
    const file = input.files[0];
    const tooLarge = file && file.size > maxBytes;
    input.setCustomValidity(
      tooLarge ? "This file is larger than the 10 MiB limit. Choose a smaller file." : ""
    );
    if (tooLarge) input.reportValidity();
  });
});
