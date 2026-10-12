const toggle = document.querySelector("#menu-toggle");
const sidebar = document.querySelector("#sidebar");
if (toggle && sidebar) {
  toggle.addEventListener("click", () => {
    const open = sidebar.classList.toggle("open");
    toggle.setAttribute("aria-expanded", String(open));
  });
}
document.querySelectorAll(".notice").forEach((notice) => {
  window.setTimeout(() => notice.classList.add("notice-fade"), 5000);
});

document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});
