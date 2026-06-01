const messages = document.querySelector("#messages");
const form = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const button = document.querySelector("#sendButton");
const modeBadge = document.querySelector("#modeBadge");
const inventory = document.querySelector("#inventory");
const pendingBooking = document.querySelector("#pendingBooking");

const formatMoney = (value) => new Intl.NumberFormat("vi-VN").format(value) + " VND";

function addMessage(role, content) {
  const bubble = document.createElement("div");
  bubble.className = `message ${role}`;
  bubble.textContent = content;
  messages.appendChild(bubble);
  messages.scrollTop = messages.scrollHeight;
}

function setLoading(isLoading) {
  button.disabled = isLoading;
  button.textContent = isLoading ? "Dang gui" : "Gui";
}

function renderState(state) {
  modeBadge.textContent = state.mode === "local-model" ? "Local model" : "Rule-based";
  renderPending(state.pending_booking);
  renderInventory(state.inventory || []);
}

function renderPending(booking) {
  if (!booking) {
    pendingBooking.className = "muted";
    pendingBooking.textContent = "Chua co booking tam.";
    return;
  }

  const pkg = booking.package;
  pendingBooking.className = "";
  pendingBooking.textContent =
    `${booking.booking_id}\n${booking.guest_name}\n${pkg.room_name} - ${pkg.resort}\n` +
    `${pkg.check_in} den ${pkg.check_out}\nTong gia: ${formatMoney(pkg.total_price)}\n` +
    "Cho cau xac nhan dat tu nguoi dung.";
}

function renderInventory(rows) {
  inventory.innerHTML = "";
  rows.forEach((room) => {
    const card = document.createElement("article");
    card.className = "room-card";

    const head = document.createElement("div");
    head.className = "room-head";
    head.innerHTML = `
      <div>
        <div class="room-code">${room.code}</div>
        <div class="room-name">${room.room_name}</div>
        <div class="muted">${room.resort}</div>
      </div>
      <div class="price">${formatMoney(room.weekend_price)}<br><span class="muted">cuoi tuan</span></div>
    `;

    const includes = document.createElement("div");
    includes.className = "includes";
    includes.textContent = room.includes.join(" + ");

    const dateGrid = document.createElement("div");
    dateGrid.className = "date-grid";
    Object.entries(room.status_by_date).forEach(([date, status]) => {
      const row = document.createElement("div");
      row.className = "date-row";
      row.innerHTML = `
        <span>${date}</span>
        <span>${status.available} phong</span>
        <span class="status-pill ${status.status}">${status.status}</span>
      `;
      dateGrid.appendChild(row);
    });

    card.append(head, includes, dateGrid);
    inventory.appendChild(card);
  });
}

async function loadState() {
  const response = await fetch("/api/inventory");
  renderState(await response.json());
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message) return;

  addMessage("user", message);
  input.value = "";
  setLoading(true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Khong gui duoc tin nhan.");
    addMessage("assistant", payload.answer);
    renderState(payload);
  } catch (error) {
    addMessage("assistant", `Co loi: ${error.message}`);
  } finally {
    setLoading(false);
    input.focus();
  }
});

addMessage(
  "assistant",
  "Xin chao, toi co the tim phong Vinpearl Nha Trang theo ngay, so khach, gia va tien ich. Toi se chi xac nhan dat khi ban noi ro xac nhan dat."
);
loadState();
