(function () {
  const STORAGE_KEY = "kb-review-admin-token";
  const tokenForm = document.getElementById("tokenForm");
  const adminTokenInput = document.getElementById("adminToken");
  const skipTokenButton = document.getElementById("skipToken");
  const logoutButton = document.getElementById("logoutButton");
  const authSection = document.getElementById("authSection");
  const queueSection = document.getElementById("queueSection");
  const reviewList = document.getElementById("reviewList");
  const messageBar = document.getElementById("messageBar");
  const refreshButton = document.getElementById("refreshQueue");
  const testerDialog = document.getElementById("chatTester");
  const testerForm = document.getElementById("testerForm");
  const testerQuestion = document.getElementById("testerQuestion");
  const testerStatus = document.getElementById("testerStatus");
  const testerResult = document.getElementById("testerResult");
  const testerAnswer = document.getElementById("testerAnswer");
  const testerNote = document.getElementById("testerNote");
  const testerCitations = document.getElementById("testerCitations");
  const closeTesterButton = document.getElementById("closeTester");

  let adminToken = null;
  const savedToken = window.localStorage.getItem(STORAGE_KEY);
  if (savedToken !== null) {
    adminToken = savedToken;
  }

  const dialogSupported = typeof window.HTMLDialogElement === "function" && testerDialog instanceof HTMLDialogElement;

  function updateAuthView() {
    const hasCredential = adminToken !== null;
    authSection.hidden = hasCredential;
    queueSection.hidden = !hasCredential;
    logoutButton.hidden = !hasCredential;
    if (hasCredential) {
      loadQueue();
    } else {
      reviewList.innerHTML = "";
      clearMessage();
      adminTokenInput.value = "";
    }
  }

  function setToken(value) {
    if (value === null) {
      adminToken = null;
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      adminToken = value;
      window.localStorage.setItem(STORAGE_KEY, value);
    }
    updateAuthView();
  }

  function adminHeaders() {
    const headers = { Accept: "application/json" };
    if (adminToken) {
      headers["X-Admin-Token"] = adminToken;
    }
    return headers;
  }

  function showMessage(text, variant = "info") {
    if (!messageBar) {
      return;
    }
    messageBar.textContent = text;
    messageBar.dataset.status = variant;
  }

  function clearMessage() {
    if (!messageBar) {
      return;
    }
    messageBar.textContent = "";
    delete messageBar.dataset.status;
  }

  async function loadQueue() {
    if (adminToken === null) {
      return;
    }
    showMessage("Loading review queue…", "info");
    reviewList.innerHTML = "";
    try {
      const response = await fetch("/admin/review/cards", { headers: adminHeaders() });
      if (response.status === 401) {
        showMessage("Admin token rejected. Please enter it again.", "error");
        setToken(null);
        return;
      }
      if (!response.ok) {
        throw new Error(`Failed to load review queue: ${response.status}`);
      }
      const payload = await response.json();
      const cards = Array.isArray(payload.cards) ? payload.cards : [];
      renderCards(cards);
      if (cards.length === 0) {
        showMessage("The review queue is empty. Generate cards with the learning agent to populate it.", "success");
      } else {
        showMessage(`Loaded ${cards.length} card${cards.length === 1 ? "" : "s"} awaiting review.`, "success");
      }
    } catch (error) {
      console.error(error);
      showMessage(error instanceof Error ? error.message : "Unable to load review queue.", "error");
    }
  }

  function renderCards(cards) {
    reviewList.innerHTML = "";
    cards.forEach((card) => {
      const entry = document.createElement("article");
      entry.className = "review-card review-entry";
      entry.dataset.cardId = card.cardId;

      const header = document.createElement("header");
      header.className = "review-entry__header";

      const title = document.createElement("h3");
      title.textContent = card.canonicalQuestion || "Untitled question";
      header.appendChild(title);

      const statusBadge = document.createElement("span");
      statusBadge.className = `status-badge status-${(card.status || "pending").replace(/_/g, "-")}`;
      statusBadge.textContent = (card.status || "pending").replace(/_/g, " ");
      statusBadge.setAttribute("aria-label", "Current review status");
      header.appendChild(statusBadge);

      entry.appendChild(header);

      const metrics = document.createElement("p");
      metrics.className = "review-entry__metrics";
      const avgConfidence = card.metrics && typeof card.metrics.averageConfidence === "number"
        ? card.metrics.averageConfidence.toFixed(2)
        : "n/a";
      const occurrences = card.metrics && typeof card.metrics.occurrenceCount === "number"
        ? card.metrics.occurrenceCount
        : "n/a";
      metrics.textContent = `Avg confidence: ${avgConfidence} • Occurrences: ${occurrences}`;
      entry.appendChild(metrics);

      const answer = document.createElement("p");
      answer.className = "review-entry__answer";
      answer.textContent = card.shortAnswer || "(No short answer provided)";
      entry.appendChild(answer);

      if (Array.isArray(card.sourceEmails) && card.sourceEmails.length > 0) {
        const sources = document.createElement("p");
        sources.className = "review-entry__sources";
        sources.textContent = `Source emails: ${card.sourceEmails.join(", ")}`;
        entry.appendChild(sources);
      }

      if (card.metadata && Object.keys(card.metadata).length > 0) {
        const metaContainer = document.createElement("div");
        metaContainer.className = "review-entry__metadata";
        const metaTitle = document.createElement("h4");
        metaTitle.textContent = "Metadata";
        metaContainer.appendChild(metaTitle);
        const metaList = document.createElement("dl");
        Object.entries(card.metadata).forEach(([key, value]) => {
          const dt = document.createElement("dt");
          dt.textContent = key;
          const dd = document.createElement("dd");
          dd.textContent = Array.isArray(value) ? value.join(", ") : String(value);
          metaList.appendChild(dt);
          metaList.appendChild(dd);
        });
        metaContainer.appendChild(metaList);
        entry.appendChild(metaContainer);
      }

      const controls = document.createElement("div");
      controls.className = "review-entry__controls";

      const statusLabel = document.createElement("label");
      statusLabel.textContent = "Status";
      const statusSelect = document.createElement("select");
      statusSelect.className = "status-select";
      [
        ["pending", "Pending"],
        ["approved", "Approved"],
        ["changes_requested", "Changes requested"],
        ["rejected", "Rejected"],
      ].forEach(([value, label]) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        if ((card.status || "pending") === value) {
          option.selected = true;
        }
        statusSelect.appendChild(option);
      });
      statusLabel.appendChild(statusSelect);
      controls.appendChild(statusLabel);

      const ratingLabel = document.createElement("label");
      ratingLabel.textContent = "Rating";
      const ratingSelect = document.createElement("select");
      ratingSelect.className = "rating-select";
      const emptyOption = document.createElement("option");
      emptyOption.value = "";
      emptyOption.textContent = "No rating";
      ratingSelect.appendChild(emptyOption);
      for (let i = 1; i <= 5; i += 1) {
        const option = document.createElement("option");
        option.value = String(i);
        option.textContent = `${i} / 5`;
        if (Number(card.rating) === i) {
          option.selected = true;
        }
        ratingSelect.appendChild(option);
      }
      ratingLabel.appendChild(ratingSelect);
      controls.appendChild(ratingLabel);

      const notesLabel = document.createElement("label");
      notesLabel.textContent = "Notes";
      const notesField = document.createElement("textarea");
      notesField.className = "review-notes";
      notesField.rows = 3;
      notesField.placeholder = "Guidance for knowledge editors or auditors";
      notesField.value = card.notes || "";
      notesLabel.appendChild(notesField);
      controls.appendChild(notesLabel);

      const buttons = document.createElement("div");
      buttons.className = "review-entry__actions";

      const saveButton = document.createElement("button");
      saveButton.type = "button";
      saveButton.className = "save-review";
      saveButton.textContent = "Save review";
      buttons.appendChild(saveButton);

      const testButton = document.createElement("button");
      testButton.type = "button";
      testButton.className = "test-review secondary";
      testButton.textContent = "Test chatbot";
      buttons.appendChild(testButton);

      controls.appendChild(buttons);
      entry.appendChild(controls);

      reviewList.appendChild(entry);
    });
  }

  async function handleSave(entry) {
    if (!entry) {
      return;
    }
    const cardId = entry.dataset.cardId;
    const statusSelect = entry.querySelector(".status-select");
    const ratingSelect = entry.querySelector(".rating-select");
    const notesField = entry.querySelector(".review-notes");
    const payload = {
      status: statusSelect ? statusSelect.value : "pending",
      rating: ratingSelect && ratingSelect.value ? Number(ratingSelect.value) : null,
      notes: notesField && notesField.value ? notesField.value : null,
    };

    try {
      const response = await fetch(`/admin/review/cards/${encodeURIComponent(cardId)}`, {
        method: "POST",
        headers: Object.assign({ "Content-Type": "application/json" }, adminHeaders()),
        body: JSON.stringify(payload),
      });
      if (response.status === 401) {
        showMessage("Admin token rejected. Please authenticate again.", "error");
        setToken(null);
        return;
      }
      if (!response.ok) {
        throw new Error("Unable to save review.");
      }
      showMessage("Review saved.", "success");
      loadQueue();
    } catch (error) {
      console.error(error);
      showMessage(error instanceof Error ? error.message : "Unable to save review.", "error");
    }
  }

  function openTester(entry) {
    if (!entry) {
      return;
    }
    const cardId = entry.dataset.cardId || "manual";
    testerDialog.dataset.cardId = cardId;
    const question = entry.querySelector("h3");
    testerQuestion.value = question ? question.textContent : "";
    testerStatus.textContent = "";
    testerResult.hidden = true;
    testerNote.hidden = true;
    testerCitations.hidden = true;
    testerAnswer.textContent = "";
    if (dialogSupported) {
      testerDialog.showModal();
    } else {
      testerDialog.setAttribute("open", "open");
    }
  }

  function closeTester() {
    testerStatus.textContent = "";
    if (dialogSupported) {
      testerDialog.close();
    } else {
      testerDialog.removeAttribute("open");
    }
  }

  async function runChatbotTest(event) {
    event.preventDefault();
    const cardId = testerDialog.dataset.cardId || "manual";
    const question = testerQuestion.value.trim();
    if (!question) {
      testerStatus.textContent = "Enter a question to test.";
      return;
    }
    testerStatus.textContent = "Requesting response…";
    testerResult.hidden = true;
    testerNote.hidden = true;
    testerCitations.hidden = true;
    testerAnswer.textContent = "";
    try {
      const response = await fetch("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          session_id: `review-${cardId}`,
          top_k: 5,
        }),
      });
      if (!response.ok) {
        throw new Error(`Chatbot returned ${response.status}`);
      }
      const payload = await response.json();
      const answer = payload.answer || "No answer was generated.";
      const note = payload.note || "";
      testerAnswer.textContent = answer;
      testerResult.hidden = false;
      if (note) {
        testerNote.textContent = note;
        testerNote.hidden = false;
      }
      const citations = Array.isArray(payload.citations) ? payload.citations : [];
      if (citations.length > 0) {
        const list = document.createElement("ul");
        citations.forEach((item) => {
          const li = document.createElement("li");
          const parts = [item.label, item.title].filter(Boolean);
          if (item.url) {
            const link = document.createElement("a");
            link.href = item.url;
            link.target = "_blank";
            link.rel = "noopener";
            link.textContent = parts.join(" – ") || item.url;
            li.appendChild(link);
          } else {
            li.textContent = parts.join(" – ") || "Context";
          }
          if (item.preview) {
            const preview = document.createElement("p");
            preview.textContent = item.preview;
            preview.className = "tester-citation__preview";
            li.appendChild(preview);
          }
          list.appendChild(li);
        });
        testerCitations.innerHTML = "";
        testerCitations.appendChild(list);
        testerCitations.hidden = false;
      }
      testerStatus.textContent = "";
    } catch (error) {
      console.error(error);
      testerStatus.textContent = error instanceof Error ? error.message : "Unable to query chatbot.";
    }
  }

  reviewList.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const entry = target.closest(".review-entry");
    if (!entry) {
      return;
    }
    if (target.classList.contains("save-review")) {
      handleSave(entry);
    } else if (target.classList.contains("test-review")) {
      openTester(entry);
    }
  });

  if (tokenForm) {
    tokenForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const value = adminTokenInput.value.trim();
      if (!value) {
        showMessage("Enter the admin token or continue without one.", "error");
        return;
      }
      setToken(value);
    });
  }

  if (skipTokenButton) {
    skipTokenButton.addEventListener("click", () => {
      setToken("");
    });
  }

  if (logoutButton) {
    logoutButton.addEventListener("click", () => {
      setToken(null);
    });
  }

  if (refreshButton) {
    refreshButton.addEventListener("click", () => loadQueue());
  }

  if (closeTesterButton) {
    closeTesterButton.addEventListener("click", () => {
      closeTester();
    });
  }

  if (testerForm) {
    testerForm.addEventListener("submit", runChatbotTest);
  }

  if (dialogSupported) {
    testerDialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      closeTester();
    });
  }

  updateAuthView();
})();
