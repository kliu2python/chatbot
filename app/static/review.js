const tokenStorageKey = 'kb-review-admin-token';
const reviewerStorageKey = 'kb-reviewer-name';

const adminTokenInput = document.getElementById('adminToken');
const reviewerInput = document.getElementById('reviewerName');
const applyTokenButton = document.getElementById('applyToken');
const tokenStatus = document.getElementById('tokenStatus');
const refreshButton = document.getElementById('refreshCards');
const statusFilter = document.getElementById('statusFilter');
const cardList = document.getElementById('cardList');
const cardMessage = document.getElementById('cardMessage');
const reviewTemplate = document.getElementById('reviewTemplate');
const chatbotForm = document.getElementById('chatbotForm');
const chatbotStatus = document.getElementById('chatbotStatus');
const chatbotResult = document.getElementById('chatbotResult');
const chatbotQuestion = document.getElementById('chatbotQuestion');
const chatbotAnswer = document.getElementById('chatbotAnswer');
const chatbotNote = document.getElementById('chatbotNote');
const chatbotSources = document.getElementById('chatbotSources');
const testTopKInput = document.getElementById('testTopK');
const testWebSearchInput = document.getElementById('testWebSearch');
const testQuestionInput = document.getElementById('testQuestion');

function getStoredToken() {
  return sessionStorage.getItem(tokenStorageKey) || '';
}

function setStoredToken(token) {
  if (token) {
    sessionStorage.setItem(tokenStorageKey, token);
  } else {
    sessionStorage.removeItem(tokenStorageKey);
  }
}

function getReviewerName() {
  return sessionStorage.getItem(reviewerStorageKey) || reviewerInput.value.trim();
}

function setReviewerName(name) {
  if (name) {
    sessionStorage.setItem(reviewerStorageKey, name);
  } else {
    sessionStorage.removeItem(reviewerStorageKey);
  }
}

function updateTokenStatus(message, tone = 'info') {
  if (!tokenStatus) return;
  tokenStatus.textContent = message;
  tokenStatus.dataset.tone = tone;
}

function applyStoredCredentials() {
  const existingToken = getStoredToken();
  const storedReviewer = sessionStorage.getItem(reviewerStorageKey) || '';
  if (existingToken) {
    adminTokenInput.value = existingToken;
    updateTokenStatus('Token loaded from session.', 'success');
  }
  if (storedReviewer) {
    reviewerInput.value = storedReviewer;
  }
}

async function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = adminTokenInput.value.trim() || getStoredToken();
  if (!headers.has('Content-Type') && options.body) {
    headers.set('Content-Type', 'application/json');
  }
  if (token) {
    headers.set('X-Admin-Token', token);
  }

  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    throw new Error('Admin authorization failed. Check your token.');
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      if (payload && payload.detail) {
        detail = payload.detail;
      }
    } catch (err) {
      // Ignore JSON parsing errors and keep status text
    }
    throw new Error(`Request failed (${response.status}): ${detail}`);
  }
  if (response.status === 204) {
    return null;
  }
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    return text;
  }
}

function normalizeList(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  return [value];
}

function formatStatus(status) {
  if (!status) return 'Unknown';
  const mapping = {
    pending: 'Pending review',
    approved: 'Approved',
    rejected: 'Rejected',
    needs_changes: 'Needs changes',
  };
  return mapping[status] || status;
}

function renderMetadataList(container, metadata) {
  if (!metadata || typeof metadata !== 'object') return;
  const dl = document.createElement('dl');
  Object.entries(metadata).forEach(([key, value]) => {
    const term = document.createElement('dt');
    term.textContent = key;
    const definition = document.createElement('dd');
    definition.textContent = Array.isArray(value) || typeof value === 'object'
      ? JSON.stringify(value, null, 2)
      : String(value);
    dl.append(term, definition);
  });
  container.appendChild(dl);
}

function createDefinitionList(card) {
  const dl = document.createElement('dl');
  const rows = [
    ['Canonical question', card.canonicalQuestion || '—'],
    ['Short answer', card.shortAnswer || '—'],
  ];

  rows.forEach(([label, value]) => {
    const dt = document.createElement('dt');
    dt.textContent = label;
    const dd = document.createElement('dd');
    dd.textContent = value;
    dl.append(dt, dd);
  });

  const stepItems = normalizeList(card.stepByStep);
  if (stepItems.length) {
    const dt = document.createElement('dt');
    dt.textContent = 'Step-by-step';
    const dd = document.createElement('dd');
    const list = document.createElement('ol');
    stepItems.forEach((step) => {
      const li = document.createElement('li');
      li.textContent = step;
      list.appendChild(li);
    });
    dd.appendChild(list);
    dl.append(dt, dd);
  }

  const constraints = normalizeList(card.constraints);
  if (constraints.length) {
    const dt = document.createElement('dt');
    dt.textContent = 'Constraints';
    const dd = document.createElement('dd');
    dd.appendChild(renderBadgeList(constraints));
    dl.append(dt, dd);
  }

  const caveats = normalizeList(card.caveats);
  if (caveats.length) {
    const dt = document.createElement('dt');
    dt.textContent = 'Caveats';
    const dd = document.createElement('dd');
    dd.appendChild(renderBadgeList(caveats));
    dl.append(dt, dd);
  }

  const links = normalizeList(card.links);
  if (links.length) {
    const dt = document.createElement('dt');
    dt.textContent = 'Links';
    const dd = document.createElement('dd');
    const list = document.createElement('ul');
    links.forEach((link) => {
      const li = document.createElement('li');
      const anchor = document.createElement('a');
      anchor.href = link;
      anchor.textContent = link;
      anchor.target = '_blank';
      anchor.rel = 'noopener noreferrer';
      li.appendChild(anchor);
      list.appendChild(li);
    });
    dd.appendChild(list);
    dl.append(dt, dd);
  }

  if (card.metrics && typeof card.metrics === 'object') {
    const dt = document.createElement('dt');
    dt.textContent = 'Metrics';
    const dd = document.createElement('dd');
    dd.textContent = JSON.stringify(card.metrics, null, 2);
    dl.append(dt, dd);
  }

  if (card.metadata && typeof card.metadata === 'object') {
    const dt = document.createElement('dt');
    dt.textContent = 'Metadata';
    const dd = document.createElement('dd');
    renderMetadataList(dd, card.metadata);
    dl.append(dt, dd);
  }

  return dl;
}

function renderBadgeList(items) {
  const wrapper = document.createElement('div');
  wrapper.className = 'badge-list';
  items.forEach((item) => {
    const badge = document.createElement('span');
    badge.textContent = item;
    wrapper.appendChild(badge);
  });
  return wrapper;
}

function renderReviews(container, card) {
  container.innerHTML = '';
  const reviews = Array.isArray(card.reviews) ? card.reviews : [];
  if (!reviews.length) {
    const empty = document.createElement('p');
    empty.textContent = 'No reviews yet.';
    empty.className = 'empty-state';
    container.appendChild(empty);
    return;
  }

  reviews
    .slice()
    .reverse()
    .forEach((review) => {
      const entry = document.createElement('div');
      entry.className = 'review-entry';

      const meta = document.createElement('div');
      meta.className = 'review-meta';
      const reviewer = document.createElement('span');
      reviewer.textContent = `${review.reviewer || 'Unknown'} · Rating ${review.rating ?? 'n/a'}`;
      const decision = document.createElement('span');
      decision.textContent = formatStatus(review.decision);
      meta.append(reviewer, decision);

      const timestamp = document.createElement('small');
      if (review.reviewed_at) {
        const date = new Date(review.reviewed_at);
        timestamp.textContent = date.toLocaleString();
      }

      const notes = document.createElement('p');
      notes.className = 'review-notes';
      notes.textContent = review.notes || 'No notes provided.';

      entry.append(meta);
      if (timestamp.textContent) {
        entry.append(timestamp);
      }
      entry.append(notes);
      container.appendChild(entry);
    });
}

function attachReviewHandler(cardElement, card) {
  const form = cardElement.querySelector('.review-form');
  if (!form) return;

  const statusLine = document.createElement('div');
  statusLine.className = 'status';
  form.appendChild(statusLine);

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const reviewerName = reviewerInput.value.trim() || getReviewerName();
    if (!reviewerName) {
      statusLine.textContent = 'Please provide a reviewer name before submitting.';
      return;
    }
    setReviewerName(reviewerName);

    const rating = Number(form.querySelector('input[name="rating"]:checked')?.value || 5);
    const decision = form.querySelector('.decision-select')?.value || 'approved';
    const notes = form.elements.namedItem('notes')?.value || '';

    statusLine.textContent = 'Submitting review…';
    form.querySelectorAll('input, textarea, button, select').forEach((el) => {
      el.disabled = true;
    });

    try {
      await apiFetch(`/knowledge-cards/${encodeURIComponent(card.id)}/review`, {
        method: 'POST',
        body: JSON.stringify({
          reviewer: reviewerName,
          rating,
          decision,
          notes,
        }),
      });
      statusLine.textContent = 'Review saved. Reloading cards…';
      await loadCards();
    } catch (error) {
      statusLine.textContent = error.message;
    } finally {
      form.querySelectorAll('input, textarea, button, select').forEach((el) => {
        el.disabled = false;
      });
    }
  });
}

function renderCard(card) {
  const fragment = reviewTemplate.content.cloneNode(true);
  const article = fragment.querySelector('.card');
  const title = fragment.querySelector('.card-title');
  const statusText = fragment.querySelector('.card-status');
  const idField = fragment.querySelector('.card-id');
  const bodySection = fragment.querySelector('.card-body');
  const reviewsSection = fragment.querySelector('.card-reviews');

  title.textContent = card.canonicalQuestion || 'Untitled knowledge card';
  statusText.textContent = formatStatus(card.status);
  idField.textContent = card.id;

  const definitionList = createDefinitionList(card);
  bodySection.appendChild(definitionList);

  renderReviews(reviewsSection, card);
  attachReviewHandler(article, card);

  return fragment;
}

async function loadCards() {
  if (!cardList) return;
  cardList.innerHTML = '';
  cardMessage.hidden = true;
  const statusValue = statusFilter.value;
  let query = '/knowledge-cards';
  if (statusValue) {
    const params = new URLSearchParams({ status: statusValue });
    query += `?${params.toString()}`;
  }

  try {
    const cards = await apiFetch(query);
    if (!cards || !cards.length) {
      cardMessage.hidden = false;
      return;
    }
    const fragment = document.createDocumentFragment();
    cards.forEach((card) => {
      fragment.appendChild(renderCard(card));
    });
    cardList.appendChild(fragment);
  } catch (error) {
    cardMessage.textContent = error.message;
    cardMessage.hidden = false;
  }
}

async function pollTask(taskId, attempt = 0) {
  const delay = Math.min(1500 * (attempt + 1), 5000);
  await new Promise((resolve) => setTimeout(resolve, delay));
  return apiFetch(`/tasks/${encodeURIComponent(taskId)}`);
}

function renderChatbotResult(result) {
  if (!result || !result.result) return;
  const payload = result.result;
  chatbotResult.hidden = false;
  chatbotQuestion.textContent = payload.question || '';
  chatbotAnswer.textContent = payload.answer || '(No answer produced)';

  if (payload.note) {
    chatbotNote.textContent = payload.note;
    chatbotNote.hidden = false;
  } else {
    chatbotNote.hidden = true;
  }

  chatbotSources.innerHTML = '';
  const citations = Array.isArray(payload.citations) ? payload.citations : [];
  if (!citations.length) {
    chatbotSources.hidden = true;
  } else {
    citations.forEach((citation) => {
      const entry = document.createElement('div');
      entry.className = 'source-entry';
      const label = document.createElement('span');
      label.textContent = citation.label || citation.id || 'source';
      entry.appendChild(label);
      if (citation.url) {
        const anchor = document.createElement('a');
        anchor.href = citation.url;
        anchor.target = '_blank';
        anchor.rel = 'noopener noreferrer';
        anchor.textContent = 'Open';
        entry.appendChild(anchor);
      }
      chatbotSources.appendChild(entry);
    });
    chatbotSources.hidden = false;
  }
}

async function runChatbotTest(event) {
  event.preventDefault();
  const question = testQuestionInput.value.trim();
  const topK = Number(testTopKInput.value || '5');
  const useWebSearch = Boolean(testWebSearchInput.checked);

  if (!question) {
    chatbotStatus.textContent = 'Enter a question to test the chatbot.';
    return;
  }

  chatbotStatus.textContent = 'Submitting test request…';
  chatbotResult.hidden = true;

  try {
    const task = await apiFetch('/ask', {
      method: 'POST',
      body: JSON.stringify({
        question,
        top_k: topK,
        use_web_search: useWebSearch,
      }),
    });

    if (!task || !task.task_id) {
      chatbotStatus.textContent = 'Unexpected response from chatbot service.';
      return;
    }

    chatbotStatus.textContent = 'Waiting for chatbot response…';
    let attempt = 0;
    let status;
    do {
      status = await pollTask(task.task_id, attempt);
      attempt += 1;
    } while (status && status.status !== 'completed' && attempt < 10);

    if (!status) {
      chatbotStatus.textContent = 'Unable to fetch chatbot response.';
      return;
    }

    if (status.status !== 'completed') {
      chatbotStatus.textContent = `Task did not complete (status: ${status.status}).`;
      return;
    }

    chatbotStatus.textContent = 'Chatbot response received.';
    renderChatbotResult(status);
  } catch (error) {
    chatbotStatus.textContent = error.message;
  }
}

applyTokenButton.addEventListener('click', () => {
  const tokenValue = adminTokenInput.value.trim();
  const reviewerName = reviewerInput.value.trim();
  setStoredToken(tokenValue);
  setReviewerName(reviewerName);
  if (tokenValue) {
    updateTokenStatus('Token saved for this session.', 'success');
  } else {
    updateTokenStatus('Token cleared.', 'info');
  }
  loadCards();
});

refreshButton.addEventListener('click', loadCards);
statusFilter.addEventListener('change', loadCards);
chatbotForm.addEventListener('submit', runChatbotTest);

applyStoredCredentials();
loadCards();
