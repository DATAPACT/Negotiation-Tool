(function () {
    function isOriginTrusted(origin) {
        return (window.TRUSTED_ORIGINS || []).some(function (entry) {
            if (entry.indexOf('*') === -1) {
                return origin === entry.replace(/\/$/, '');
            }
            // e.g. "https://*.dp.assistcloud.net"
            var parts = entry.split('*');
            return origin.startsWith(parts[0]) && origin.endsWith(parts[1]);
        });
    }

    var ssoInProgress = false;
    var tokenReceived = false;
    var parentOrigin = document.referrer ? new URL(document.referrer).origin : '*';

    function notifyParentError(message) {
        if (window.parent !== window) {
            window.parent.postMessage({ type: 'SSO_ERROR', message: message }, parentOrigin);
        }
    }

    function handleSsoToken(token) {
        if (ssoInProgress) return;
        ssoInProgress = true;
        tokenReceived = true;

        fetch('/negotiation/sso-login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: token }),
            credentials: 'same-origin',
        })
            .then(function (res) {
                return res.json().then(function (data) {
                    return { ok: res.ok, data: data };
                });
            })
            .then(function (result) {
                if (!result.ok) {
                    console.error('[SSO] Login failed:', result.data && result.data.error);
                    notifyParentError(result.data && result.data.error || 'Login failed');
                    ssoInProgress = false;
                    return;
                }
                if (result.data && result.data.redirect_url) {
                    var current = window.location.pathname;
                    var target = new URL(result.data.redirect_url, window.location.origin).pathname;
                    if (current !== target) {
                        window.location.href = result.data.redirect_url;
                    }
                }
            })
            .catch(function (err) {
                console.error('[SSO] Network error:', err);
                notifyParentError('Network error');
                ssoInProgress = false;
            });
    }

    window.addEventListener('message', function (event) {
        if (!isOriginTrusted(event.origin)) {
            return;
        }

        // INJECT_CSS: allows the trusted parent frame to apply custom styles
        if (event.data && event.data.type === 'INJECT_CSS' && typeof event.data.css === 'string') {
            var style = document.createElement('style');
            style.textContent = event.data.css;
            document.head.appendChild(style);
            return;
        }

        if (!event.data || event.data.type !== 'SSO_TOKEN' || !event.data.token) {
            return;
        }

        handleSsoToken(event.data.token);
    });

    // Signal to the parent that this page is ready.
    // Retries every 100ms for up to 3s in case the parent mounts after the first signal.
    // Skip entirely if already authenticated.
    if (window.parent !== window && !window.SSO_AUTHENTICATED) {
        window.parent.postMessage({ type: 'IFRAME_READY' }, parentOrigin);

        var retryCount = 0;
        var retryInterval = setInterval(function () {
            if (tokenReceived || retryCount >= 30) {
                clearInterval(retryInterval);
                return;
            }
            window.parent.postMessage({ type: 'IFRAME_READY' }, parentOrigin);
            retryCount++;
        }, 100);
    }
})();