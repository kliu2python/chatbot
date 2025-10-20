const globalConfig = window.FortiIdentityChatConfig || {};
const configuredBaseUrl = (globalConfig.baseUrl || '').replace(/\/$/, '');
const ASK_ENDPOINT = configuredBaseUrl ? `${configuredBaseUrl}/ask` : '/ask';
const baseFetchOptions = globalConfig.fetchOptions || {};
const baseHeaders = {
    'Content-Type': 'application/json',
    ...(baseFetchOptions.headers || {})
};
const sharedFetchOptions = { ...baseFetchOptions };
delete sharedFetchOptions.headers;

const chatRoot = document.querySelector('[data-fortiidentity-chat="root"]');
const chatWidget = chatRoot ? chatRoot.querySelector('#chatWidget') : null;
const chatToggle = chatRoot ? chatRoot.querySelector('#chatToggle') : null;
const closeChat = chatRoot ? chatRoot.querySelector('#closeChat') : null;
const chatForm = chatRoot ? chatRoot.querySelector('#chatForm') : null;
const chatInput = chatRoot ? chatRoot.querySelector('#chatInput') : null;
const chatMessages = chatRoot ? chatRoot.querySelector('#chatMessages') : null;
const sendButton = chatRoot ? chatRoot.querySelector('#sendButton') : null;
const openChatFromIntro = chatRoot ? chatRoot.querySelector('#openChatFromIntro') : null;

if (!chatWidget || !chatToggle || !closeChat || !chatForm || !chatInput || !chatMessages || !sendButton) {
    console.error('FortiIdentity chat widget markup is missing required elements.');
}

const SESSION_KEY = globalConfig.sessionStorageKey || 'fortiidentity-chat-session-id';
let sessionId = window.localStorage.getItem(SESSION_KEY);
let typingIndicatorElement = null;

if (!sessionId) {
    sessionId = crypto.randomUUID();
    window.localStorage.setItem(SESSION_KEY, sessionId);
}

function setWidgetOpen(isOpen) {
    if (!chatWidget) {
        return;
    }

    if (isOpen) {
        chatWidget.classList.add('chat-widget--open');
        chatWidget.setAttribute('aria-expanded', 'true');
        if (chatInput) {
            chatInput.focus();
        }
    } else {
        chatWidget.classList.remove('chat-widget--open');
        chatWidget.setAttribute('aria-expanded', 'false');
    }
}

function createCitationList(citations = []) {
    if (!Array.isArray(citations) || citations.length === 0) {
        return null;
    }

    const sourceBlock = document.createElement('div');
    sourceBlock.className = 'message__sources';

    const heading = document.createElement('div');
    heading.className = 'message__sources-heading';
    heading.textContent = 'Citations';
    sourceBlock.appendChild(heading);

    const summaryRow = document.createElement('div');
    summaryRow.className = 'message__sources-summary';

    const summaryLabel = document.createElement('span');
    summaryLabel.className = 'message__sources-summary-label';
    summaryLabel.textContent = 'Quick view:';
    summaryRow.appendChild(summaryLabel);

    citations.forEach(citation => {
        const labelText = citation.label || `[${citation.id}]`;
        const badge = citation.url ? document.createElement('a') : document.createElement('span');
        badge.className = 'message__citation-badge';
        badge.textContent = labelText;

        if (citation.url) {
            badge.href = citation.url;
            badge.target = '_blank';
            badge.rel = 'noopener noreferrer';
        }

        const hoverDetails = [citation.title, citation.section].filter(Boolean).join(' · ');
        if (hoverDetails) {
            badge.title = hoverDetails;
            badge.setAttribute('aria-label', `${labelText} – ${hoverDetails}`);
        } else if (citation.title) {
            badge.title = citation.title;
            badge.setAttribute('aria-label', `${labelText} – ${citation.title}`);
        }

        summaryRow.appendChild(badge);
    });

    sourceBlock.appendChild(summaryRow);

    const details = document.createElement('details');
    details.className = 'message__sources-details';

    const toggle = document.createElement('summary');
    toggle.textContent = 'See citation details';
    toggle.setAttribute('aria-label', 'Toggle citation details');
    details.appendChild(toggle);

    const list = document.createElement('ul');
    list.className = 'message__sources-list';

    citations.forEach(citation => {
        const item = document.createElement('li');
        item.className = 'message__sources-item';

        const label = document.createElement('span');
        label.className = 'message__citation-label';
        label.textContent = citation.label || `[${citation.id}]`;
        item.appendChild(label);

        const textWrapper = document.createElement('span');
        textWrapper.className = 'message__citation-text';

        const titleParts = [];
        if (citation.title) {
            titleParts.push(citation.title);
        }
        if (citation.section) {
            titleParts.push(citation.section);
        }
        const linkText = titleParts.join(' · ') || 'Source';

        if (citation.url) {
            const link = document.createElement('a');
            link.href = citation.url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = linkText;
            textWrapper.appendChild(link);
        } else {
            const span = document.createElement('span');
            span.textContent = linkText;
            textWrapper.appendChild(span);
        }

        if (citation.preview) {
            const preview = document.createElement('span');
            preview.className = 'message__citation-preview';
            preview.textContent = ` — ${citation.preview}`;
            textWrapper.appendChild(preview);
        }

        item.appendChild(textWrapper);
        list.appendChild(item);
    });

    details.appendChild(list);
    sourceBlock.appendChild(details);
    return sourceBlock;
}

function appendMessage(content, type = 'bot', citations = []) {
    const wrapper = document.createElement('div');
    wrapper.className = `message message--${type}`;

    const messageContent = document.createElement('div');
    messageContent.className = 'message__text';
    messageContent.innerHTML = content;
    wrapper.appendChild(messageContent);

    if (type === 'bot') {
        const citationList = createCitationList(citations);
        if (citationList) {
            wrapper.appendChild(citationList);
        }
    }

    if (!chatMessages) {
        return;
    }

    chatMessages.appendChild(wrapper);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function showTypingIndicator() {
    if (!chatMessages) {
        return;
    }

    hideTypingIndicator();

    const wrapper = document.createElement('div');
    wrapper.className = 'message message--bot message--typing';

    const indicator = document.createElement('div');
    indicator.className = 'typing-indicator';
    indicator.setAttribute('role', 'status');
    indicator.setAttribute('aria-live', 'polite');

    for (let i = 0; i < 3; i += 1) {
        const dot = document.createElement('span');
        dot.className = 'typing-indicator__dot';
        indicator.appendChild(dot);
    }

    const srOnly = document.createElement('span');
    srOnly.className = 'sr-only';
    srOnly.textContent = 'Assistant is typing';
    indicator.appendChild(srOnly);

    wrapper.appendChild(indicator);
    chatMessages.appendChild(wrapper);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    typingIndicatorElement = wrapper;
}

function hideTypingIndicator() {
    if (typingIndicatorElement && typingIndicatorElement.parentNode) {
        typingIndicatorElement.parentNode.removeChild(typingIndicatorElement);
    }
    typingIndicatorElement = null;
}

function renderHistory(history = []) {
    if (!chatMessages) {
        return;
    }

    chatMessages.innerHTML = '';
    history.forEach(entry => {
        appendMessage(entry.question, 'user');
        const responseText = entry.answer || entry.note || 'No response available.';
        appendMessage(responseText.replace(/\n/g, '<br/>'), 'bot', entry.citations || entry.sources || []);
    });
}

async function askQuestion(question) {
    if (sendButton) {
        sendButton.disabled = true;
        sendButton.textContent = 'Sending…';
    }

    showTypingIndicator();

    try {
        const response = await fetch(ASK_ENDPOINT, {
            ...sharedFetchOptions,
            method: 'POST',
            headers: baseHeaders,
            body: JSON.stringify({ question, session_id: sessionId })
        });

        if (!response.ok) {
            throw new Error(`Server responded with ${response.status}`);
        }

        const data = await response.json();
        if (data.session_id && data.session_id !== sessionId) {
            sessionId = data.session_id;
            window.localStorage.setItem(SESSION_KEY, sessionId);
        }
        hideTypingIndicator();
        renderHistory(data.history || []);
    } catch (error) {
        hideTypingIndicator();
        appendMessage('Whoops—I had trouble reaching the service just now. Let’s try that again in a moment.', 'bot');
        console.error(error);
    } finally {
        if (sendButton) {
            sendButton.disabled = false;
            sendButton.textContent = 'Send';
        }
    }
}

if (chatForm && chatInput) {
    chatForm.addEventListener('submit', event => {
        event.preventDefault();
        const question = chatInput.value.trim();
        if (!question) {
            return;
        }

        appendMessage(question, 'user');
        chatInput.value = '';
        askQuestion(question);
    });
}

if (chatToggle && chatWidget) {
    chatToggle.addEventListener('click', () => setWidgetOpen(!chatWidget.classList.contains('chat-widget--open')));
}

if (closeChat) {
    closeChat.addEventListener('click', () => setWidgetOpen(false));
}

if (openChatFromIntro) {
    openChatFromIntro.addEventListener('click', () => setWidgetOpen(true));
}

// Load existing history when the page loads
(async () => {
    try {
        const response = await fetch(ASK_ENDPOINT, {
            ...sharedFetchOptions,
            method: 'POST',
            headers: baseHeaders,
            body: JSON.stringify({ question: '', session_id: sessionId, top_k: 1 })
        });
        if (response.ok) {
            const data = await response.json();
            if ((data.history || []).length > 0) {
                renderHistory(data.history);
            }
        }
    } catch (error) {
        console.warn('Unable to pre-load chat history', error);
    }
})();
