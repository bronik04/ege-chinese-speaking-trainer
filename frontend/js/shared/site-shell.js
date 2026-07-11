const accountLinks = document.querySelectorAll("[data-account-link]");

async function updateAccountLinks() {
  if (!accountLinks.length) return;
  let user = null;
  try {
    const response = await fetch("/api/auth/me");
    if (response.ok) user = (await response.json()).user;
  } catch (_) {}
  accountLinks.forEach(link => {
    link.classList.toggle("signed-in", Boolean(user));
    const label = link.querySelector("[data-account-label]");
    if (label) label.textContent = user?.email || "Войти";
    link.setAttribute("aria-label", user ? `Личный кабинет: ${user.email}` : "Войти в личный кабинет");
  });
}

document.querySelectorAll("[data-current-year]").forEach(node => {
  node.textContent = new Date().getFullYear();
});

updateAccountLinks();
