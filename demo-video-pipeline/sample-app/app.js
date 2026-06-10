/* Sample Task Board — vanilla JS, no dependencies, no network calls.
 * Fictional seed data. Exposes window.__demo helpers the recorder can call,
 * plus stable data-testid hooks for Playwright. */

const SEED = [
  { id: 1, title: "Draft Q3 launch checklist", priority: "high", done: false },
  { id: 2, title: "Review onboarding copy", priority: "normal", done: false },
  { id: 3, title: "Sync with design on icons", priority: "normal", done: true },
  { id: 4, title: "Triage inbound feedback", priority: "high", done: false },
  { id: 5, title: "Archive last sprint board", priority: "low", done: true },
];

let tasks = SEED.map((t) => ({ ...t }));
let filter = "all";
let nextId = 6;

const $ = (sel) => document.querySelector(sel);
const listEl = $("#task-list");
const activityEl = $("#activity-list");

function logActivity(text) {
  const li = document.createElement("li");
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  li.innerHTML = `${text}<span class="when">${hh}:${mm}</span>`;
  activityEl.prepend(li);
}

function stats() {
  const total = tasks.length;
  const done = tasks.filter((t) => t.done).length;
  const open = total - done;
  const rate = total ? Math.round((done / total) * 100) : 0;
  $("#stat-total-value").textContent = total;
  $("#stat-open-value").textContent = open;
  $("#stat-done-value").textContent = done;
  $("#stat-rate-value").textContent = rate + "%";
}

function render() {
  listEl.innerHTML = "";
  const visible = tasks.filter((t) =>
    filter === "all" ? true : filter === "done" ? t.done : !t.done
  );
  for (const t of visible) {
    const li = document.createElement("li");
    li.className = "task" + (t.done ? " done" : "");
    li.dataset.id = t.id;
    li.dataset.testid = "task-" + t.id;
    const priClass = t.priority === "high" ? "pri-high" : "";
    li.innerHTML = `
      <button class="check" data-testid="check-${t.id}" aria-label="toggle"></button>
      <span class="title">${t.title}</span>
      <span class="tag ${priClass}">${t.priority}</span>`;
    li.querySelector(".check").addEventListener("click", () => toggle(t.id));
    listEl.appendChild(li);
  }
  stats();
}

function toggle(id) {
  const t = tasks.find((x) => x.id === id);
  if (!t) return;
  t.done = !t.done;
  logActivity(`${t.done ? "Completed" : "Reopened"} “${t.title}”`);
  render();
}

function addTask(title, priority = "normal") {
  title = (title || "").trim();
  if (!title) return;
  tasks.unshift({ id: nextId++, title, priority, done: false });
  logActivity(`Added “${title}”`);
  render();
}

function setFilter(f) {
  filter = f;
  document.querySelectorAll(".filter").forEach((b) =>
    b.classList.toggle("is-active", b.dataset.filter === f)
  );
  render();
}

// Wiring
$("#task-list");
$("[data-testid=add-form]").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("#new-task");
  addTask(input.value, "high");
  input.value = "";
});
document.querySelectorAll(".filter").forEach((b) =>
  b.addEventListener("click", () => setFilter(b.dataset.filter))
);

// Helpers the recorder can drive deterministically (no reliance on focus/typing speed)
window.__demo = { addTask, toggle, setFilter, get tasks() { return tasks; } };

logActivity("Board loaded");
render();
