window.CONFIG = {
    // Automatically uses empty string (relative /api) for same-origin,
    // and Render backend if running on Vercel preview/production.
    API_BASE_URL: (window.location.hostname.includes('vercel.app')) 
        ? 'https://aninews-system.onrender.com' 
        : ''
};
