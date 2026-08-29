/**
 * Chrome on Android remembers the "Desktop site" menu checkbox per domain,
 * and the installed PWA inherits it: Chrome then spoofs a desktop UA and
 * ignores the viewport meta, so the layout viewport becomes ~980px and every
 * width-based breakpoint reads "desktop" on a phone. There is no site-side
 * opt-out (no meta/header/manifest field), so when the app runs standalone
 * on a touch device with that anomaly we simulate mobile instead:
 *  - zoom <html> so content lays out at the true device width
 *  - set data-force-mobile on <html> for CSS overrides
 *  - expose isForcedMobile() so useIsMobile() can force JS breakpoints
 *
 * Only the installed (standalone) app is corrected — browser tabs keep
 * Chrome's normal Desktop-site behavior, which is what the user asked for.
 *
 * Append ?vpdebug to the URL to render an overlay with the raw signals
 * (useful because what Chrome spoofs in Desktop-site mode varies by version).
 */

const state = { forced: false, zoom: 1, signals: null }

function matches(query) {
  try {
    return window.matchMedia(query).matches
  } catch {
    return false
  }
}

function readSignals() {
  const vv = window.visualViewport
  return {
    standalone: matches('(display-mode: standalone)'),
    coarsePointer: matches('(pointer: coarse)'),
    touchPoints: navigator.maxTouchPoints || 0,
    innerWidth: window.innerWidth,
    screenWidth: (window.screen && window.screen.width) || 0,
    screenHeight: (window.screen && window.screen.height) || 0,
    vvWidth: vv ? Math.round(vv.width) : null,
    vvScale: vv ? Math.round(vv.scale * 100) / 100 : null,
    ua: navigator.userAgent
  }
}

function applyZoom() {
  const s = readSignals()
  // screenWidth tracks the current orientation on Android, so it is the
  // preferred target; visualViewport is the fallback when it gets spoofed.
  const anomalyScreen = s.screenWidth > 0 && s.innerWidth > s.screenWidth * 1.3
  let target = anomalyScreen
    ? s.screenWidth
    : s.vvWidth && s.vvScale
      ? Math.round(s.vvWidth * s.vvScale)
      : 412
  target = Math.min(Math.max(target, 320), 480)
  state.zoom = s.innerWidth / target
  document.documentElement.style.zoom = String(state.zoom)
}

export function initDesktopSiteGuard() {
  if (typeof window === 'undefined' || !window.matchMedia) return
  const s = readSignals()
  state.signals = s

  const touch =
    s.coarsePointer || s.touchPoints > 0 || 'ontouchstart' in window
  const anomaly =
    (s.screenWidth > 0 && s.innerWidth > s.screenWidth * 1.3) ||
    (s.vvScale != null && s.vvScale < 0.75)

  // A correctly-viewported phone never reports a ~980px layout viewport,
  // so innerWidth >= 800 keeps real tablets/desktops out of forced mode.
  // screenWidth < 1024 excludes touchscreen laptops/desktops, where browser
  // zoom can inflate innerWidth past screen.width and fake the anomaly —
  // zooming those would be far worse than missing an odd Chrome version here.
  const phoneSizedScreen = s.screenWidth > 0 && s.screenWidth < 1024
  if (s.standalone && touch && phoneSizedScreen && s.innerWidth >= 800 && anomaly) {
    state.forced = true
    document.documentElement.setAttribute('data-force-mobile', '')
    applyZoom()
    window.addEventListener('resize', () => {
      if (state.forced) applyZoom()
    })
  }

  // The installed PWA always launches at start_url, so ?vpdebug can't be
  // typed there — persist the flag from a browser tab (same origin storage)
  // and the overlay shows up inside the installed app too. ?vpdebug=off clears.
  let debug = /[?&]vpdebug/.test(window.location.search)
  try {
    if (/[?&]vpdebug=off/.test(window.location.search)) {
      localStorage.removeItem('vpdebug')
      debug = false
    } else if (debug) {
      localStorage.setItem('vpdebug', '1')
    } else {
      debug = localStorage.getItem('vpdebug') === '1'
    }
  } catch {
    /* storage unavailable — query-param-only debug */
  }
  if (debug) {
    renderDebugOverlay()
  }
}

export function isForcedMobile() {
  return state.forced
}

function renderDebugOverlay() {
  const div = document.createElement('div')
  div.style.cssText =
    'position:fixed;bottom:0;left:0;right:0;z-index:99999;' +
    'background:rgba(255,255,255,0.95);color:#222;font:11px/1.5 monospace;' +
    'padding:8px;border-top:2px solid #5b7c99;white-space:pre-wrap;word-break:break-all'
  const dump = () =>
    JSON.stringify(
      { forced: state.forced, zoom: Math.round(state.zoom * 100) / 100, ...readSignals() },
      null,
      1
    )
  div.textContent = dump()
  div.onclick = () => {
    div.textContent = dump()
  }
  const attach = () => document.body.appendChild(div)
  if (document.body) attach()
  else document.addEventListener('DOMContentLoaded', attach)
}
