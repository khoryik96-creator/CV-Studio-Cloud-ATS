"use strict";
(() => {
  const button = document.getElementById("staffEnroll");
  const status = document.getElementById("staffStatus");
  let token = window.location.hash.slice(1);
  if (window.location.hash) history.replaceState(null, "", window.location.pathname);
  if (!/^[A-Za-z0-9_-]{43}$/.test(token)) {
    status.textContent = "Open the latest staff access link from your administrator.";
    return;
  }
  button.disabled = false;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const response = await fetch("/staff/enroll", {
        method: "POST", credentials: "same-origin", cache: "no-store", redirect: "error",
        headers: {"Content-Type": "application/json"}, body: JSON.stringify({token}),
      });
      if (response.ok) {
        token = "";
        window.location.replace("/cloud-ui");
        return;
      }
      status.textContent = response.status === 409
        ? "Sign out of your current session, then reopen your staff link."
        : "This staff link is unavailable. Ask your administrator for a new link.";
    } catch {
      status.textContent = "Connection unavailable. Try again.";
    }
    button.disabled = false;
  });
})();
