(function() {
    const originalFetch = window.fetch;
    window.fetch = function(input, init = {}) {
        let url;
        let options = { ...init };

        if (typeof input === 'string') {
            url = input;
        } else if (input instanceof Request) {
            url = input.url;
        } else {
            url = String(input);
        }

        // SMART ROUTING: Only prefix with Render if we are NOT on localhost
        if (url.startsWith('/api/')) {
            const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
            const baseUrl = (window.CONFIG && CONFIG.API_BASE_URL && !isLocal) ? CONFIG.API_BASE_URL : '';
            
            const cleanBase = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;
            url = cleanBase + url;
            
            // Credentials needed for cross-domain (Vercel -> Render)
            if (!isLocal) {
                options.credentials = 'include';
            }
        }

        return originalFetch(url, options).catch(err => {
            console.error(`[API Interceptor] Fetch failed:`, err);
            throw err;
        });
    };
})();
