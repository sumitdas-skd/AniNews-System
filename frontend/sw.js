const CACHE_NAME = 'aninews-v4';
const assetsToCache = [
    '/',
    '/index.html',
    '/detail.html',
    '/login.html',
    '/style.css',
    '/login.css',
    '/config.js',
    '/api-interceptor.js',
    '/app.js',
    '/detail.js',
    '/icon-512.png',
    'https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap'
];

self.addEventListener('install', (event) => {
    self.skipWaiting();
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(assetsToCache);
        })
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cache) => {
                    if (cache !== CACHE_NAME) {
                        return caches.delete(cache);
                    }
                })
            );
        })
    );
});

self.addEventListener('fetch', (event) => {
    // Network first strategy
    event.respondWith(
        fetch(event.request).catch(() => {
            return caches.match(event.request);
        })
    );
});

self.addEventListener('push', function(event) {
    if (event.data) {
        let data = { title: 'AniNews', body: 'New update available!', url: '/' };
        try {
            data = event.data.json();
        } catch (e) {
            console.error('Failed to parse push data', e);
        }

        const options = {
            body: data.body,
            icon: '/icon-512.png',
            badge: '/icon-512.png',
            data: { url: data.url }
        };

        event.waitUntil(
            self.registration.showNotification(data.title, options)
        );
    }
});

self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    if (event.notification.data && event.notification.data.url) {
        event.waitUntil(
            clients.openWindow(event.notification.data.url)
        );
    }
});
