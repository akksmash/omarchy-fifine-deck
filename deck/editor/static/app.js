"use strict";

const TOKEN = document.querySelector('meta[name="deck-token"]').content;

const api = async (path, body) => {
  const opts = { headers: { "X-Deck-Token": TOKEN } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
};

const $ = (id) => document.getElementById(id);
const FIELDS = ["label", "caption", "cmd", "color", "icon", "art"];

let state = null;      // last /api/state
let selected = null;   // key index being edited
let dirty = false;

// ---------------------------------------------------------------- toast

let toastTimer = null;
function toast(msg, kind = "") {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast " + kind;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 2600);
}

// ---------------------------------------------------------------- grid

// Cache-bust per key, so a tile refreshes only when that key changed.
const tileVersion = new Map();
const tileUrl = (k) =>
  `/api/tile?key=${k}&token=${encodeURIComponent(TOKEN)}&v=${tileVersion.get(k) || 0}`;

function refreshTile(k) {
  tileVersion.set(k, Date.now());
  const img = document.querySelector(`.key[data-key="${k}"] img`);
  if (img) img.src = tileUrl(k);
}

function buildGrid() {
  const grid = $("grid");
  grid.style.setProperty("--cols", state.profile.cols);
  grid.innerHTML = "";

  for (let k = 1; k <= state.profile.keys; k++) {
    const spec = state.keys[String(k)] || {};
    const cell = document.createElement("button");
    cell.className = "key" + (Object.keys(spec).length ? "" : " blank");
    cell.dataset.key = k;
    cell.draggable = true;
    cell.title = spec.label || `Key ${k} (unbound)`;

    const img = document.createElement("img");
    img.src = tileUrl(k);
    img.alt = spec.label || `key ${k}`;
    img.draggable = false;
    cell.appendChild(img);

    const idx = document.createElement("span");
    idx.className = "idx";
    idx.textContent = k;
    cell.appendChild(idx);

    cell.addEventListener("click", () => select(k));
    wireDrag(cell);
    grid.appendChild(cell);
  }
}

// ------------------------------------------------------------ drag/drop

let dragFrom = null;

function wireDrag(cell) {
  cell.addEventListener("dragstart", (e) => {
    dragFrom = Number(cell.dataset.key);
    cell.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    // Firefox will not start a drag without payload.
    e.dataTransfer.setData("text/plain", String(dragFrom));
  });

  cell.addEventListener("dragend", () => {
    cell.classList.remove("dragging");
    document.querySelectorAll(".dropzone").forEach((c) => c.classList.remove("dropzone"));
    dragFrom = null;
  });

  cell.addEventListener("dragover", (e) => {
    if (dragFrom === null || Number(cell.dataset.key) === dragFrom) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    cell.classList.add("dropzone");
  });

  cell.addEventListener("dragleave", () => cell.classList.remove("dropzone"));

  cell.addEventListener("drop", async (e) => {
    e.preventDefault();
    cell.classList.remove("dropzone");
    const to = Number(cell.dataset.key);
    const from = dragFrom !== null ? dragFrom : Number(e.dataTransfer.getData("text/plain"));
    if (!from || from === to) return;
    try {
      await api("/api/swap", { a: from, b: to });
      await reload({ keepSelection: to });
      refreshTile(from); refreshTile(to);
      markDirty();
      toast(`Swapped key ${from} and ${to}`);
    } catch (err) { toast(String(err), "bad"); }
  });
}

// ------------------------------------------------------------- editing

function select(k) {
  selected = k;
  document.querySelectorAll(".key").forEach((c) =>
    c.classList.toggle("selected", Number(c.dataset.key) === k));

  const spec = state.keys[String(k)] || {};
  $("empty").hidden = true;
  $("form").hidden = false;
  $("f-index").textContent = k;
  for (const f of FIELDS) $("f-" + f).value = spec[f] || "";
  syncColorPicker();
  $("test-out").hidden = true;
}

function currentSpec() {
  const spec = {};
  for (const f of FIELDS) spec[f] = $("f-" + f).value;
  return spec;
}

function markDirty() {
  dirty = true;
  $("btn-save").disabled = false;
}

let pushTimer = null;
function pushKey() {
  if (selected === null) return;
  clearTimeout(pushTimer);
  pushTimer = setTimeout(async () => {
    const spec = currentSpec();
    try {
      await api("/api/key", { key: selected, spec });
      state.keys[String(selected)] = spec;
      refreshTile(selected);
      const cell = document.querySelector(`.key[data-key="${selected}"]`);
      if (cell) {
        cell.title = spec.label || `Key ${selected} (unbound)`;
        cell.classList.toggle("blank", !FIELDS.some((f) => spec[f].trim()));
      }
      markDirty();
    } catch (err) { toast(String(err), "bad"); }
  }, 350);
}

function syncColorPicker() {
  const v = $("f-color").value.trim();
  if (/^#[0-9a-f]{6}$/i.test(v)) $("f-color-picker").value = v;
}

// --------------------------------------------------------------- state

function paintStatus(st) {
  $("device").textContent = st.device || state.profile.name;
  $("dot").className = "dot " + (st.present ? "on" : "off");

  const bits = [];
  bits.push(st.present ? "connected" : "not connected");
  bits.push(st.daemon ? "daemon running" : "daemon stopped");
  if (!st.magick) bits.push("ImageMagick missing");
  $("substatus").textContent = bits.join(" · ");
}

// Cheap poll: the header only. Rebuilding the grid on a timer would flicker
// and re-render every tile for nothing.
async function refreshStatus() {
  const s = await api("/api/state");
  state.status = s.status;
  paintStatus(s.status);
}

async function reload({ keepSelection = null } = {}) {
  state = await api("/api/state");
  paintStatus(state.status);

  if (state.dirty) markDirty();
  $("set-brightness").value = state.settings.brightness;
  $("out-brightness").textContent = state.settings.brightness + "%";
  $("set-draw").checked = state.settings.draw_on_attach;

  buildGrid();
  const want = keepSelection !== null ? keepSelection : selected;
  if (want !== null && want <= state.profile.keys) select(want);
}

// --------------------------------------------------------------- wiring

for (const f of FIELDS) $("f-" + f).addEventListener("input", () => {
  if (f === "color") syncColorPicker();
  pushKey();
});

$("f-color-picker").addEventListener("input", (e) => {
  $("f-color").value = e.target.value;
  pushKey();
});

$("btn-save").addEventListener("click", async () => {
  try {
    const r = await api("/api/save", {});
    dirty = false;
    $("btn-save").disabled = true;
    toast(r.redraw ? "Saved — deck redrawing" : "Saved", "good");
  } catch (err) { toast(String(err), "bad"); }
});

$("btn-revert").addEventListener("click", async () => {
  if (dirty && !confirm("Discard unsaved changes?")) return;
  await api("/api/revert", {});
  dirty = false;
  $("btn-save").disabled = true;
  tileVersion.clear();
  await reload();
  toast("Reverted to the saved config");
});

$("btn-redraw").addEventListener("click", async () => {
  try {
    const r = await api("/api/redraw", {});
    toast(r.ok ? "Redraw requested" : "Could not request a redraw",
          r.ok ? "good" : "bad");
  } catch (err) { toast(String(err), "bad"); }
});

$("btn-test").addEventListener("click", async () => {
  const out = $("test-out");
  out.hidden = false;
  out.className = "";
  out.textContent = "running…";
  try {
    const r = await api("/api/test", { cmd: $("f-cmd").value });
    out.textContent = r.output;
    out.className = r.ok ? "" : "bad";
  } catch (err) {
    out.textContent = String(err);
    out.className = "bad";
  }
});

$("btn-clear").addEventListener("click", () => {
  if (selected === null) return;
  if (!confirm(`Clear key ${selected}?`)) return;
  for (const f of FIELDS) $("f-" + f).value = "";
  pushKey();
});

$("set-brightness").addEventListener("input", (e) => {
  $("out-brightness").textContent = e.target.value + "%";
});
$("set-brightness").addEventListener("change", async (e) => {
  await api("/api/settings", { settings: { brightness: Number(e.target.value) } });
  markDirty();
});
$("set-draw").addEventListener("change", async (e) => {
  await api("/api/settings", { settings: { draw_on_attach: e.target.checked } });
  markDirty();
});

window.addEventListener("beforeunload", (e) => {
  if (dirty) { e.preventDefault(); e.returnValue = ""; }
});

// Keep the connection/daemon indicator honest while the window is open.
setInterval(() => { refreshStatus().catch(() => {}); }, 8000);

reload().catch((err) => toast("Could not load: " + err, "bad"));
