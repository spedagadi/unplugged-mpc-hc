/* unplugged — site behaviour: mobile navigation, copy buttons, active link. */
(function () {
  document.documentElement.classList.add("js");

  var head = document.querySelector(".site-head");
  var toggle = document.querySelector(".nav-toggle");
  if (head && toggle) {
    toggle.addEventListener("click", function () {
      var open = head.classList.toggle("nav-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  var here = window.location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll(".nav-links a").forEach(function (link) {
    var target = (link.getAttribute("href") || "").split("/").pop();
    if (target && target === here) link.setAttribute("aria-current", "page");
  });

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      try {
        var area = document.createElement("textarea");
        area.value = text;
        area.setAttribute("readonly", "");
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        var ok = document.execCommand("copy");
        document.body.removeChild(area);
        ok ? resolve() : reject(new Error("copy rejected"));
      } catch (err) {
        reject(err);
      }
    });
  }

  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.addEventListener("click", function () {
      var value = button.getAttribute("data-copy");
      var status = button.parentElement.querySelector(".copy-status");
      copyText(value).then(function () {
        if (status) status.textContent = "Copied.";
      }).catch(function () {
        if (status) status.textContent = "Select the value and copy it manually.";
      });
    });
  });
})();

/* Site search: header button, modal, and search-index.json. */
(function () {
  var headIn = document.querySelector(".head-in");
  if (!headIn) return;

  var searchBtn = document.createElement("button");
  searchBtn.type = "button";
  searchBtn.className = "search-toggle";
  searchBtn.setAttribute("aria-label", "Search");
  searchBtn.setAttribute("aria-expanded", "false");
  searchBtn.setAttribute("aria-controls", "site-search");
  searchBtn.innerHTML = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="9" cy="9" r="5.5"/><path d="m13.2 13.2 3.8 3.8"/></svg>';
  var searchAnchor = headIn.querySelector(".head-cta") || headIn.querySelector(".nav-toggle");
  headIn.insertBefore(searchBtn, searchAnchor);

  var modal = document.createElement("div");
  modal.className = "search-modal";
  modal.id = "site-search";
  modal.hidden = true;
  modal.innerHTML =
    '<div class="search-panel" role="dialog" aria-modal="true" aria-label="Search unplugged">' +
      '<form class="search-form" role="search">' +
        '<input class="search-input" id="search-input" type="search" placeholder="Search features, setup and the user guide…" autocomplete="off" aria-label="Search">' +
        '<button class="search-close" type="button" aria-label="Close search">Esc</button>' +
      '</form>' +
      '<ul class="search-results" aria-live="polite"></ul>' +
      '<p class="search-hint">Search features, setup, HDR, calibration and the user guide.</p>' +
    '</div>';
  document.body.appendChild(modal);

  var input = modal.querySelector(".search-input");
  var results = modal.querySelector(".search-results");
  var closeBtn = modal.querySelector(".search-close");
  var form = modal.querySelector(".search-form");
  var index = null;
  var indexPromise = null;
  var timer = null;

  function loadIndex() {
    if (index) return Promise.resolve(index);
    if (!indexPromise) {
      indexPromise = fetch("search-index.json", { cache: "no-cache" })
        .then(function (response) {
          if (!response.ok) throw new Error("HTTP " + response.status);
          return response.json();
        })
        .then(function (data) {
          index = data;
          return index;
        });
    }
    return indexPromise;
  }

  function showMessage(text) {
    results.innerHTML = "";
    var item = document.createElement("li");
    item.className = "search-empty";
    item.textContent = text;
    results.appendChild(item);
  }

  function showError() {
    showMessage("Search index could not load. Check that search-index.json is deployed.");
  }

  function excerpt(text, tokens) {
    text = text || "";
    var lower = text.toLowerCase();
    var at = -1;
    tokens.forEach(function (token) {
      var found = lower.indexOf(token);
      if (found >= 0 && (at < 0 || found < at)) at = found;
    });
    if (at < 0) at = 0;
    var start = Math.max(0, at - 50);
    var end = Math.min(text.length, at + 150);
    return (start > 0 ? "…" : "") + text.slice(start, end).trim() + (end < text.length ? "…" : "");
  }

  function render(query) {
    if (!index) return;
    var value = String(query || "").trim();
    var q = value.toLowerCase();
    if (q.length < 2) {
      showMessage("Type at least two characters. Try “tone mapping”, “black bars” or “SDR nits”.");
      return;
    }
    var tokens = q.split(/\s+/).filter(Boolean);
    var scored = [];
    index.forEach(function (item) {
      var title = String(item.title || "").toLowerCase();
      var section = String(item.section || "").toLowerCase();
      var text = String(item.text || "").toLowerCase();
      var score = 0;
      if (title.indexOf(q) !== -1) score += 18;
      tokens.forEach(function (token) {
        if (title.indexOf(token) !== -1) score += 7;
        if (section.indexOf(token) !== -1) score += 3;
        if (text.indexOf(token) !== -1) score += 1;
      });
      if (score > 0) scored.push({ item: item, score: score });
    });
    scored.sort(function (a, b) { return b.score - a.score; });
    scored = scored.slice(0, 12);
    if (!scored.length) {
      showMessage("No matches for “" + value + "”.");
      return;
    }
    results.innerHTML = "";
    scored.forEach(function (entry) {
      var item = entry.item;
      var li = document.createElement("li");
      var link = document.createElement("a");
      link.className = "search-result";
      link.href = item.url;
      var title = document.createElement("span");
      title.className = "sr-title";
      title.textContent = item.title;
      var section = document.createElement("span");
      section.className = "sr-section";
      section.textContent = item.section || "unplugged";
      var text = document.createElement("span");
      text.className = "sr-excerpt";
      text.textContent = excerpt(item.text, tokens);
      link.appendChild(title);
      link.appendChild(section);
      link.appendChild(text);
      li.appendChild(link);
      results.appendChild(li);
    });
  }

  function openSearch() {
    if (!modal.hidden) { input.focus(); return; }
    modal.hidden = false;
    searchBtn.setAttribute("aria-expanded", "true");
    document.documentElement.classList.add("search-open");
    input.value = "";
    results.innerHTML = "";
    showMessage("Loading search…");
    input.focus();
    loadIndex().then(function () { render(input.value); }).catch(showError);
  }

  function closeSearch() {
    if (modal.hidden) return;
    modal.hidden = true;
    searchBtn.setAttribute("aria-expanded", "false");
    document.documentElement.classList.remove("search-open");
    searchBtn.focus();
  }

  function isTyping(element) {
    if (!element || !element.tagName) return false;
    var tag = element.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || element.isContentEditable;
  }

  searchBtn.addEventListener("click", function () {
    if (modal.hidden) openSearch(); else closeSearch();
  });
  closeBtn.addEventListener("click", closeSearch);
  modal.addEventListener("click", function (event) {
    if (event.target === modal) closeSearch();
  });
  form.addEventListener("submit", function (event) { event.preventDefault(); });
  input.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(function () {
      if (index) render(input.value);
      else loadIndex().then(function () { render(input.value); }).catch(showError);
    }, 80);
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !modal.hidden) {
      event.preventDefault();
      closeSearch();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && String(event.key).toLowerCase() === "k") {
      event.preventDefault();
      openSearch();
      return;
    }
    if (event.key === "/" && modal.hidden && !isTyping(event.target)) {
      event.preventDefault();
      openSearch();
    }
  });
  document.querySelectorAll("[data-open-search]").forEach(function (button) {
    button.addEventListener("click", function (event) {
      event.preventDefault();
      openSearch();
    });
  });
})();