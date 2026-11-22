"use client";

import { useEffect, useRef } from "react";
import { loadJSON } from "@/lib/data";

// The hero figure: a dotted globe spins up and streams down into the drive, the Wi-Fi drops, and the drive lights up what it holds.
// Drawn on a canvas each frame from a 12-second timeline, so it can pause, hold a still frame, and stop when off screen.
// It runs outside React: start() owns the canvas and the button's aria-pressed, and returns the function that stops it.
export default function Hero() {
  const fig = useRef(null);
  useEffect(() => start(fig.current), []);
  return (
    <figure className="fig viz" ref={fig}>
      <canvas
        role="img"
        aria-label="A dotted globe spins up and streams into a drive until the drive holds the whole kit. Then the Wi-Fi goes off, the globe goes dark, and the drive lights up what it holds: Wikipedia, AI models, maps and guides."
      />
      <button type="button" className="viz-toggle" aria-label="Pause the animation" aria-pressed="false">
        <span className="viz-state" aria-hidden="true">
          <svg width="10" height="10" viewBox="0 0 10 10">
            <path d="M1 0L10 5L1 10z" fill="currentColor" />
          </svg>
          PLAY
        </span>
      </button>
    </figure>
  );
}

function start(fig) {
  if (!window.ResizeObserver) return;
  var stopped = false;
  var cv = fig.querySelector("canvas"),
    ctx = cv.getContext("2d"),
    btn = fig.querySelector(".viz-toggle");
  var INK = "#1C1F1A",
    SIG = "#D9531E",
    SIGT = "#9A3A10",
    OLIVE = "#4A5A2A",
    PAPER = "#F3F0E6",
    D = Math.PI / 180,
    TAU = 2 * Math.PI;
  var MONO = getComputedStyle(fig).getPropertyValue("--mono").trim() || "ui-monospace, monospace"; // next/font's name for Plex Mono

  // Land as a 180x90 bitmap of 2-degree cells, rows from the north, bits low first (Natural Earth 110m land, public domain).
  var bits = Uint8Array.from(
    atob(
      "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAOAfAP8DAAAAAAAAAAAAAAAAAAAAAADo//z//wcAAAAAAAACAAAAAAAAAAAAhvvw//8PAPABAAAAwAMAAAAAAAAAwADkw////wEABAAAAABgAAAAAAAAAADAUT8A/v8PAAAAAAwA/j8AuAEAAAAAcBHtDcD/fwAAAAAwAPz/fwMAABCAAQD5w/wD8P8FAAAMAIL7//////9/AP//////////////B/D/SAAAAAAAQID//////////////x8AKAAEAAAAAAAA8///////////////YCgAAAAAAAAAAADw/////wEs4AEAAHz+////////////gL////8HeAAcAADg5///////////9ADgAf7/f4AnAAAAAH78////////H0QAAAiA//8f8AcAAIBB4////////38ADwAQAOD//5//AQAAHAT/////////A3AAAAAA/v//+T8AAGDz//////////8DAQAAAMD/////AwAAsP//////////LwAAAAAA6P///2IAAAD+//////////8CAAAAAAD///8/CAAA4P//////////JwAAAAAA8P///wYAAAD+/unz/////z8AAAAAAAD///8HAAAA/pgPPP//////MQAAAAAA8P//PwAAAMBD9v7n/////wcBAAAAAAD///8AAAAAPkD7f/7///8hEAAAAAAA4P//DwAAAIDhAv/n////f8YAAAAAAAD8//8AAAAA+AdE//////8jDwAAAAAAgP//AwAAAMD/APD/////PxgAAAAAAADw/x8AAAAA/n/v//////8HAAAAAAAAAPwDAgAAAOD////7////fwAAAAAAAACgHyAAAACA//9/f/7///8DAAAAAAAAAPQBAAAAAPj//+cv+P//PwAAAAAAAAAAHjAAAADA/////g/+//8EAAAAAAAAAOBhCAAAAP7//99/4D//AAAAAAAAAAAAPAMEAADA////+Qf84BcAAAAAAAAAAAA/AAAAAPz//58fgAf+QAAAAAAAAAAAAA8AAADg////ewA4gA8EAAAAAAAAAADAAAAAAPz//38BgAP4QQAAAAAAAAAAAAgPAADA////zwAwgAwQAAAAAAAAAAAA9Q8AAPj///8HAAVIAAAAAAAAAAAAAID/AQAA////fwBAAAAQAAAAAAAAAAAA+P8AAGDh//8DAAA0GAAAAAAAAAAAAID/HwAAAPj/HwAAgMIBAAAAAAAAAAAA/P8BAACA//8AAAAYXgAAAAAAAAAAAMD/fwAAAPz/BwAAAOOBAQAAAAAAAAAA/P8/AACA/z8AAABgbtQBAAAAAAAAAOD//w8AAPD/AwAAAAQIeAAAAAAAAAAA/P//AQAA/z8AAACAA4APAQAAAAAAAID//w8AAPD/AwAAAAARsEAAAAAAAAAA+P9/AAAA/j8AAAAAAAAAAAAAAAAAAAD//wcAAPD/QwAAAACAIwAAAAAAAAAA8P9/AAAA/z8EAAAAAD8GIAAAAAAAAAD8/wMAAPD/cQAAAAD4ZwAAAAAAAAAAgP8/AAAA/w8HAAAAgP8HAAAAAAAAAAD4/wMAAOD/MAAAAAD//wEBAAAAAAAAgP8PAAAA/g8DAAAA+P8fAAAAAAAAAAD4PwAAAOB/EAAAAID//wMAAAAAAAAAgP8DAAAA/AMAAAAA+P9/AAAAAAAAAAD8HwAAAMA/AAAAAID//wcAAAAAAAAAwP8BAAAA+AEAAAAA8P9/AAAAAAAAAAD8DwAAAIAPAAAAAAAP/gMAAAAAAAAAwB8AAAAAAAAAAAAAEIAfAAEAAAAAAAD+AwAAAAAAAAAAAAAA8AEgAAAAAAAA4AcAAAAAAAAAAAAAAAAAAAYAAAAAAABeAAAAAAAAAAAAAAAAwAAwAAAAAAAAwAMAAAAAAAAAAAAAAAAIgAEAAAAAAAAeAAAAAAAAAAAAAAAAAAAMAAAAAAAA4AEAAAAAAAAAAAAAAAAAAAAAAAAAAAAPAAAAAAAAAAABAAAAAAAAAAAAAAAAcAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAOAAAAAAAAAAAAAAAAAAAAAAAAAAAAwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAMAAAAAAAB4AEDwn/8HAAAAAAAAAAAwAAAAAACA/P/h/////w8AAAAAAAAAwAcAAAD4////z///////PwAAAAAAHALwAACA//////////////8HAADw/y///wMAAP7/////////////HwAA+P///38AAID///////////////8AAPL/////BwAO////////////////DwAA8P////8HEPD//////////////z8AAOD/////////////////////////HwDgPwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    ),
    function (c) {
      return c.charCodeAt(0);
    },
  );
  function isLand(la, lo) {
    var i = Math.floor((90 - la) / 2) * 180 + (Math.floor((lo + 180) / 2) % 180);
    return (bits[i >> 3] >> (i & 7)) & 1;
  }
  function sample(step, keep) {
    var out = [];
    for (var la = -55; la < 84; la += step) {
      var n = Math.round((360 / step) * Math.cos(la * D));
      for (var k = 0; k < n; k++) {
        var lo = -180 + ((k + 0.5) * 360) / n;
        if (isLand(la, lo) !== keep) continue;
        var a = la * D,
          b = lo * D;
        out.push({ lo: b, X: Math.cos(a) * Math.sin(b), Y: Math.sin(a), Z: Math.cos(a) * Math.cos(b) });
      }
    }
    return out;
  }
  var land = sample(2, 1),
    sea = sample(3, 0),
    N = land.length;

  // What fills the drive: the recommended kit, in GB. Replaced by the live sizes from sources.json once it loads.
  var PARTS = [
      ["WIKIPEDIA", 127],
      ["AI MODELS", 56],
      ["MAPS", 17],
      ["GUIDES", 62],
    ],
    TOTAL = 262;
  loadJSON("sources.json")
    .then(function (data) {
      if (stopped) return;
      var gb = [0, 0, 0, 0];
      data.sources.forEach(function (s) {
        if (s.presets.indexOf("recommended") < 0 || !s.bytes) return;
        gb[s.id === "wikipedia_en_all_maxi" ? 0 : s.group === "AI models" ? 1 : s.group === "Maps" ? 2 : 3] +=
          s.bytes / 1e9;
      });
      if (gb[0] && gb[1]) {
        PARTS.forEach(function (p, i) {
          p[1] = Math.round(gb[i]);
        });
        TOTAL = PARTS.reduce(function (t, p) {
          return t + p[1];
        }, 0);
        frame();
      }
    })
    .catch(function () {});

  // Timeline, in seconds of the loop
  var LOOP = 12,
    T_PACK = 2.2,
    T_OUT = 5.9,
    T_SAY = 6.6,
    T_RESET = 10.8,
    FLY = 0.9;
  var W0 = 22 * D,
    W1 = 150 * D,
    TILT = 16 * D,
    ct = Math.cos(TILT),
    st = Math.sin(TILT);
  function omega(t) {
    // a slow spin, a fast one while it unspools, then slow again
    if (t < T_PACK) return W0;
    if (t < T_PACK + 0.5) return W0 + (W1 - W0) * ease((t - T_PACK) / 0.5);
    if (t < T_OUT - 0.4) return W1;
    if (t < T_OUT + 0.6) return W1 + (W0 - W1) * ease((t - T_OUT + 0.4) / 1);
    return W0;
  }
  var HZ = 240,
    TH = new Float64Array(LOOP * HZ + 2);
  for (var i = 1; i < TH.length; i++) TH[i] = TH[i - 1] + omega((i - 0.5) / HZ) / HZ;
  function theta(t) {
    var f = t * HZ,
      j = Math.floor(f);
    return TH[j] + (TH[j + 1] - TH[j]) * (f - j);
  }
  function timeAt(r) {
    var lo = 0,
      hi = TH.length - 1;
    while (hi - lo > 1) {
      var m = (lo + hi) >> 1;
      if (TH[m] < r) lo = m;
      else hi = m;
    }
    return hi / HZ;
  }

  // One composition, the globe over a wide drive that fills from the left, scaled to the canvas.
  // Text and the Wi-Fi icon grow back to a readable size when the canvas is small (ts).
  var L = {
      W: 440,
      H: 500,
      g: { x: 220, y: 172, r: 124 },
      peel: 70 * D,
      d: { x: 40, y: 346, w: 360, h: 112, gx: 56, gy: 380, gw: 328, gh: 66 },
      port: { x: 220, y: 340, dx: 0, dy: 1 },
      wifi: { x: 24, y: 30 },
    },
    slots = [],
    dpr = 1,
    scale = 1,
    ts = 1;
  (function () {
    var d = L.d,
      s = Math.sqrt((d.gw * d.gh) / N),
      a,
      b;
    for (; ; s *= 0.99) {
      a = Math.floor(d.gw / s);
      b = Math.floor(d.gh / s);
      if (a * b >= N) break;
    }
    d.s = s;
    d.cols = a;
    d.rows = b;
    d.ox = d.gx + (d.gw - (a - 1) * s) / 2;
    d.oy = d.gy + (d.gh - (b - 1) * s) / 2;
    for (var k = 0; k < N; k++) slots.push({ x: d.ox + Math.floor(k / b) * s, y: d.oy + (k % b) * s });
  })();
  function layout() {
    var w = cv.getBoundingClientRect().width || L.W;
    cv.style.aspectRatio = L.W + " / " + L.H;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    scale = w / L.W;
    ts = Math.min(1.7, Math.max(1, 0.95 / scale));
    cv.width = Math.round(w * dpr);
    cv.height = Math.round(((w * L.H) / L.W) * dpr);
  }

  function clamp(u) {
    return u < 0 ? 0 : u > 1 ? 1 : u;
  }
  function ease(u) {
    u = clamp(u);
    return u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2;
  }
  function proj(p, rot, o) {
    var c = Math.cos(rot),
      s = Math.sin(rot),
      X = p.X * c + p.Z * s,
      Z = p.Z * c - p.X * s,
      g = L.g;
    o.x = g.x + g.r * X;
    o.y = g.y - g.r * (ct * p.Y - st * Z);
    o.z = st * p.Y + ct * Z;
    return o;
  }

  // Once per loop: when each land dot reaches the peel line, where it leaves from, and which slot it fills.
  var dep = new Float64Array(N),
    from = [],
    loopNo = -1,
    base = 0;
  function plan(n) {
    loopNo = n;
    base = n * TH[TH.length - 1];
    var r0 = base + theta(T_PACK),
      tmp = {},
      order = [];
    for (var i = 0; i < N; i++) {
      var need = (((L.peel - land[i].lo - r0) % TAU) + 2 * TAU) % TAU;
      dep[i] = timeAt(theta(T_PACK) + need);
      order.push(i);
    }
    order.sort(function (a, b) {
      return dep[a] - dep[b];
    });
    from = new Array(N);
    order.forEach(function (i, k) {
      var p = proj(land[i], base + theta(dep[i]), tmp);
      from[i] = { x: p.x, y: p.y, slot: k, j: (((i * 0.618034) % 1) - 0.5) * 7 }; // fixed per dot: a resize while paused redraws the same frame
    });
  }

  // Arcs between places while online
  var arcs = [],
    nextArc = 0,
    arcLoop = -1;
  function spawnArc(t, rot) {
    var tmp = {},
      a,
      b,
      d,
      n = 0;
    do a = land[(Math.random() * N) | 0];
    while (proj(a, rot, tmp).z < 0.45 && ++n < 40);
    n = 0;
    do {
      b = land[(Math.random() * N) | 0];
      d = Math.acos(Math.max(-1, Math.min(1, a.X * b.X + a.Y * b.Y + a.Z * b.Z)));
    } while ((d < 18 * D || d > 65 * D || proj(b, rot, tmp).z < 0.3) && ++n < 60);
    arcs.push({ a: a, b: b, d: d, t: t });
  }
  function slerp(A, s, h) {
    var sd = Math.sin(A.d),
      k1 = (Math.sin((1 - s) * A.d) / sd) * h,
      k2 = (Math.sin(s * A.d) / sd) * h;
    return { X: A.a.X * k1 + A.b.X * k2, Y: A.a.Y * k1 + A.b.Y * k2, Z: A.a.Z * k1 + A.b.Z * k2 };
  }

  function dots(list, r) {
    ctx.beginPath();
    for (var i = 0; i < list.length; i += 2) {
      ctx.moveTo(list[i] + r, list[i + 1]);
      ctx.arc(list[i], list[i + 1], r, 0, TAU);
    }
    ctx.fill();
  }
  function text(s, x, y, size, color, weight, align) {
    ctx.font = (weight || 500) + " " + size * ts + "px " + MONO;
    ctx.fillStyle = color;
    ctx.textAlign = align || "left";
    ctx.fillText(s, x, y);
  }
  function rrect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }
  function line(x1, y1, x2, y2) {
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  }
  function wifi(x, y, bars, off, k) {
    ctx.lineCap = "round";
    ctx.lineWidth = 1.7 * k;
    ctx.strokeStyle = INK;
    ctx.fillStyle = INK;
    for (var i = 0; i < 3; i++) {
      ctx.globalAlpha = i < bars ? 1 : 0.18;
      ctx.beginPath();
      ctx.arc(x, y, (4 + i * 4) * k, -Math.PI * 0.78, -Math.PI * 0.22);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    ctx.beginPath();
    ctx.arc(x, y, 1.7 * k, 0, TAU);
    ctx.fill();
    if (off > 0) {
      ctx.strokeStyle = SIG;
      ctx.lineWidth = 2.2 * k;
      line(x - 9 * k, y - 15 * k, x + (18 * off - 9) * k, y + (18 * off - 15) * k);
    }
    ctx.lineCap = "butt";
  }

  function draw(t, loop) {
    if (loop !== loopNo) plan(loop);
    var rot = base + theta(t),
      tmp = {},
      g = L.g,
      d = L.d,
      q = L.port,
      k,
      p;
    ctx.setTransform(dpr * scale, 0, 0, dpr * scale, 0, 0);
    ctx.clearRect(0, 0, L.W, L.H);
    var outage = clamp((t - T_OUT) / 0.8) * (1 - clamp((t - T_RESET) / 0.6));
    var resetting = t >= T_RESET,
      back = clamp((t - T_RESET) / 1.1),
      drain = clamp((t - T_RESET) / 0.5);

    // a ghost sphere of sea dots, dimmer while offline
    var b3 = [[], [], []];
    for (k = 0; k < sea.length; k++) {
      p = proj(sea[k], rot, tmp);
      if (p.z > 0) b3[p.z > 0.66 ? 2 : p.z > 0.33 ? 1 : 0].push(p.x, p.y);
    }
    ctx.fillStyle = INK;
    for (k = 0; k < 3; k++) {
      ctx.globalAlpha = (0.2 - 0.11 * outage) * (0.45 + k * 0.3);
      dots(b3[k], 0.9);
    }
    ctx.globalAlpha = 0.5 - 0.28 * outage;
    ctx.strokeStyle = INK;
    ctx.lineWidth = 1;
    ctx.setLineDash(outage > 0.5 ? [3, 4] : []);
    ctx.beginPath();
    ctx.arc(g.x, g.y, g.r + 6, 0, TAU);
    ctx.stroke();
    ctx.setLineDash([]);

    // land: on the globe, in flight, or landed in the drive
    var onG = [[], [], [], []],
      fly = [],
      landed = [],
      done = 0;
    for (k = 0; k < N; k++) {
      var f = from[k],
        sl = slots[f.slot];
      if (resetting) {
        // ripple back onto the globe from its center
        p = proj(land[k], rot, tmp);
        var rip = clamp(back * 1.8 - (Math.hypot(p.x - g.x, p.y - g.y) / g.r) * 0.8);
        if (p.z > 0 && rip > 0) onG[Math.min(3, (p.z * 4 * rip) | 0)].push(p.x, p.y);
        landed.push(sl.x, sl.y);
        continue;
      }
      if (t < T_PACK || t < dep[k]) {
        p = proj(land[k], rot, tmp);
        if (p.z > 0) onG[Math.min(3, (p.z * 4) | 0)].push(p.x, p.y);
        continue;
      }
      var u = (t - dep[k]) / FLY;
      if (u >= 1) {
        landed.push(sl.x, sl.y);
        done++;
        continue;
      }
      // two curves that meet at the port, both level with it there, so the stream threads through it
      var qx = q.x + (q.dy ? f.j : 0),
        qy = q.y + (q.dx ? f.j : 0),
        e = ease(u);
      var l1 = Math.hypot(qx - f.x, qy - f.y),
        l2 = Math.hypot(sl.x - qx, sl.y - qy),
        cut = l1 / (l1 + l2),
        v,
        ax,
        ay,
        bx,
        by,
        cx,
        cy;
      if (e < cut) {
        v = e / cut;
        ax = f.x;
        ay = f.y;
        cx = qx - q.dx * 50;
        cy = qy - q.dy * 50;
        bx = qx;
        by = qy;
      } else {
        v = (e - cut) / (1 - cut);
        ax = qx;
        ay = qy;
        cx = qx + q.dx * 40;
        cy = qy + q.dy * 40;
        bx = sl.x;
        by = sl.y;
      }
      fly.push(
        (1 - v) * (1 - v) * ax + 2 * (1 - v) * v * cx + v * v * bx,
        (1 - v) * (1 - v) * ay + 2 * (1 - v) * v * cy + v * v * by,
      );
    }
    ctx.fillStyle = INK;
    for (k = 0; k < 4; k++) {
      ctx.globalAlpha = 0.4 + k * 0.2;
      dots(onG[k], 0.8 + k * 0.17);
    }
    ctx.globalAlpha = 1;

    // network arcs while online
    if (loop !== arcLoop) {
      arcs = [];
      nextArc = 0;
      arcLoop = loop;
    }
    if (t >= nextArc && t < T_PACK - 0.5) {
      spawnArc(t, rot);
      nextArc = t + 0.16;
    }
    arcs = arcs.filter(function (A) {
      return t >= A.t && t - A.t < 1.25;
    });
    ctx.lineWidth = 1.4;
    ctx.strokeStyle = SIG;
    ctx.fillStyle = SIG;
    arcs.forEach(function (A) {
      var age = t - A.t,
        head = clamp(age / 0.6),
        tail = clamp((age - 0.4) / 0.6),
        o = {};
      ctx.beginPath();
      for (var s = tail, first = true; ; s = Math.min(head, s + 0.04)) {
        proj(slerp(A, s, 1 + 0.2 * Math.sin(Math.PI * s)), rot, o);
        if (first) ctx.moveTo(o.x, o.y);
        else ctx.lineTo(o.x, o.y);
        first = false;
        if (s >= head) break;
      }
      ctx.stroke();
      if (head < 1) {
        ctx.beginPath();
        ctx.arc(o.x, o.y, 1.8, 0, TAU);
        ctx.fill();
      }
      if (age > 0.6) {
        var z = proj(A.b, rot, {}),
          m = (age - 0.6) / 0.65;
        ctx.globalAlpha = 1 - m;
        ctx.beginPath();
        ctx.arc(z.x, z.y, 2 + 9 * m, 0, TAU);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
    });

    // the drive, dashed and empty until the copy starts
    var live = t > T_PACK - 0.15 && !(resetting && drain >= 1);
    ctx.lineWidth = 2;
    ctx.strokeStyle = INK;
    ctx.fillStyle = PAPER;
    rrect(d.x, d.y, d.w, d.h, 12);
    ctx.fill();
    if (!live) {
      ctx.setLineDash([5, 5]);
      ctx.globalAlpha = 0.55;
    }
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
    ctx.fillStyle = INK;
    rrect(q.x - 12, d.y - 9, 24, 11, 3);
    ctx.fill();
    ctx.lineWidth = 1;
    ctx.globalAlpha = 0.45;
    line(d.x + 10, d.y + 26, d.x + d.w - 10, d.y + 26);
    ctx.globalAlpha = 1;
    var gb = t < T_PACK ? 0 : resetting ? (drain < 1 ? TOTAL : 0) : t > T_OUT ? TOTAL : Math.round((TOTAL * done) / N);
    text("TINFOIL KIT", d.x + 14, d.y + 17, 10, INK, 600);
    text(gb + " GB", d.x + d.w - 30, d.y + 17, 10, INK, 600, "right");
    var led = t > T_PACK && !resetting ? (t > T_SAY && Math.sin(t * 21) < -0.3 ? 0.3 : 1) : 0.2;
    ctx.globalAlpha = led;
    ctx.fillStyle = led > 0.5 ? SIG : INK;
    ctx.beginPath();
    ctx.arc(d.x + d.w - 16, d.y + 13.5, 3.3, 0, TAU);
    ctx.fill();
    ctx.globalAlpha = 1;
    if (t < T_PACK + 1) {
      // faint empty slots
      ctx.globalAlpha = 0.09 * (1 - clamp((t - T_PACK) / 1));
      ctx.fillStyle = INK;
      var gl = [];
      for (k = 0; k < N; k++) gl.push(slots[k].x, slots[k].y);
      dots(gl, 0.7);
      ctx.globalAlpha = 1;
    }
    ctx.fillStyle = INK;
    ctx.globalAlpha = 1 - drain;
    dots(landed, 0.95);
    ctx.globalAlpha = 1;

    // offline: light each part of the drive in turn, and name it under the drive
    var say = t > T_SAY && !resetting ? t - T_SAY : resetting && drain < 1 ? 99 : -1,
      cum = 0,
      fade = 1 - drain;
    if (say >= 0)
      PARTS.forEach(function (P, j) {
        var c0 = Math.round((cum / TOTAL) * d.cols),
          c1 = Math.max(c0 + 1, Math.round(((cum + P[1]) / TOTAL) * d.cols)),
          lit = [];
        cum += P[1];
        if (say < j * 0.9 || !(say < (j + 1) * 0.9 || (j === PARTS.length - 1 && say < 4.2))) return;
        for (var s = c0 * d.rows; s < Math.min(N, c1 * d.rows); s++) lit.push(slots[s].x, slots[s].y);
        ctx.globalAlpha = clamp((say - j * 0.9) / 0.3) * fade;
        ctx.fillStyle = SIG;
        dots(lit, 1.1);
        var x0 = d.ox + (c0 - 0.5) * d.s,
          x1 = d.ox + (c1 - 0.5) * d.s,
          by = d.y + d.h + 9;
        ctx.strokeStyle = SIG;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(x0, by - 4);
        ctx.lineTo(x0, by);
        ctx.lineTo(x1, by);
        ctx.lineTo(x1, by - 4);
        ctx.stroke();
        var name = P[0] + "  ",
          size = P[1] + " GB",
          fs = 11.5 * ts,
          nw,
          sw;
        ctx.font = "600 " + fs + "px " + MONO;
        nw = ctx.measureText(name).width;
        ctx.font = "500 " + fs + "px " + MONO;
        sw = ctx.measureText(size).width;
        var lx = Math.max(8, Math.min(L.W - 8 - nw - sw, (x0 + x1) / 2 - (nw + sw) / 2)),
          ly = by + 7 + fs * 0.8;
        text(name, lx, ly, 11.5, SIGT, 600);
        text(size, lx + nw, ly, 11.5, OLIVE, 500);
        ctx.globalAlpha = 1;
      });

    // data in motion, on top in signal orange
    ctx.fillStyle = SIG;
    dots(fly, 1.2);

    // wi-fi status
    var w = L.wifi,
      bars = 3,
      off = clamp((t - T_OUT - 0.5) / 0.25) * (1 - clamp((t - T_RESET) / 0.2));
    if (t > T_OUT && !resetting) bars = 3 - Math.min(3, Math.floor(clamp((t - T_OUT) / 0.6) * 4));
    if (resetting) bars = Math.min(3, Math.floor(clamp((t - T_RESET - 0.2) / 0.6) * 4));
    wifi(w.x, w.y, bars, off, ts);
    text(off > 0.5 ? "WI-FI OFF" : "ONLINE", w.x + 18 * ts, w.y - 2 * ts, 11, off > 0.5 ? SIGT : INK, 600);
  }

  // Playback: clicking the figure pauses it (WCAG 2.2.2), a still frame for reduced motion, nothing drawn while off screen.
  var still = window.matchMedia("(prefers-reduced-motion: reduce)"),
    playing = !still.matches,
    visible = true;
  var STILL_AT = 4.4,
    clock = playing ? 0 : STILL_AT,
    last = 0,
    raf = 0;
  function frame() {
    draw(clock % LOOP, Math.floor(clock / LOOP));
  }
  function tick(ms) {
    raf = 0;
    if (last) clock += Math.min(0.05, (ms - last) / 1000);
    last = ms;
    frame();
    if (playing && visible) raf = requestAnimationFrame(tick);
  }
  function kick() {
    if (!stopped && !raf && playing && visible) {
      last = 0;
      raf = requestAnimationFrame(tick);
    }
  }
  function label() {
    btn.setAttribute("aria-pressed", String(!playing));
  }
  // dropping the queued frame makes a pause hold exactly what's on screen
  function toggle() {
    playing = !playing;
    cancelAnimationFrame(raf);
    raf = 0;
    label();
    kick();
  }
  function motion() {
    playing = !still.matches;
    if (!playing) clock = STILL_AT;
    label();
    frame();
    kick();
  }
  btn.addEventListener("click", toggle);
  still.addEventListener("change", motion);
  var io = new IntersectionObserver(function (es) {
    visible = es[0].isIntersecting;
    kick();
  });
  io.observe(cv);
  // resize on the next frame, so changing the canvas height doesn't re-trigger the observer mid-delivery
  var ro = new ResizeObserver(function () {
    requestAnimationFrame(function () {
      if (!stopped) {
        layout();
        frame();
      }
    });
  });
  ro.observe(fig);
  if (document.fonts)
    document.fonts.ready.then(function () {
      if (!stopped) frame();
    });
  label();
  layout();
  frame();
  kick();
  return function stop() {
    stopped = true;
    cancelAnimationFrame(raf);
    btn.removeEventListener("click", toggle);
    still.removeEventListener("change", motion);
    io.disconnect();
    ro.disconnect();
  };
}
