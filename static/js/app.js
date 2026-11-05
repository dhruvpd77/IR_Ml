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
  const cameraLabel = box.querySelector("[data-video-camera-label]");
  const camera = box.querySelector("[data-video-camera]");
  const gallery = box.querySelector("[data-video-gallery]");
  const record = box.querySelector("[data-video-record]");
  const stop = box.querySelector("[data-video-stop]");
  const liveCamera = window.isSecureContext && navigator.mediaDevices && window.MediaRecorder;
  if (liveCamera) {
    cameraLabel.hidden = true;
    record.hidden = false;
  }
  let recorder = null;
  let stream = null;
  let timer = null;
  let previewUrl = "";

  function say(text) {
    if (status) status.textContent = text;
  }

  function showFile(file) {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(file);
    preview.hidden = false;
    preview.src = previewUrl;
    preview.controls = true;
    const mb = (file.size / (1024 * 1024)).toFixed(1);
    say(`Ready · ${mb} MB. It is reduced again when you save.`);
  }

  function store(file) {
    const data = new DataTransfer();
    data.items.add(file);
    result.files = data.files;
    showFile(file);
  }

  async function shrink(file) {
    if (!window.isSecureContext || !window.MediaRecorder) {
      store(file);
      say("Selected. The first 30 seconds are kept and the file is reduced when you save.");
      return;
    }
    say("Reducing the video…");
    try {
      const smaller = await squeezeVideo(file);
      store(smaller);
    } catch (error) {
      store(file);
    }
  }

  gallery.addEventListener("change", () => {
    if (gallery.files[0]) shrink(gallery.files[0]);
  });
  camera.addEventListener("change", () => {
    if (camera.files[0]) shrink(camera.files[0]);
  });

  function finishRecording() {
    if (timer) clearTimeout(timer);
    timer = null;
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
    recorder = null;
    preview.srcObject = null;
    record.hidden = false;
    stop.hidden = true;
    preview.controls = true;
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
      preview.hidden = false;
      preview.controls = false;
      preview.srcObject = stream;
      await preview.play();
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
        store(new File(chunks, `inspection.${extension}`, { type: type.split(";")[0] }));
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

function squeezeVideo(file) {
  return new Promise((resolve, reject) => {
    const video = document.createElement("video");
    video.playsInline = true;
    video.muted = true;
    video.src = URL.createObjectURL(file);
    video.onerror = () => reject(new Error("unreadable"));
    video.onloadedmetadata = async () => {
      const duration = Math.min(video.duration || 20, 30);
      const scale = Math.min(1, 854 / (video.videoWidth || 854));
      const width = Math.max(2, Math.round(((video.videoWidth || 854) * scale) / 2) * 2);
      const height = Math.max(2, Math.round(((video.videoHeight || 480) * scale) / 2) * 2);
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d");
      if (!canvas.captureStream) {
        reject(new Error("no capture"));
        return;
      }
      const output = canvas.captureStream(15);
      const mime = ["video/webm;codecs=vp8", "video/webm", "video/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(output, { mimeType: mime || undefined, videoBitsPerSecond: 600000 });
      const chunks = [];
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size) chunks.push(event.data);
      };
      recorder.onstop = () => {
        URL.revokeObjectURL(video.src);
        const type = (recorder.mimeType || mime || "video/webm").split(";")[0];
        resolve(new File(chunks, type.includes("mp4") ? "inspection.mp4" : "inspection.webm", { type }));
      };
      recorder.start(250);
      await video.play();
      const draw = () => {
        if (video.ended || video.currentTime >= duration) return;
        context.drawImage(video, 0, 0, width, height);
        requestAnimationFrame(draw);
      };
      draw();
      setTimeout(() => {
        video.pause();
        if (recorder.state === "recording") recorder.stop();
      }, duration * 1000 + 150);
    };
  });
}
