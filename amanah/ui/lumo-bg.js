/* lumo-bg — soft spectral gradient + fine monochrome noise/grain field.
   Each speck flickers at its OWN random speed + phase → incoherent random noise
   (no synchronized "breathing"). Built-in scroll PARALLAX: an over-tall inner
   layer drifts vertically with scroll (crisp, never gaps).
   Tunable live via attributes: opacity, density, speed, scale, tint, glow. */
(function () {
  if (customElements.get('lumo-bg')) return;

  var GRAD =
    "radial-gradient(54% 46% at 24% 12%, rgba(46,123,255,A1), transparent 62%)," +
    "radial-gradient(46% 40% at 84% 8%, rgba(245,193,90,A2), transparent 62%)," +
    "radial-gradient(58% 48% at 66% 52%, rgba(122,96,224,A3), transparent 64%)," +
    "radial-gradient(54% 46% at 10% 78%, rgba(120,178,255,A1), transparent 62%)," +
    "radial-gradient(56% 48% at 92% 92%, rgba(245,193,90,A2), transparent 62%)";
  function gradFor(glow) {
    return GRAD.replace(/A1/g, (0.20 * glow).toFixed(3))
               .replace(/A2/g, (0.15 * glow).toFixed(3))
               .replace(/A3/g, (0.10 * glow).toFixed(3));
  }

  if (!document.getElementById('lumo-bg-kf')) {
    var st = document.createElement('style');
    st.id = 'lumo-bg-kf';
    st.textContent = '@keyframes lumoBgDrift{0%{transform:scale(1.04) translate(0,0)}100%{transform:scale(1.14) translate(-1.5%,1%)}}';
    document.head.appendChild(st);
  }
  var INK = [23, 25, 34], ACCENT = [46, 123, 255];
  function num(v, d) { v = parseFloat(v); return isFinite(v) ? v : d; }

  class LumoBg extends HTMLElement {
    static get observedAttributes() { return ['opacity', 'density', 'speed', 'scale', 'tint', 'glow']; }
    connectedCallback() {
      this._opacity = num(this.getAttribute('opacity'), 0.24);
      this._density = num(this.getAttribute('density'), 0.48);
      this._speed = num(this.getAttribute('speed'), 1);
      this._scale = num(this.getAttribute('scale'), 5);
      this._tint = num(this.getAttribute('tint'), 0);
      this._glow = num(this.getAttribute('glow'), 1);
      this._prog = 0.5;

      this._inner = document.createElement('div');
      this._inner.style.cssText = 'position:absolute;left:0;right:0;top:-15%;height:130%;will-change:transform';
      this._grad = document.createElement('div');
      this._grad.style.cssText = 'position:absolute;inset:-12%;filter:blur(20px);animation:lumoBgDrift 34s ease-in-out infinite alternate;background:' + gradFor(this._glow);
      var cv = document.createElement('canvas');
      cv.style.cssText = 'position:absolute;inset:0;width:100%;height:100%';
      this._inner.append(this._grad, cv);
      this.append(this._inner);
      this._cv = cv; this._last = 0; this._t = 0;

      var self = this;
      this._onResize = function () { self._resize(); };
      this._onScroll = function () {
        var max = document.documentElement.scrollHeight - window.innerHeight;
        self._prog = max > 0 ? Math.min(1, Math.max(0, (window.scrollY || window.pageYOffset || 0) / max)) : 0.5;
      };
      window.addEventListener('resize', this._onResize, { passive: true });
      window.addEventListener('scroll', this._onScroll, { passive: true });
      this._resize(); this._onScroll();
      requestAnimationFrame(function () { self._resize(); });
      this._loop = this._loop.bind(this);
      this._raf = requestAnimationFrame(this._loop);
    }
    disconnectedCallback() {
      cancelAnimationFrame(this._raf);
      window.removeEventListener('resize', this._onResize);
      window.removeEventListener('scroll', this._onScroll);
    }
    attributeChangedCallback(name, _o, v) {
      if (!this.isConnected) return;
      var f = num(v, null); if (f === null) return;
      if (name === 'opacity') this._opacity = f;
      else if (name === 'density') this._density = f;
      else if (name === 'speed') this._speed = f;
      else if (name === 'tint') this._tint = f;
      else if (name === 'glow') { this._glow = f; if (this._grad) this._grad.style.background = gradFor(f); }
      else if (name === 'scale') { this._scale = f; this._resize(); }
    }
    _resize() {
      var cv = this._cv; if (!cv) return;
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      this._W = this._inner.clientWidth || window.innerWidth;
      this._H = this._inner.clientHeight || Math.round(window.innerHeight * 1.3);
      cv.width = Math.max(1, this._W * dpr);
      cv.height = Math.max(1, this._H * dpr);
      var ctx = cv.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      this._ctx = ctx;
      var cell = Math.max(3, this._scale);
      this._cell = cell;
      var cols = Math.ceil(this._W / cell) + 1, rows = Math.ceil(this._H / cell) + 1;
      this._cols = cols; this._rows = rows;
      var n = cols * rows;
      this._base = new Float32Array(n);
      this._pha = new Float32Array(n);
      this._spd = new Float32Array(n);
      for (var i = 0; i < n; i++) {
        this._base[i] = Math.random();
        this._pha[i] = Math.random() * 6.2832;
        this._spd[i] = 0.4 + Math.random() * 2.2;
      }
    }
    _loop(ts) {
      this._raf = requestAnimationFrame(this._loop);
      if (this._inner.clientHeight > 0 && this._inner.clientHeight !== this._H) this._resize();
      var budget = 0.13 * window.innerHeight;
      var ty = (0.5 - this._prog) * 2 * budget;
      this._inner.style.transform = 'translate3d(0,' + ty.toFixed(1) + 'px,0)';
      if (ts - this._last < 33) return;
      var dt = Math.min(0.1, (ts - this._last) / 1000);
      this._last = ts;
      this._t += dt * this._speed * 3;
      var ctx = this._ctx; if (!ctx) return;
      var W = this._W, H = this._H, cell = this._cell, cols = this._cols, rows = this._rows;
      var base = this._base, pha = this._pha, spd = this._spd, t = this._t;
      var thresh = 1 - this._density, span = Math.max(0.001, 1 - thresh);
      var r = cell * 0.42, op = this._opacity, tint = this._tint;
      var cr = Math.round(INK[0] + (ACCENT[0] - INK[0]) * tint * 0.7);
      var cg = Math.round(INK[1] + (ACCENT[1] - INK[1]) * tint * 0.7);
      var cb = Math.round(INK[2] + (ACCENT[2] - INK[2]) * tint * 0.7);
      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = 'rgb(' + cr + ',' + cg + ',' + cb + ')';
      var idx = 0;
      for (var y = 0; y < rows; y++) {
        for (var x = 0; x < cols; x++, idx++) {
          var tw = 0.5 + 0.5 * Math.sin(t * spd[idx] + pha[idx]);
          var v = base[idx] * 0.55 + tw * 0.45;
          if (v < thresh) continue;
          var a = ((v - thresh) / span) * op;
          if (a < 0.012) continue;
          ctx.globalAlpha = a;
          ctx.beginPath();
          ctx.arc(x * cell, y * cell, r, 0, 6.2832);
          ctx.fill();
        }
      }
      ctx.globalAlpha = 1;
    }
  }
  customElements.define('lumo-bg', LumoBg);
})();
