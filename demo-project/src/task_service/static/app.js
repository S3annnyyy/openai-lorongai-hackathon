const taskList = document.getElementById("task-list");
const emptyState = document.getElementById("empty");
const reportPanel = document.getElementById("report");
const statusFilter = document.getElementById("status-filter");
const form = document.getElementById("task-form");
const refreshBtn = document.getElementById("refresh");

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const bodyText = await response.text();
  const payload = bodyText ? JSON.parse(bodyText) : null;
  if (!response.ok) {
    throw new Error(payload?.detail || "Request failed");
  }
  return payload;
}

function renderTask(task) {
  const li = document.createElement("li");
  li.className = "item";
  const title = document.createElement("span");
  title.textContent = `${task.title} (${task.priority})`;
  const status = document.createElement("span");
  status.textContent = task.completed ? "done" : "open";
  const toggle = document.createElement("button");
  toggle.textContent = task.completed ? "Reopen" : "Complete";
  toggle.onclick = async () => {
    await requestJson(`/api/tasks/${task.id}`, {
      method: "PATCH",
      body: JSON.stringify({ completed: !task.completed }),
    });
    await refresh();
  };
  const remove = document.createElement("button");
  remove.textContent = "Delete";
  remove.onclick = async () => {
    await requestJson(`/api/tasks/${task.id}`, { method: "DELETE" });
    await refresh();
  };
  li.append(title, status, toggle, remove);
  taskList.appendChild(li);
}

function applyFilter(task) {
  const selected = statusFilter.value;
  if (selected === "completed") return task.completed;
  if (selected === "active") return !task.completed;
  return true;
}

function formatReport(report) {
  reportPanel.textContent = JSON.stringify(
    {
      total: report.total,
      completed: report.completed,
      completionRate: `${(report.completion_rate * 100).toFixed(1)}%`,
      byPriority: report.by_priority,
    },
    null,
    2,
  );
}

async function refresh() {
  const [tasks, report] = await Promise.all([
    requestJson("/api/tasks"),
    requestJson("/api/report"),
  ]);
  taskList.innerHTML = "";
  const visible = tasks.filter(applyFilter);
  if (visible.length === 0) {
    emptyState.textContent = "No tasks to show.";
    return;
  }
  emptyState.textContent = "";
  visible.forEach(renderTask);
  formatReport(report);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const title = document.getElementById("title").value.trim();
  const priority = document.getElementById("priority").value;
  if (!title) return;
  await requestJson("/api/tasks", {
    method: "POST",
    body: JSON.stringify({ title, priority }),
  });
  form.reset();
  await refresh();
});

statusFilter.addEventListener("change", refresh);
refreshBtn.addEventListener("click", refresh);

refresh().catch((error) => {
  emptyState.textContent = `Failed to load tasks: ${error.message}`;
  reportPanel.textContent = "";
});

