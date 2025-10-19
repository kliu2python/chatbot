const chatWidget = document.getElementById('chatWidget');
const chatToggle = document.getElementById('chatToggle');
const closeChat = document.getElementById('closeChat');
const chatForm = document.getElementById('chatForm');
const chatInput = document.getElementById('chatInput');
const chatMessages = document.getElementById('chatMessages');
const sendButton = document.getElementById('sendButton');
const openChatFromIntro = document.getElementById('openChatFromIntro');

const SESSION_KEY = 'fortiidentity-chat-session-id';
let sessionId = window.localStorage.getItem(SESSION_KEY);

if (!sessionId) {
    sessionId = crypto.randomUUID();
    window.localStorage.setItem(SESSION_KEY, sessionId);
}

function setWidgetOpen(isOpen) {
    if (isOpen) {
        chatWidget.classList.add('chat-widget--open');
        chatWidget.setAttribute('aria-expanded', 'true');
        chatInput.focus();
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

    chatMessages.appendChild(wrapper);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function renderHistory(history = []) {
    chatMessages.innerHTML = '';
    history.forEach(entry => {
        appendMessage(entry.question, 'user');
        const responseText = entry.answer || entry.note || 'No response available.';
        appendMessage(responseText.replace(/\n/g, '<br/>'), 'bot', entry.sources || []);
    });
}

async function askQuestion(question) {
    sendButton.disabled = true;
    sendButton.textContent = 'Sending…';

    try {
        const response = await fetch('/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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
        sendButton.disabled = false;
        sendButton.textContent = 'Send';
    }
}

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

chatToggle.addEventListener('click', () => setWidgetOpen(!chatWidget.classList.contains('chat-widget--open')));
closeChat.addEventListener('click', () => setWidgetOpen(false));
openChatFromIntro.addEventListener('click', () => setWidgetOpen(true));

// Load existing history when the page loads
(async () => {
    try {
        const response = await fetch('/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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
