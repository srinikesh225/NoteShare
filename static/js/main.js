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
