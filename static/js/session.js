/* Idle sign-out, the half of it that runs in the browser.

   The server decides. It holds the clock in a signed cookie and ends the
   session on its own, so this file cannot keep anyone signed in past what the
   server allows, and switching JavaScript off does not defeat the timeout —
   it only removes the warning.

   What this adds is honesty about what "idle" means. A request is the only
   thing the server can see, so a person spending fifteen minutes typing a
   project summary looks idle to it and would lose the lot. Here we watch for
   real interaction and tell the server about it, at most once a minute.

   It also gives warning. Losing half-written work to a silent timeout is the
   thing people remember about a site. */
(function () {
  "use strict";

  var root = document.body;
  if (!root || !root.dataset.idleLimit) { return; }

  var LIMIT = parseInt(root.dataset.idleLimit, 10);        // seconds allowed
  var WARN_AT = parseInt(root.dataset.idleWarn, 10) || 90; // warn this early
  var left = parseInt(root.dataset.idleLeft, 10);
  if (!LIMIT || isNaN(left)) { return; }

  var PING_URL = root.dataset.idlePing;
  var SIGNIN_URL = root.dataset.idleSignin;

  // How often a working person's activity is reported. It must be well
  // inside the limit: reporting every 60s against a 60s limit means the
  // server expires the session a moment before the next heartbeat, and
  // somebody typing steadily gets signed out mid-sentence.
  var PING_EVERY = Math.max(15, Math.min(60, Math.floor(LIMIT / 3)));

  var active = false;          // has the person done anything since last ping?
  var lastPing = 0;
  var bar = null;

  /* ------------------------------------------------------------- activity */

  function noteActivity() { active = true; }

  // Deliberately not "scroll". Showing the warning inserts a sticky bar at
  // the top of the page, which shifts the layout and fires a scroll event —
  // so counting scroll as activity meant the warning kept the session alive
  // by appearing, and the timeout could never fire on any page with this
  // script running.
  //
  // Nothing is lost by leaving it out: a person reading scrolls with a wheel,
  // a finger or the keyboard, and all three are listed here.
  ["keydown", "pointerdown", "wheel", "touchstart"].forEach(function (evt) {
    window.addEventListener(evt, noteActivity, { passive: true });
  });

  // A video call runs inside an iframe, so none of its events reach this
  // page. Presenting for half an hour would otherwise look like sitting
  // still. The room page sets this flag while a call is open.
  function inCall() { return root.dataset.idleHold === "1"; }

  /* ---------------------------------------------------------------- clock */

  function fmt(secs) {
    var m = Math.floor(secs / 60), s = secs % 60;
    if (m > 0) { return m + (m === 1 ? " minute" : " minutes"); }
    return s + (s === 1 ? " second" : " seconds");
  }

  function showWarning() {
    if (bar) { return; }
    bar = document.createElement("div");
    bar.className = "idle-bar";
    bar.setAttribute("role", "status");

    var text = document.createElement("span");
    text.className = "idle-bar-text";

    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn--small";
    button.textContent = "Stay signed in";
    button.addEventListener("click", function () {
      active = true;
      ping(true);
    });

    bar.appendChild(text);
    bar.appendChild(button);
    document.body.insertBefore(bar, document.body.firstChild);
    bar.textNode = text;
  }

  function hideWarning() {
    if (bar && bar.parentNode) { bar.parentNode.removeChild(bar); }
    bar = null;
  }

  function signedOut() {
    // Carry where they were, so signing back in returns them to this page
    // rather than to a bare dashboard.
    var here = window.location.pathname + window.location.search;
    window.location = SIGNIN_URL + "?timeout=1&next=" + encodeURIComponent(here);
  }

  /* ----------------------------------------------------------------- ping */

  function ping(keepalive) {
    var url = PING_URL + (keepalive ? "?keepalive=1" : "");
    lastPing = Date.now();

    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Accept": "application/json" }
    }).then(function (res) {
      if (res.status === 401) { signedOut(); return null; }
      return res.json();
    }).then(function (data) {
      if (!data) { return; }
      if (!data.signed_in) { signedOut(); return; }
      left = data.seconds_left;
      if (left > WARN_AT) { hideWarning(); }
    }).catch(function () {
      /* Offline or the server is down. The local countdown carries on; the
         next successful ping corrects it. Never sign someone out over a
         failed request — that would log people out of a working session
         every time the network hiccuped. */
    });
  }

  /* ---------------------------------------------------------------- tick */

  setInterval(function () {
    left -= 1;

    var working = active || inCall();
    var sincePing = Date.now() - lastPing;

    // Report activity on a steady cadence while the person is working.
    if (working && sincePing > PING_EVERY * 1000) {
      active = false;
      ping(true);
      return;
    }

    // Getting close to the limit while still working: refresh now rather
    // than show a warning to somebody who is plainly here. Rate-limited so a
    // long session does not turn into a request per second.
    if (working && left <= WARN_AT + 10 && sincePing > 5000) {
      active = false;
      ping(true);
      return;
    }

    if (left <= 0) {
      // Ask the server rather than trusting this countdown, which drifts
      // when a tab is backgrounded and browsers throttle timers.
      ping(false);
      left = 10;
      return;
    }

    if (left <= WARN_AT) {
      showWarning();
      bar.textNode.textContent =
        "You will be signed out in " + fmt(left) + " unless you carry on.";
    } else {
      hideWarning();
    }
  }, 1000);

  // Coming back to a backgrounded tab, ask the server what is actually left
  // rather than trusting a timer the browser may have throttled.
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) { ping(false); }
  });
})();
