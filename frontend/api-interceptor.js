(function() {
    const originalFetch = window.fetch;
    window.fetch = function(input, init = {}) {
        let url;
        let options = { ...init };

        // Handle both string URLs and Request objects
        if (typeof input === 'string') {
            url = input;
        } else if (input instanceof Request) {
            url = input.url;
            // Merge options from Request object if possible
        } else {
            url = String(input);
        }

        // Automatically prefix relative API calls with the backend base URL
        if (url.startsWith('/api/')) {
            const baseUrl = (window.CONFIG && CONFIG.API_BASE_URL) ? CONFIG.API_BASE_URL : '';
            // Ensure no double slashes
            const cleanBase = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;
            url = cleanBase + url;
            
            // Ensure cookies/sessions are sent across origins (Vercel -> Render)
            options.credentials = 'include';
            
            console.log(`[API Interceptor] Routing to: ${url}`);
        }

        return originalFetch(url, options).catch(err => {
            console.error(`[API Interceptor] Fetch failed for ${url}:`, err);
            throw err;
        });
    };
})();
