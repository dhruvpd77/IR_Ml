function catalogUrl() {
  const form = document.querySelector("[data-catalog-url]");
  return form ? form.dataset.catalogUrl : "";
}

function applyCcn(select) {
  const scope = select.closest(".form-grid") || select.closest("form");
  const ccn = scope && scope.querySelector("[data-ccn]");
  const option = select.selectedOptions[0];
  if (!ccn) return;
  if (option && option.dataset.ccn) ccn.value = option.dataset.ccn;
  else if (!select.value) ccn.value = "";
}

async function refreshModels(select) {
  const url = catalogUrl();
  if (!url || !select) return;
  const scope = select.closest(".form-grid") || select.closest("form");
  const company = scope.querySelector('[name$="company"]');
  const type = scope.querySelector('[name$="machine_type"]');
  const ccn = scope.querySelector("[data-ccn]");
  if (!company || !type) return;
  const current = select.value || select.dataset.current || "";
  if (!company.value || !type.value) {
    select.replaceChildren(new Option("Select company and type first", ""));
    if (ccn && !current) ccn.value = "";
    return;
  }
  try {
    const response = await fetch(
      `${url}?company=${encodeURIComponent(company.value)}&type=${encodeURIComponent(type.value)}`,
      { headers: { "X-Requested-With": "fetch" } }
    );
    if (!response.ok) throw new Error("lookup failed");
    const data = await response.json();
    select.replaceChildren();
    select.add(new Option(data.items.length ? "Select" : "No models for this company and type", ""));
    data.items.forEach((item) => {
      const option = new Option(item.ccn ? `${item.model}  ·  ${item.ccn}` : item.model, item.model);
      option.value = item.model;
      option.dataset.ccn = item.ccn;
      select.add(option);
    });
    if (current && ![...select.options].some((option) => option.value === current)) {
      const extra = new Option(current, current);
      if (ccn && ccn.value) extra.dataset.ccn = ccn.value;
      select.add(extra);
    }
    if (current) select.value = current;
    applyCcn(select);
  } catch (error) {
    select.replaceChildren(new Option("Could not load models", ""));
  }
}

function syncTestResult() {
  const problem = document.querySelector("[data-not-ok]");
  if (!problem) return;
  const chosen = document.querySelector('[name="f_test_result"]:checked');
  problem.hidden = !chosen || chosen.value !== "NOT OK";
}

function syncInspectionDates(root) {
  (root || document).querySelectorAll("[data-inspection]").forEach((select) => {
    const scope = select.closest(".form-grid") || select.closest("form") || document;
    const dateField = scope.querySelector("[data-inspection-date]");
    if (!dateField) return;
    dateField.hidden = select.value !== "Yes";
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const shell = document.getElementById("shell");
  const menu = document.getElementById("menuBtn");
  const backdrop = document.querySelector(".sidebar-backdrop");
  const closeMenu = () => shell && shell.classList.remove("sidebar-open");
  if (menu && shell) {
    menu.addEventListener("click", () => shell.classList.toggle("sidebar-open"));
  }
  if (backdrop) backdrop.addEventListener("click", closeMenu);
  document.querySelectorAll(".nav-link").forEach((link) => link.addEventListener("click", closeMenu));
  document.querySelectorAll("[data-select-all]").forEach((box) => {
    box.addEventListener("change", () => {
      document.querySelectorAll(box.dataset.selectAll).forEach((item) => {
        item.checked = box.checked;
      });
    });
  });
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
  const addButton = document.querySelector("[data-add-row]");
  if (addButton) {
    addButton.addEventListener("click", () => {
      const formset = document.querySelector(addButton.dataset.addRow);
      const total = formset.querySelector('input[name$="-TOTAL_FORMS"]');
      const rows = formset.querySelectorAll("[data-row]");
      const index = Number(total.value);
      const clone = rows[rows.length - 1].cloneNode(true);
      clone.querySelectorAll("input, select, textarea").forEach((field) => {
        if (field.name) field.name = field.name.replace(/-\d+-/, `-${index}-`);
        if (field.id) field.id = field.id.replace(/-\d+-/, `-${index}-`);
        if (field.matches("[data-model]")) {
          field.replaceChildren(new Option("Select company and type first", ""));
          delete field.dataset.current;
        } else if (field.tagName === "SELECT") {
          field.selectedIndex = 0;
        } else if (field.type !== "hidden") {
          field.value = "";
        }
      });
      clone.querySelectorAll(".field-error").forEach((node) => node.remove());
      formset.querySelector("[data-rows]").appendChild(clone);
      total.value = String(index + 1);
      syncInspectionDates(clone);
    });
  }
  syncInspectionDates(document);
  syncTestResult();
  document.addEventListener("change", (event) => {
    if (event.target.matches("[data-test-result]")) syncTestResult();
  });
  document.querySelectorAll("[data-model]").forEach((select) => refreshModels(select));
  document.addEventListener("change", (event) => {
    if (event.target.matches("[data-inspection]")) syncInspectionDates(event.target.closest(".form-grid") || document);
    if (event.target.matches('[name$="company"], [name$="machine_type"]')) {
      const scope = event.target.closest(".form-grid") || event.target.closest("form");
      const model = scope && scope.querySelector("[data-model]");
      if (model) {
        model.value = "";
        delete model.dataset.current;
        const ccn = scope.querySelector("[data-ccn]");
        if (ccn) ccn.value = "";
        refreshModels(model);
      }
    }
    if (event.target.matches("[data-model]")) applyCcn(event.target);
  });
  document.querySelectorAll(".data-table").forEach((table) => {
    const headers = [...table.querySelectorAll("thead th")].map((cell) => cell.textContent.trim());
    table.querySelectorAll("tbody tr").forEach((row) => {
      [...row.children].forEach((cell, index) => {
        if (headers[index]) cell.dataset.label = headers[index];
      });
    });
  });
  const badge = document.getElementById("unreadBadge");
  if (badge) {
    const refresh = () => {
      fetch("/notifications/unread-count/", { headers: { "X-Requested-With": "fetch" } })
        .then((response) => response.json())
        .then((data) => {
          badge.hidden = !data.unread;
          badge.textContent = data.unread;
        })
        .catch(() => {});
    };
    const timer = setInterval(refresh, 60000);
    window.addEventListener("pagehide", () => clearInterval(timer));
  }
  document.querySelectorAll("[data-fullscreen]").forEach((button) => {
    const target = document.getElementById(button.dataset.fullscreen);
    if (!target || !target.requestFullscreen) return;
    const sync = () => button.setAttribute("aria-pressed", document.fullscreenElement === target ? "true" : "false");
    button.addEventListener("click", () => {
      if (document.fullscreenElement === target) document.exitFullscreen();
      else target.requestFullscreen().catch(() => {});
    });
    document.addEventListener("fullscreenchange", sync);
  });
  if (window.lucide) window.lucide.createIcons();
  document.querySelectorAll("[data-video-box]").forEach(bindVideoBox);
});

function bindVideoBox(box) {
  const preview = box.querySelector("[data-video-preview]");
  const status = box.querySelector("[data-video-status]");
  const result = box.querySelector("[data-video-result]");
  const list = box.querySelector("[data-video-list]");
  const cameraLabel = box.querySelector("[data-video-camera-label]");
  const camera = box.querySelector("[data-video-camera]");
  const gallery = box.querySelector("[data-video-gallery]");
  const record = box.querySelector("[data-video-record]");
  const stop = box.querySelector("[data-video-stop]");
  const maxBytes = 200 * 1024 * 1024;
  const maxClips = 8;
  const liveCamera = window.isSecureContext && navigator.mediaDevices && window.MediaRecorder;
  const selected = [];
  if (liveCamera) {
    cameraLabel.hidden = true;
    record.hidden = false;
  }
  let recorder = null;
  let stream = null;
  let timer = null;

  function say(text) {
    if (status) status.textContent = text;
  }

  function sync() {
    list.replaceChildren();
    selected.forEach((file, index) => {
      const item = document.createElement("li");
      const name = document.createElement("span");
      const mb = (file.size / (1024 * 1024)).toFixed(1);
      name.textContent = `${file.name} · ${mb} MB`;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn-ghost";
      button.textContent = "Remove";
      button.addEventListener("click", () => {
        selected.splice(index, 1);
        sync();
      });
      item.append(name, button);
      list.append(item);
    });
    const data = new DataTransfer();
    selected.forEach((file) => data.items.add(file));
    result.files = data.files;
    if (!selected.length) {
      say("Add one or more inspection videos. Each file can be up to 200 MB. The picture and sound are reduced when you save.");
    } else {
      say(`${selected.length} video${selected.length === 1 ? "" : "s"} ready. Quality is reduced when you save.`);
    }
  }

  function addFile(file) {
    if (!file || !file.size) return;
    if (file.size > maxBytes) {
      say(`${file.name} is over 200 MB. Each video must be 200 MB or smaller.`);
      return;
    }
    if (selected.length >= maxClips) {
      say(`You can add up to ${maxClips} videos at a time.`);
      return;
    }
    selected.push(file);
    sync();
  }

  gallery.addEventListener("change", () => {
    Array.from(gallery.files || []).forEach(addFile);
    gallery.value = "";
  });
  camera.addEventListener("change", () => {
    if (camera.files[0]) addFile(camera.files[0]);
    camera.value = "";
  });

  function finishRecording() {
    if (timer) clearTimeout(timer);
    timer = null;
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
    recorder = null;
    if (preview) {
      preview.srcObject = null;
      preview.hidden = true;
    }
    record.hidden = false;
    stop.hidden = true;
  }

  record.addEventListener("click", async () => {
    const live = window.isSecureContext && navigator.mediaDevices && window.MediaRecorder;
    if (!live) {
      camera.click();
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: { ideal: 854 }, height: { ideal: 480 } },
        audio: true,
      });
      if (preview) {
        preview.hidden = false;
        preview.controls = false;
        preview.srcObject = stream;
        await preview.play();
      }
      const mime = ["video/webm;codecs=vp8,opus", "video/webm", "video/mp4"].find(
        (type) => MediaRecorder.isTypeSupported(type)
      );
      recorder = new MediaRecorder(stream, {
        mimeType: mime || undefined,
        videoBitsPerSecond: 700000,
        audioBitsPerSecond: 64000,
      });
      const chunks = [];
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size) chunks.push(event.data);
      };
      recorder.onstop = () => {
        const type = recorder && recorder.mimeType ? recorder.mimeType : mime || "video/webm";
        const extension = type.includes("mp4") ? "mp4" : "webm";
        finishRecording();
        addFile(new File(chunks, `inspection.${extension}`, { type: type.split(";")[0] }));
      };
      recorder.start(250);
      record.hidden = true;
      stop.hidden = false;
      say("Recording… it stops at 20 seconds.");
      timer = setTimeout(() => {
        if (recorder && recorder.state === "recording") recorder.stop();
      }, 20000);
    } catch (error) {
      finishRecording();
      camera.click();
    }
  });
  stop.addEventListener("click", () => {
    if (recorder && recorder.state === "recording") recorder.stop();
  });
}
