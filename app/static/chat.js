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

const chatWidget = document.getElementById('chatWidget');
const chatToggle = document.getElementById('chatToggle');
const closeChat = document.getElementById('closeChat');
const chatForm = document.getElementById('chatForm');
const chatInput = document.getElementById('chatInput');
const chatMessages = document.getElementById('chatMessages');
const sendButton = document.getElementById('sendButton');
const openChatFromIntro = document.getElementById('openChatFromIntro');

if (!chatWidget || !chatToggle || !closeChat || !chatForm || !chatInput || !chatMessages || !sendButton) {
    console.error('FortiIdentity chat widget markup is missing required elements.');
}

const SESSION_KEY = globalConfig.sessionStorageKey || 'fortiidentity-chat-session-id';
let sessionId = window.localStorage.getItem(SESSION_KEY);

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

function appendMessage(content, type = 'bot', sources = []) {
    const wrapper = document.createElement('div');
    wrapper.className = `message message--${type}`;

    const messageContent = document.createElement('div');
    messageContent.className = 'message__text';
    messageContent.innerHTML = content;
    wrapper.appendChild(messageContent);

    if (type === 'bot' && sources.length > 0) {
        const sourceBlock = document.createElement('div');
        sourceBlock.className = 'message__sources';
        sourceBlock.textContent = `Sources: ${sources.map(src => `[#${src.id} ${src.source || 'context'}]`).join(' ')}`;
        wrapper.appendChild(sourceBlock);
    }

    if (!chatMessages) {
        return;
    }

    chatMessages.appendChild(wrapper);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function renderHistory(history = []) {
    if (!chatMessages) {
        return;
    }

    chatMessages.innerHTML = '';
    history.forEach(entry => {
        appendMessage(entry.question, 'user');
        const responseText = entry.answer || entry.note || 'No response available.';
        appendMessage(responseText.replace(/\n/g, '<br/>'), 'bot', entry.sources || []);
    });
}

async function askQuestion(question) {
    if (sendButton) {
        sendButton.disabled = true;
        sendButton.textContent = 'Sending…';
    }

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
        renderHistory(data.history || []);
    } catch (error) {
        appendMessage('Sorry, something went wrong contacting the assistant. Please try again.', 'bot');
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
            } else {
                // Remove placeholder append from empty question if backend returns entry
                if (Array.isArray(data.history) && data.history.length === 0) {
                    chatMessages.innerHTML = '';
                }
            }
        }
    } catch (error) {
        console.warn('Unable to pre-load chat history', error);
    }
})();
