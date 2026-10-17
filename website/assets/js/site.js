// BSM Karma Builder website - menu button and the page view counter
// Benoît Saint-Moulin | www.bsm3d.com | version 1.0.0

(function () {
  var button = document.querySelector('.menu-btn');
  var menu = document.getElementById('menu');
  if (button && menu) {
    button.addEventListener('click', function () {
      var open = menu.classList.toggle('open');
      button.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }

  // the counter: not for a browser that asks not to be followed, and nothing but the page and the referrer host is sent
  var dnt = navigator.doNotTrack === '1' || window.doNotTrack === '1' || navigator.msDoNotTrack === '1' || navigator.globalPrivacyControl === true;
  var page = document.body.getAttribute('data-page');
  if (dnt || !page || page === '404') return;
  var body = JSON.stringify({ p: page, r: document.referrer || '' });
  if (navigator.sendBeacon) {
    navigator.sendBeacon('/hit.php', new Blob([body], { type: 'text/plain' }));
  } else if (window.fetch) {
    fetch('/hit.php', { method: 'POST', body: body, keepalive: true, credentials: 'omit' });
  }
})();
