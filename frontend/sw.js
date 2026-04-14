const CACHE_NAME = 'aninews-v3';
const assetsToCache = [
    '/',
    '/index.html',
    '/detail.html',
    '/style.css',
    '/app.js',
    '/detail.js',
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
            icon: '/icon-192x192.png',
            badge: '/icon-192x192.png',
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
