(function () {
    // Prevent multiple instantiations
    console.log("HI")
    const alreadyBootstrapped = window.__chromaFaqBotEmbedded;
    if (alreadyBootstrapped) {
        return;
    }
    window.__chromaFaqBotEmbedded = true;

    // Get script element and configuration
    const scriptElement = document.currentScript;
    const declaredBaseUrl = scriptElement && scriptElement.dataset ? scriptElement.dataset.baseUrl : '';

    // Normalize base URL and determine if we should use HTTPS
    let normalizedBaseUrl = (declaredBaseUrl || (scriptElement ? new URL(scriptElement.src).origin : '') || '').replace(/\/$/, '');

    // If the script is loaded over HTTPS, try to use HTTPS for the iframe as well
    if (!declaredBaseUrl && scriptElement && scriptElement.src) {
        try {
            const scriptUrl = new URL(scriptElement.src);
            if (scriptUrl.protocol === 'https:') {
                // If the script is loaded over HTTPS, construct an HTTPS URL for the backend
                const hostname = scriptUrl.hostname;
                const httpsPort = '8443'; // Default HTTPS port for our service
                normalizedBaseUrl = `https://${hostname}:${httpsPort}`;
            }
        } catch (e) {
            // If URL parsing fails, fall back to the original logic
        }
    }

    // Create the chat widget container using iframe for better isolation
    function createChatWidget() {
        // Create toggle button
        const toggleButton = document.createElement('button');
        toggleButton.className = 'chat-toggle';
        toggleButton.setAttribute('aria-label', 'Open support chat');
        toggleButton.innerHTML = '<span class="chat-toggle__icon">💬</span>';
        toggleButton.style.position = 'fixed';
        toggleButton.style.right = '24px';
        toggleButton.style.bottom = '24px';
        toggleButton.style.width = '60px';
        toggleButton.style.height = '60px';
        toggleButton.style.borderRadius = '50%';
        toggleButton.style.border = 'none';
        toggleButton.style.background = '#1f6feb';
        toggleButton.style.color = '#fff';
        toggleButton.style.fontSize = '1.5rem';
        toggleButton.style.display = 'flex';
        toggleButton.style.alignItems = 'center';
        toggleButton.style.justifyContent = 'center';
        toggleButton.style.boxShadow = '0 18px 45px rgba(31, 111, 235, 0.45)';
        toggleButton.style.cursor = 'pointer';
        toggleButton.style.zIndex = '1000';
        toggleButton.style.transition = 'transform 0.2s ease, box-shadow 0.2s ease';

        // Create iframe for the chat widget
        const iframe = document.createElement('iframe');
        iframe.id = 'chroma-faq-bot-iframe';
        iframe.style.position = 'fixed';
        iframe.style.right = '24px';
        iframe.style.bottom = '100px';
        iframe.style.width = '400px';
        iframe.style.height = '600px';
        iframe.style.border = 'none';
        iframe.style.borderRadius = '12px';
        iframe.style.boxShadow = '0 35px 80px rgba(15, 23, 42, 0.55)';
        iframe.style.display = 'none';
        iframe.style.zIndex = '10000';

        // Set iframe source
        const baseUrl = normalizedBaseUrl || (scriptElement ? new URL(scriptElement.src).origin : window.location.origin);
        iframe.src = `${baseUrl}/embed`;

        // Add to document body
        document.body.appendChild(toggleButton);
        document.body.appendChild(iframe);

        // Add event listeners
        toggleButton.addEventListener('click', () => {
            if (iframe.style.display === 'none') {
                iframe.style.display = 'block';
                toggleButton.innerHTML = '<span class="chat-toggle__icon">✕</span>';
            } else {
                iframe.style.display = 'none';
                toggleButton.innerHTML = '<span class="chat-toggle__icon">💬</span>';
            }
        });
    }

    // Initialize the widget when the DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', createChatWidget);
    } else {
        createChatWidget();
    }
})();