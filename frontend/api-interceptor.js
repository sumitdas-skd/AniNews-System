(function() {
    const originalFetch = window.fetch;
    window.fetch = function(input, init = {}) {
        let url;
        let options = { ...init };

        if (typeof input === 'string') {
            url = input;
        } else if (input instanceof Request) {
            url = input.url;
            // Ensure we copy other Request properties if needed, 
            // but for this app, simple URL modification is usually enough.
        } else {
            url = String(input);
        }

        // SMART ROUTING: Only prefix with Render if we are NOT on localhost and have a baseUrl
        if (url.startsWith('/api/')) {
            const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
            const config = window.CONFIG || {};
            const baseUrl = (config.API_BASE_URL && !isLocal) ? config.API_BASE_URL : '';
            
            if (baseUrl) {
                const cleanBase = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;
                url = cleanBase + url;
                
                // Credentials needed for cross-domain (Vercel -> Render)
                if (!isLocal) {
                    options.credentials = 'include';
                }
            }
        }

        return originalFetch(url, options).catch(err => {
            console.error(`[API Interceptor] Fetch failed for ${url}:`, err);
            throw err;
        });
    };
})();
