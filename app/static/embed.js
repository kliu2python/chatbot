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
                <span class="chat-toggle__icon">💬</span>
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
