function catalogUrl() {
  const form = document.querySelector("[data-catalog-url]");
  return form ? form.dataset.catalogUrl : "";
}

function ccnField(scope) {
  return scope && scope.querySelector("input[data-ccn]");
}

function optionCcn(option) {
  if (!option) return "";
  const stored = option.getAttribute("data-ccn");
  if (stored) return stored;
  const text = option.text || "";
  const mark = text.lastIndexOf("·");
  return mark === -1 ? "" : text.slice(mark + 1).trim();
}

function applyCcn(select) {
  const scope = select.closest(".form-grid") || select.closest("form");
  const ccn = ccnField(scope);
  const option = select.selectedOptions && select.selectedOptions[0];
  if (!ccn) return;
  if (!select.value) {
    ccn.value = "";
    return;
  }
  ccn.value = optionCcn(option);
}

function paintModels(select, items, query, selected) {
  const needle = (query || "").trim().toLowerCase();
  const matches = (items || []).filter((item) => {
    if (!needle) return true;
    return item.model.toLowerCase().includes(needle) || String(item.ccn || "").toLowerCase().includes(needle);
  });
  if (selected && !matches.some((item) => item.model === selected)) {
    const current = (items || []).find((item) => item.model === selected);
    if (current) matches.unshift(current);
  }
  select.replaceChildren();
  select.add(new Option(matches.length ? "Select" : "No matching model", ""));
  matches.forEach((item) => {
    const option = new Option(item.ccn ? `${item.model}  ·  ${item.ccn}` : item.model, item.model);
    option.setAttribute("data-ccn", item.ccn || "");
    select.add(option);
  });
  if (selected && ![...select.options].some((option) => option.value === selected)) {
    const extra = new Option(selected, selected);
    const scope = select.closest(".form-grid") || select.closest("form");
    const ccn = ccnField(scope);
    extra.setAttribute("data-ccn", (ccn && ccn.value) || "");
    select.add(extra);
  }
  if (selected) select.value = selected;
  applyCcn(select);
}

async function refreshModels(select) {
  const url = catalogUrl();
  if (!url || !select) return;
  const scope = select.closest(".form-grid") || select.closest("form");
  const company = scope.querySelector('[name$="company"]');
  const type = scope.querySelector('[name$="machine_type"]');
  const ccn = ccnField(scope);
  const search = scope.querySelector("[data-model-search]");
  if (!company || !type) return;
  const current = select.value || select.dataset.current || "";
  if (!company.value || !type.value) {
    select._models = [];
    select.replaceChildren(new Option("Select brand and type first", ""));
    if (ccn && !current) ccn.value = "";
    if (search) search.value = "";
    return;
  }
  try {
    const response = await fetch(
      `${url}?company=${encodeURIComponent(company.value)}&type=${encodeURIComponent(type.value)}`,
      { headers: { "X-Requested-With": "fetch" } }
    );
    if (!response.ok) throw new Error("lookup failed");
    const data = await response.json();
    select._models = data.items || [];
    if (search) search.value = "";
    paintModels(select, select._models, "", current);
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

function syncTestReports(root) {
  (root || document).querySelectorAll("[data-test-report]").forEach((select) => {
    const scope = select.closest(".form-grid") || select.closest("form") || document;
    const extra = scope.querySelector("[data-test-report-other]");
    if (!extra) return;
    extra.hidden = select.value !== "Other";
  });
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
          field.replaceChildren(new Option("Select brand and type first", ""));
          field._models = [];
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
      syncTestReports(clone);
    });
  }
  document.querySelectorAll("form[data-require-all]").forEach((form) => {
    const boxFor = (field) => field.closest(".check-row, .elec-row > div, .field") || field.parentElement;
    const mark = (box) => {
      if (!box || box.closest("[hidden]")) return false;
      box.classList.add("is-missing");
      if (!box.querySelector(".field-error")) {
        const note = document.createElement("p");
        note.className = "field-error";
        note.dataset.clientError = "1";
        note.textContent = "This field is missing.";
        box.appendChild(note);
      }
      return true;
    };
    form.addEventListener("submit", (event) => {
      const submitter = event.submitter;
      if (!submitter || !["submit", "approve", "update"].includes(submitter.value)) return;
      form.querySelectorAll("[data-client-error]").forEach((node) => node.remove());
      form.querySelectorAll(".is-missing").forEach((node) => node.classList.remove("is-missing"));
      const seen = new Set();
      let first = null;
      const flag = (box) => {
        if (!box || seen.has(box)) return;
        seen.add(box);
        if (mark(box) && !first) first = box;
      };
      form.querySelectorAll("textarea, select, input").forEach((field) => {
        if (field.disabled || field.closest("[hidden]")) return;
        if (field.type === "hidden" || field.type === "file" || field.type === "button" || field.type === "submit") return;
        const box = boxFor(field);
        if (field.type === "radio") {
          const chosen = form.querySelector(`input[type="radio"][name="${CSS.escape(field.name)}"]:checked`);
          if (!chosen) flag(box);
          return;
        }
        if (field.type === "checkbox") {
          if (!field.checked) flag(box);
          return;
        }
        if (!String(field.value || "").trim()) flag(box);
      });
      form.querySelectorAll("[data-video-box]").forEach((box) => {
        if (!box.querySelector("[data-video-clip]")) flag(box.closest(".check-row, .field") || box);
      });
      form.querySelectorAll("[data-photo-box]").forEach((box) => {
        if (!box.querySelector("[data-photo-clip]")) flag(box.closest(".field") || box);
      });
      if (!first) return;
      event.preventDefault();
      first.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });
  syncInspectionDates(document);
  syncTestReports(document);
  syncTestResult();
  document.addEventListener("change", (event) => {
    if (event.target.matches("[data-test-result]")) syncTestResult();
  });
  document.querySelectorAll("[data-model]").forEach((select) => refreshModels(select));
  document.addEventListener("change", (event) => {
    if (event.target.matches("[data-inspection]")) syncInspectionDates(event.target.closest(".form-grid") || document);
    if (event.target.matches("[data-test-report]")) syncTestReports(event.target.closest(".form-grid") || document);
    if (event.target.matches('[name$="company"], [name$="machine_type"]')) {
      const scope = event.target.closest(".form-grid") || event.target.closest("form");
      const model = scope && scope.querySelector("[data-model]");
      if (model) {
        model.value = "";
        delete model.dataset.current;
        const ccn = ccnField(scope);
        if (ccn) ccn.value = "";
        refreshModels(model);
      }
    }
    if (event.target.matches("[data-model]")) applyCcn(event.target);
  });
  document.addEventListener("input", (event) => {
    if (!event.target.matches("[data-model-search]")) return;
    const scope = event.target.closest(".form-grid") || event.target.closest("form");
    const model = scope && scope.querySelector("[data-model]");
    if (model) paintModels(model, model._models || [], event.target.value, model.value);
  });
  document.addEventListener("keydown", (event) => {
    if (event.target.matches("[data-model-search]") && event.key === "Enter") event.preventDefault();
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
    if (!target) return;
    const active = () => document.fullscreenElement || document.webkitFullscreenElement;
    const sync = () => {
      const on = active() === target;
      target.classList.toggle("is-fullscreen", on);
      button.setAttribute("aria-pressed", on ? "true" : "false");
    };
    button.addEventListener("click", () => {
      if (active() === target) {
        const exit = document.exitFullscreen || document.webkitExitFullscreen;
        if (exit) exit.call(document);
        return;
      }
      const enter = target.requestFullscreen || target.webkitRequestFullscreen;
      if (enter) enter.call(target).catch(() => {});
    });
    document.addEventListener("fullscreenchange", sync);
    document.addEventListener("webkitfullscreenchange", sync);
  });
  if (window.lucide) window.lucide.createIcons();
  document.querySelectorAll("[data-video-box]").forEach((box) => {
    if (box.dataset.uploadUrl) bindQcVideoBox(box);
    else bindVideoBox(box);
  });
  document.querySelectorAll("[data-photo-box]").forEach((box) => bindPhotoBox(box));
  const paintClock = () => {
    const now = new Date();
    const text = now.toLocaleString("en-IN", {
      weekday: "short",
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    document.querySelectorAll("[data-clock]").forEach((node) => {
      node.textContent = text;
    });
  };
  paintClock();
  setInterval(paintClock, 1000);
});

function bindPhotoBox(box) {
  const status = box.querySelector("[data-photo-status]");
  const list = box.querySelector("[data-photo-list]");
  const saved = box.querySelector("[data-photo-saved]");
  const busy = box.querySelector("[data-photo-busy]");
  const busyText = box.querySelector("[data-photo-busy-text]");
  const upload = box.querySelector("[data-photo-upload]");
  const camera = box.querySelector("[data-photo-camera]");
  const gallery = box.querySelector("[data-photo-gallery]");
  const maxBytes = 20 * 1024 * 1024;
  const maxPhotos = 8;
  const selected = [];
  const token = document.querySelector("[name=csrfmiddlewaretoken]");
  let working = false;

  function say(text) {
    if (status) status.textContent = text;
  }

  function setBusy(on, text) {
    working = on;
    box.classList.toggle("is-busy", on);
    if (busy) busy.hidden = !on;
    if (busyText && text) busyText.textContent = text;
    if (upload) upload.disabled = on || !selected.length;
  }

  function sync() {
    list.replaceChildren();
    selected.forEach((file, index) => {
      const item = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MB`;
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
    if (upload) upload.disabled = working || !selected.length;
    if (!selected.length) {
      say("Take or choose inspection photos, then press Upload photo. Photos are reduced in size.");
    } else {
      say(`${selected.length} photo${selected.length === 1 ? "" : "s"} waiting. Press Upload photo.`);
    }
  }

  function addSaved(photo) {
    const clip = document.createElement("div");
    clip.className = "video-clip";
    clip.dataset.photoClip = String(photo.id);
    const image = document.createElement("img");
    image.className = "clip";
    image.alt = "";
    image.src = photo.url;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn-ghost";
    button.textContent = `Remove ${photo.name}`;
    button.addEventListener("click", () => removeSaved(photo.id, clip));
    clip.append(image, button);
    saved.append(clip);
  }

  function addFile(file) {
    if (!file || !file.size || working) return;
    if (!file.type.startsWith("image/")) {
      say("Choose a photo.");
      return;
    }
    if (file.size > maxBytes) {
      say(`${file.name} is over 20 MB. Each photo must be 20 MB or smaller.`);
      return;
    }
    const already = saved.querySelectorAll("[data-photo-clip]").length;
    if (already + selected.length >= maxPhotos) {
      say(`You can keep up to ${maxPhotos} photos.`);
      return;
    }
    selected.push(file);
    sync();
  }

  async function send(file) {
    const body = new FormData();
    body.append("photo", file);
    const response = await fetch(box.dataset.uploadUrl, {
      method: "POST",
      body,
      headers: { "X-CSRFToken": token ? token.value : "" },
      credentials: "same-origin",
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "The photo could not be uploaded.");
    return data;
  }

  async function removeSaved(id, clip) {
    if (working) return;
    setBusy(true, "Removing photo…");
    try {
      const response = await fetch(`${box.dataset.removeBase}${id}/remove/`, {
        method: "POST",
        headers: { "X-CSRFToken": token ? token.value : "" },
        credentials: "same-origin",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "The photo could not be removed.");
      clip.remove();
      say("Photo removed.");
    } catch (error) {
      say(error.message);
    } finally {
      setBusy(false);
    }
  }

  saved.querySelectorAll("[data-photo-remove]").forEach((button) => {
    button.addEventListener("click", () => {
      const clip = button.closest("[data-photo-clip]");
      removeSaved(button.dataset.photoRemove, clip);
    });
  });
  gallery.addEventListener("change", () => {
    Array.from(gallery.files || []).forEach(addFile);
    gallery.value = "";
  });
  camera.addEventListener("change", () => {
    if (camera.files[0]) addFile(camera.files[0]);
    camera.value = "";
  });
  upload.addEventListener("click", async () => {
    const files = selected.slice();
    if (!files.length || working) return;
    for (let index = 0; index < files.length; index += 1) {
      setBusy(true, `Processing photo ${index + 1} of ${files.length}…`);
      try {
        const savedPhoto = await send(files[index]);
        addSaved(savedPhoto);
        const at = selected.indexOf(files[index]);
        if (at >= 0) selected.splice(at, 1);
        sync();
      } catch (error) {
        say(error.message);
        setBusy(false);
        return;
      }
    }
    setBusy(false);
    say(files.length === 1 ? "Photo uploaded." : `${files.length} photos uploaded.`);
  });
  const form = box.closest("form");
  if (form) {
    form.addEventListener("submit", (event) => {
      if (working) {
        event.preventDefault();
        say("Wait until the photo finishes processing.");
        return;
      }
      if (selected.length) {
        event.preventDefault();
        say("Press Upload photo first. Saving the card does not send the photo.");
      }
    });
  }
}

function bindQcVideoBox(box) {
  const preview = box.querySelector("[data-video-preview]");
  const status = box.querySelector("[data-video-status]");
  const list = box.querySelector("[data-video-list]");
  const saved = box.querySelector("[data-video-saved]");
  const busy = box.querySelector("[data-video-busy]");
  const busyText = box.querySelector("[data-video-busy-text]");
  const upload = box.querySelector("[data-video-upload]");
  const cameraLabel = box.querySelector("[data-video-camera-label]");
  const camera = box.querySelector("[data-video-camera]");
  const gallery = box.querySelector("[data-video-gallery]");
  const record = box.querySelector("[data-video-record]");
  const stop = box.querySelector("[data-video-stop]");
  const maxBytes = 200 * 1024 * 1024;
  const maxClips = 8;
  const liveCamera = window.isSecureContext && navigator.mediaDevices && window.MediaRecorder;
  const selected = [];
  const token = document.querySelector("[name=csrfmiddlewaretoken]");
  if (liveCamera) {
    cameraLabel.hidden = true;
    record.hidden = false;
  }
  let recorder = null;
  let stream = null;
  let timer = null;
  let working = false;

  function say(text) {
    if (status) status.textContent = text;
  }

  function setBusy(on, text) {
    working = on;
    box.classList.toggle("is-busy", on);
    if (busy) busy.hidden = !on;
    if (on && busy) busy.scrollIntoView({ block: "center" });
    if (busyText && text) busyText.textContent = text;
    if (upload) upload.disabled = on || !selected.length;
  }

  function sync() {
    list.replaceChildren();
    selected.forEach((file, index) => {
      const item = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MB`;
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
    if (upload) upload.disabled = working || !selected.length;
    if (!selected.length) {
      say("Record or choose the inspection video, then press Upload video. Saving the card does not send the video.");
    } else {
      say(`${selected.length} video${selected.length === 1 ? "" : "s"} waiting. Press Upload video.`);
    }
  }

  function addSaved(video) {
    const clip = document.createElement("div");
    clip.className = "video-clip";
    clip.dataset.videoClip = String(video.id);
    const player = document.createElement("video");
    player.className = "clip";
    player.controls = true;
    player.playsInline = true;
    player.src = video.url;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn-ghost";
    button.dataset.videoRemove = String(video.id);
    button.textContent = `Remove ${video.name}`;
    button.addEventListener("click", () => removeSaved(video.id, clip));
    clip.append(player, button);
    saved.append(clip);
  }

  function addFile(file) {
    if (!file || !file.size || working) return;
    if (file.size > maxBytes) {
      say(`${file.name} is over 200 MB. Each video must be 200 MB or smaller.`);
      return;
    }
    const already = saved.querySelectorAll("[data-video-clip]").length;
    if (already + selected.length >= maxClips) {
      say(`You can keep up to ${maxClips} videos.`);
      return;
    }
    selected.push(file);
    sync();
  }

  async function send(file) {
    const body = new FormData();
    body.append("video", file);
    const response = await fetch(box.dataset.uploadUrl, {
      method: "POST",
      body,
      headers: { "X-CSRFToken": token ? token.value : "" },
      credentials: "same-origin",
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "The video could not be uploaded.");
    return data;
  }

  async function removeSaved(id, clip) {
    if (working) return;
    setBusy(true, "Removing video…");
    try {
      const response = await fetch(`${box.dataset.removeBase}${id}/remove/`, {
        method: "POST",
        headers: { "X-CSRFToken": token ? token.value : "" },
        credentials: "same-origin",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "The video could not be removed.");
      clip.remove();
      say("Video removed.");
    } catch (error) {
      say(error.message);
    } finally {
      setBusy(false);
    }
  }

  saved.querySelectorAll("[data-video-remove]").forEach((button) => {
    button.addEventListener("click", () => {
      const clip = button.closest("[data-video-clip]");
      removeSaved(button.dataset.videoRemove, clip);
    });
  });

  gallery.addEventListener("change", () => {
    Array.from(gallery.files || []).forEach(addFile);
    gallery.value = "";
  });
  camera.addEventListener("change", () => {
    if (camera.files[0]) addFile(camera.files[0]);
    camera.value = "";
  });

  upload.addEventListener("click", async () => {
    const files = selected.slice();
    if (!files.length || working) return;
    for (let index = 0; index < files.length; index += 1) {
      setBusy(true, `Processing video ${index + 1} of ${files.length}…`);
      try {
        const savedVideo = await send(files[index]);
        addSaved(savedVideo);
        const at = selected.indexOf(files[index]);
        if (at >= 0) selected.splice(at, 1);
        sync();
      } catch (error) {
        say(error.message);
        setBusy(false);
        return;
      }
    }
    setBusy(false);
    say(files.length === 1 ? "Video uploaded." : `${files.length} videos uploaded.`);
  });

  const form = box.closest("form");
  if (form) {
    form.addEventListener("submit", (event) => {
      if (working) {
        event.preventDefault();
        say("Wait until the video finishes processing.");
        return;
      }
      if (selected.length) {
        event.preventDefault();
        say("Press Upload video first. Saving the card does not send the video.");
      }
    });
  }

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
    if (working) return;
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
      say("Recording… it stops at 20 seconds. Then press Upload video.");
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
