// BSM Karma Builder website - menu button, contact form and the page view counter
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

  // the contact form: the token comes from the server (the page is a static file), the form shows when it is there
  var form = document.getElementById('contact-form');
  if (form) {
    var status = document.getElementById('form-status');
    var send = form.querySelector('button[type=submit]');
    var say = function (kind, lines) {
      status.className = 'callout ' + kind;
      status.textContent = '';
      lines.forEach(function (line) {
        var p = document.createElement('p');
        p.textContent = line;
        status.appendChild(p);
      });
      status.hidden = false;
    };
    var start = function () {
      send.disabled = true;
      fetch(form.getAttribute('data-token-url'), { cache: 'no-store', credentials: 'omit' })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          if (!data.token) { throw new Error('no token'); }
          form.elements.token.value = data.token;
          form.hidden = false;
          // a robot is quicker than a person: the server ignores a token younger than three seconds
          setTimeout(function () { send.disabled = false; }, 3500);
        })
        .catch(function () { say('warn', ['The form cannot start now. Please try again later.']); });
    };
    var wanted = new URLSearchParams(window.location.search).get('topic');
    Array.prototype.forEach.call(form.elements.topic.options, function (option) {
      if (option.value === wanted) { option.selected = true; }
    });
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      if (!form.checkValidity()) { form.reportValidity(); return; }
      send.disabled = true;
      fetch(form.action, { method: 'POST', body: new FormData(form), credentials: 'omit' })
        .then(function (response) { return response.json().then(function (data) { return { status: response.status, data: data }; }); })
        .then(function (result) {
          if (result.data.ok) {
            say('ok', ['Message sent. Thank you, I will answer as soon as I can.']);
            form.hidden = true;
            return;
          }
          say('warn', result.data.errors || ['The message was not sent.']);
          if (result.status === 400) { start(); } else { send.disabled = false; }
        })
        .catch(function () { say('warn', ['The message was not sent: the server did not answer.']); send.disabled = false; });
    });
    start();
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
