// Master Dentizt — lightweight UI helpers (no framework, no build step)

document.addEventListener("submit", function (e) {
  const form = e.target;
  if (form.hasAttribute("data-confirm")) {
    const msg = form.getAttribute("data-confirm") || "Are you sure?";
    if (!window.confirm(msg)) {
      e.preventDefault();
    }
  }
});

document.addEventListener("click", function (e) {
  const btn = e.target.closest("[data-fill-today]");
  if (btn) {
    const targetId = btn.getAttribute("data-fill-today");
    const input = document.getElementById(targetId);
    if (input) {
      const d = new Date();
      const iso = d.toISOString().slice(0, 10);
      input.value = iso;
    }
  }
});

// Auto-hide flash messages after a while
window.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".flash").forEach(function (el) {
    setTimeout(function () {
      el.style.transition = "opacity 0.6s";
      el.style.opacity = "0";
      setTimeout(function () { el.remove(); }, 700);
    }, 6000);
  });
});
