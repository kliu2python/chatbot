(function () {
    const alreadyBootstrapped = window.__fortiIdentityChatEmbedded;
    if (alreadyBootstrapped) {
        return;
    }
    window.__fortiIdentityChatEmbedded = true;

    const scriptElement = document.currentScript;
    const declaredBaseUrl = scriptElement && scriptElement.dataset ? scriptElement.dataset.baseUrl : '';
    const normalizedBaseUrl = (declaredBaseUrl || (scriptElement ? new URL(scriptElement.src).origin : '') || '').replace(/\/$/, '');

    window.FortiIdentityChatConfig = window.FortiIdentityChatConfig || {};
    if (normalizedBaseUrl && !window.FortiIdentityChatConfig.baseUrl) {
        window.FortiIdentityChatConfig.baseUrl = normalizedBaseUrl;
    }

    if (scriptElement && scriptElement.dataset && scriptElement.dataset.sessionKey) {
        window.FortiIdentityChatConfig.sessionStorageKey = scriptElement.dataset.sessionKey;
    }

    if (scriptElement && scriptElement.dataset && scriptElement.dataset.withCredentials === 'true') {
        const existingFetchOptions = window.FortiIdentityChatConfig.fetchOptions || {};
        window.FortiIdentityChatConfig.fetchOptions = {
            ...existingFetchOptions,
            credentials: 'include'
        };
    }

    function ensureStylesheet() {
        if (document.querySelector('link[data-fortiidentity-chat="styles"]')) {
            return;
        }

        const stylesheet = document.createElement('link');
        stylesheet.rel = 'stylesheet';
        stylesheet.href = `${window.FortiIdentityChatConfig.baseUrl || ''}/static/styles.css`;
        stylesheet.setAttribute('data-fortiidentity-chat', 'styles');
        document.head.appendChild(stylesheet);
    }

    function injectMarkup() {
        if (document.querySelector('[data-fortiidentity-chat="root"]')) {
            return;
        }

        const wrapper = document.createElement('div');
        wrapper.className = 'fortiidentity-chat';
        wrapper.setAttribute('data-fortiidentity-chat', 'root');
        wrapper.innerHTML = `
            <button id="chatToggle" class="chat-toggle" aria-label="Open support chat">
                <span class="chat-toggle__icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" focusable="false" role="img">
                        <path d="M4 4.75C4 3.784 4.784 3 5.75 3h12.5C19.216 3 20 3.784 20 4.75v8.5c0 .966-.784 1.75-1.75 1.75H8.59l-3.142 2.514A.75.75 0 0 1 4 17.95zm1.75-.25a.25.25 0 0 0-.25.25v12.105l2.59-2.072a.75.75 0 0 1 .467-.163h10.693a.25.25 0 0 0 .25-.25v-9.62a.25.25 0 0 0-.25-.25z" />
                    </svg>
                </span>
            </button>
            <section id="chatWidget" class="chat-widget" aria-live="polite" aria-expanded="false">
                <header class="chat-widget__header">
                    <div>
                        <h2>FortiIdentity Cloud Support</h2>
                        <p class="chat-widget__subtitle">Chat with the virtual support engineer</p>
                    </div>
                    <button id="closeChat" class="chat-widget__close" aria-label="Close chat">×</button>
                </header>
                <div id="chatMessages" class="chat-widget__messages"></div>
                <form id="chatForm" class="chat-widget__form" autocomplete="off">
                    <label class="sr-only" for="chatInput">Type your question</label>
                    <textarea id="chatInput" class="chat-widget__input" rows="2" placeholder="Ask about MFA, user sources, or configuration..." required></textarea>
                    <div class="chat-widget__actions">
                        <button type="submit" id="sendButton" class="chat-widget__send">Send</button>
                    </div>
                </form>
            </section>
            <button id="openChatFromIntro" type="button" class="sr-only">Open support chat</button>
        `;

        document.body.appendChild(wrapper);
    }

    function injectChatScript() {
        if (document.querySelector('script[data-fortiidentity-chat="runtime"]')) {
            return;
        }

        const script = document.createElement('script');
        script.src = `${window.FortiIdentityChatConfig.baseUrl || ''}/static/chat.js`;
        script.defer = false;
        script.async = false;
        script.setAttribute('data-fortiidentity-chat', 'runtime');
        document.head.appendChild(script);
    }

    function bootstrap() {
        ensureStylesheet();
        injectMarkup();
        injectChatScript();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootstrap);
    } else {
        bootstrap();
    }
})();
