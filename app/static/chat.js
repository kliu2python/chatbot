const globalConfig = window.ChromaFaqBotConfig || {};
const configuredBaseUrl = (globalConfig.baseUrl || '').replace(/\/$/, '');
const ASK_ENDPOINT = configuredBaseUrl ? `${configuredBaseUrl}/ask` : '/ask';
const END_SESSION_ENDPOINT = configuredBaseUrl ? `${configuredBaseUrl}/end` : '/end';
const baseFetchOptions = globalConfig.fetchOptions || {};
const baseHeaders = {
    'Content-Type': 'application/json',
    ...(baseFetchOptions.headers || {})
};
const sharedFetchOptions = { ...baseFetchOptions };
delete sharedFetchOptions.headers;

// For standalone version, get elements from document
const chatWidget = document.getElementById('chatWidget');
const chatToggle = document.getElementById('chatToggle');
const closeChat = document.getElementById('closeChat');
const chatForm = document.getElementById('chatForm');
const chatInput = document.getElementById('chatInput');
const chatMessages = document.getElementById('chatMessages');
const sendButton = document.getElementById('sendButton');
const openChatFromIntro = document.getElementById('openChatFromIntro');
const endSessionButton = document.getElementById('endSession');

if (!chatWidget || !chatForm || !chatInput || !chatMessages || !sendButton) {
    console.error('Chroma FAQ Bot widget markup is missing required elements.');
}

const SESSION_KEY = globalConfig.sessionStorageKey || 'chroma-faq-bot-session-id';
let sessionId = window.localStorage.getItem(SESSION_KEY);
let typingIndicatorElement = null;
let inactivityTimer = null;
const INACTIVITY_TIMEOUT = 5 * 60 * 1000; // 5 minutes in milliseconds

if (!sessionId) {
    sessionId = crypto.randomUUID ? crypto.randomUUID() : Date.now().toString();
    window.localStorage.setItem(SESSION_KEY, sessionId);
}

// Reset inactivity timer
function resetInactivityTimer() {
    if (inactivityTimer) {
        clearTimeout(inactivityTimer);
    }
    inactivityTimer = setTimeout(endSession, INACTIVITY_TIMEOUT);
}

// End session function
async function endSession() {
    try {
        await fetch(END_SESSION_ENDPOINT, {
            ...sharedFetchOptions,
            method: 'POST',
            headers: baseHeaders,
            body: JSON.stringify({ session_id: sessionId })
        });
    } catch (error) {
        console.error('Error ending session:', error);
    } finally {
        // Clear session data
        window.localStorage.removeItem(SESSION_KEY);
        sessionId = crypto.randomUUID ? crypto.randomUUID() : Date.now().toString();
        window.localStorage.setItem(SESSION_KEY, sessionId);

        // Clear chat messages
        if (chatMessages) {
            chatMessages.innerHTML = '';
        }

        // Reset inactivity timer
        if (inactivityTimer) {
            clearTimeout(inactivityTimer);
            inactivityTimer = null;
        }
    }
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
        resetInactivityTimer();
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
    heading.textContent = 'Sources';
    sourceBlock.appendChild(heading);

    const summaryRow = document.createElement('div');
    summaryRow.className = 'message__sources-summary';

    const summaryLabel = document.createElement('span');
    summaryLabel.className = 'message__sources-summary-label';
    summaryLabel.textContent = 'References:';
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
    toggle.textContent = 'See source details';
    toggle.setAttribute('aria-label', 'Toggle source details');
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
    if (!chatMessages) {
        return;
    }

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

// Store references to active polls to prevent duplicates
const activePolls = new Map();

async function askQuestion(question) {
    if (sendButton) {
        sendButton.disabled = true;
        sendButton.textContent = 'Sending…';
    }

    showTypingIndicator();

    try {
        // Submit the question to get a task ID
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

        // Handle session ID updates
        if (data.session_id && data.session_id !== sessionId) {
            sessionId = data.session_id;
            window.localStorage.setItem(SESSION_KEY, sessionId);
        }
        console.log(data)
        // Check if we received a task ID (asynchronous processing)
        if (data.task_id) {
            // Start polling for the task result
            await pollForTaskResult(data.task_id, question);
        } else if (data.history) {
            // Handle legacy synchronous responses
            hideTypingIndicator();
            renderHistory(data.history || []);
            resetInactivityTimer(); // Reset inactivity timer after each response
        } else {
            // Handle unexpected response format
            hideTypingIndicator();
            appendMessage('Sorry, I could not process your request.', 'bot');
        }
    } catch (error) {
        hideTypingIndicator();
        appendMessage('Sorry, I encountered an issue. Please try again.', 'bot');
        console.error(error);
    } finally {
        if (sendButton) {
            sendButton.disabled = false;
            sendButton.textContent = 'Send';
        }
    }
}

async function pollForTaskResult(taskId, question) {
    // Prevent duplicate polling for the same task
    if (activePolls.has(taskId)) {
        return;
    }

    activePolls.set(taskId, true);

    try {
        const TASK_STATUS_ENDPOINT = configuredBaseUrl ?
            `${configuredBaseUrl}/tasks/${taskId}` : `/tasks/${taskId}`;

        // Poll every 1 second until task is complete
        const pollInterval = setInterval(async () => {
            try {
                const response = await fetch(TASK_STATUS_ENDPOINT, {
                    ...sharedFetchOptions,
                    method: 'GET',
                    headers: baseHeaders
                });

                if (!response.ok) {
                    clearInterval(pollInterval);
                    activePolls.delete(taskId);
                    hideTypingIndicator();
                    appendMessage('Sorry, I encountered an issue while processing your request.', 'bot');
                    return;
                }

                const taskData = await response.json();

                // Check task status
                if (taskData.status === 'completed') {
                    clearInterval(pollInterval);
                    activePolls.delete(taskId);
                    hideTypingIndicator();
                    console.log(taskData)
                    // Extract the result from the completed task
                    if (taskData.result) {
                        // Format the response similar to how the old API worked
                        const historyEntry = {
                            question: question,
                            answer: taskData.result.answer || taskData.result.response || 'No answer available.',
                            citations: taskData.result.citations || taskData.result.sources || []
                        };

                        // Display the answer
                        appendMessage(historyEntry.answer, 'bot', historyEntry.citations);
                        resetInactivityTimer(); // Reset inactivity timer after successful response
                    } else {
                        appendMessage('Sorry, I could not process your request.', 'bot');
                    }
                } else if (taskData.status === 'failed') {
                    clearInterval(pollInterval);
                    activePolls.delete(taskId);
                    hideTypingIndicator();
                    const errorMessage = taskData.error || 'Sorry, I encountered an error processing your request.';
                    appendMessage(errorMessage, 'bot');
                    resetInactivityTimer(); // Reset inactivity timer even on error
                }
                // For 'queued' or 'processing' statuses, continue polling
            } catch (error) {
                console.error('Error polling for task result:', error);
                // Continue polling despite individual request failures
                // But still reset the inactivity timer to prevent session ending
                resetInactivityTimer();
            }
        }, 1000); // Poll every 1 second

        // Set a timeout to stop polling after 5 minutes
        setTimeout(() => {
            if (activePolls.has(taskId)) {
                clearInterval(pollInterval);
                activePolls.delete(taskId);
                hideTypingIndicator();
                appendMessage('Sorry, your request is taking longer than expected. Please try again.', 'bot');
                resetInactivityTimer(); // Reset inactivity timer on timeout
            }
        }, 300000); // 5 minutes timeout
    } catch (error) {
        activePolls.delete(taskId);
        hideTypingIndicator();
        appendMessage('Sorry, I encountered an issue setting up your request.', 'bot');
        console.error('Error starting task poll:', error);
        resetInactivityTimer(); // Reset inactivity timer on setup error
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

    // Allow sending message with Enter key (without Shift for new lines)
    chatInput.addEventListener('keydown', event => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            if (chatInput.value.trim()) {
                chatForm.dispatchEvent(new Event('submit'));
            }
        }
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

if (endSessionButton) {
    endSessionButton.addEventListener('click', endSession);
}

// Reset inactivity timer on page load
resetInactivityTimer();

// Reset inactivity timer on mouse movement and keyboard activity
document.addEventListener('mousemove', resetInactivityTimer);
document.addEventListener('keypress', resetInactivityTimer);
document.addEventListener('touchstart', resetInactivityTimer);

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
            // Handle both new async and legacy sync response formats
            if (data.task_id) {
                // For async responses to empty questions, we might not need to do anything
                // as there won't be any meaningful result
                console.log('Async task created for history loading:', data.task_id);
            } else if ((data.history || []).length > 0) {
                // Legacy sync response with history
                renderHistory(data.history);
            }
        }
    } catch (error) {
        console.warn('Unable to pre-load chat history', error);
    }
})();