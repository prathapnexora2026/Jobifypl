/* ============================================================================
   JobifyPL shared image cropper — WhatsApp / Instagram style.

   Usage:
     const blob = await cropImageFile(file);   // File -> square JPEG Blob
     if (blob) { ...upload blob... }            // null if the user cancelled

   The user pans (drag) and zooms (pinch / wheel / slider) an image inside a
   circular frame; on "Done" we render the framed square region to a canvas and
   return a JPEG Blob. Output is a square (the circle is inscribed) so it looks
   perfect wherever avatars are shown rounded. Self-contained: injects its own
   overlay + styles the first time it runs. Non-image files pass straight
   through unchanged (so document uploads that reuse this are never mangled).
   ========================================================================== */
(function () {
  if (window.cropImageFile) return;
  var OUT = 512;                 // output square size in px
  var injected = false;

  function inject() {
    if (injected) return; injected = true;
    var css =
      ".jcrop-bg{position:fixed;inset:0;z-index:4000;background:#0b0f1a;display:none;flex-direction:column;touch-action:none;-webkit-user-select:none;user-select:none;}" +
      ".jcrop-bg.show{display:flex;}" +
      ".jcrop-top{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;color:#fff;flex-shrink:0;}" +
      ".jcrop-top b{font-size:16px;font-weight:700;}" +
      ".jcrop-top button{background:none;border:none;color:#fff;font-size:15px;font-weight:700;padding:8px 4px;cursor:pointer;}" +
      ".jcrop-top .done{color:#F5A800;}" +
      ".jcrop-stage{flex:1;position:relative;overflow:hidden;}" +
      ".jcrop-stage img{position:absolute;top:0;left:0;transform-origin:0 0;will-change:transform;pointer-events:none;-webkit-user-drag:none;max-width:none;}" +
      ".jcrop-frame{position:absolute;pointer-events:none;box-shadow:0 0 0 4000px rgba(0,0,0,.58);border:2px solid rgba(255,255,255,.92);border-radius:50%;}" +
      ".jcrop-hint{position:absolute;left:0;right:0;bottom:14px;text-align:center;color:rgba(255,255,255,.72);font-size:13px;pointer-events:none;}" +
      ".jcrop-ctrl{padding:14px 22px 24px;display:flex;align-items:center;gap:14px;flex-shrink:0;}" +
      ".jcrop-ctrl input[type=range]{flex:1;accent-color:#F5A800;height:4px;}" +
      ".jcrop-ic{color:rgba(255,255,255,.85);font-size:20px;line-height:1;}";
    var st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);

    var bg = document.createElement("div");
    bg.className = "jcrop-bg"; bg.id = "jcrop-bg";
    bg.innerHTML =
      '<div class="jcrop-top">' +
        '<button id="jcrop-cancel">Cancel</button>' +
        '<b>Move &amp; Zoom</b>' +
        '<button class="done" id="jcrop-done">Done</button>' +
      '</div>' +
      '<div class="jcrop-stage" id="jcrop-stage">' +
        '<img id="jcrop-img" alt="">' +
        '<div class="jcrop-frame" id="jcrop-frame"></div>' +
        '<div class="jcrop-hint">Drag to move • Pinch or use the slider to zoom</div>' +
      '</div>' +
      '<div class="jcrop-ctrl">' +
        '<span class="jcrop-ic">&#128444;</span>' +
        '<input type="range" id="jcrop-zoom" min="1" max="4" step="0.01" value="1">' +
        '<span class="jcrop-ic" style="font-size:26px;">&#128444;</span>' +
      '</div>';
    document.body.appendChild(bg);
  }

  window.cropImageFile = function (file) {
    return new Promise(function (resolve) {
      // Not an image? (e.g. a PDF) — return the file untouched.
      if (!file || !/^image\//i.test(file.type || "")) { resolve(file); return; }
      inject();

      var bg = document.getElementById("jcrop-bg");
      var stage = document.getElementById("jcrop-stage");
      var img = document.getElementById("jcrop-img");
      var frame = document.getElementById("jcrop-frame");
      var zoom = document.getElementById("jcrop-zoom");

      var nw = 0, nh = 0;                     // natural image size
      var D = 0, fL = 0, fT = 0;              // frame diameter + top-left (stage coords)
      var baseScale = 1, scale = 1, tx = 0, ty = 0;
      var objectUrl = URL.createObjectURL(file);

      function render() {
        img.style.transform = "translate(" + tx + "px," + ty + "px) scale(" + scale + ")";
      }
      function clamp() {
        var dw = nw * scale, dh = nh * scale;
        var minX = fL + D - dw, maxX = fL;      // image must cover the frame
        var minY = fT + D - dh, maxY = fT;
        if (tx > maxX) tx = maxX; if (tx < minX) tx = minX;
        if (ty > maxY) ty = maxY; if (ty < minY) ty = minY;
      }
      function zoomAt(newScale, ax, ay) {       // keep point under (ax,ay) fixed
        newScale = Math.max(baseScale, Math.min(baseScale * 4, newScale));
        var nx = (ax - tx) / scale, ny = (ay - ty) / scale;
        scale = newScale;
        tx = ax - nx * scale; ty = ay - ny * scale;
        clamp(); render();
        zoom.value = (scale / baseScale).toFixed(2);
      }

      function layout() {
        var sw = stage.clientWidth, sh = stage.clientHeight;
        D = Math.max(80, Math.min(sw, sh) - 44);
        fL = (sw - D) / 2; fT = (sh - D) / 2;
        frame.style.width = frame.style.height = D + "px";
        frame.style.left = fL + "px"; frame.style.top = fT + "px";
        baseScale = Math.max(D / nw, D / nh);
        scale = baseScale;
        var dw = nw * scale, dh = nh * scale;
        tx = fL + (D - dw) / 2; ty = fT + (D - dh) / 2;   // centre the image
        zoom.min = "1"; zoom.max = "4"; zoom.value = "1";
        clamp(); render();
      }

      // ---- pointer pan + pinch ----
      var pts = {};           // active pointers
      var pinchStart = 0, scaleStart = 1;
      function midpoint() {
        var a = Object.keys(pts);
        return { x: (pts[a[0]].x + pts[a[1]].x) / 2, y: (pts[a[0]].y + pts[a[1]].y) / 2 };
      }
      function dist() {
        var a = Object.keys(pts);
        var dx = pts[a[0]].x - pts[a[1]].x, dy = pts[a[0]].y - pts[a[1]].y;
        return Math.hypot(dx, dy);
      }
      function toStage(e) {
        var r = stage.getBoundingClientRect();
        return { x: e.clientX - r.left, y: e.clientY - r.top };
      }
      function onDown(e) {
        stage.setPointerCapture && stage.setPointerCapture(e.pointerId);
        pts[e.pointerId] = toStage(e);
        if (Object.keys(pts).length === 2) { pinchStart = dist(); scaleStart = scale; }
      }
      function onMove(e) {
        if (!pts[e.pointerId]) return;
        var p = toStage(e), prev = pts[e.pointerId];
        var n = Object.keys(pts).length;
        if (n === 1) {
          tx += p.x - prev.x; ty += p.y - prev.y; clamp(); render();
        }
        pts[e.pointerId] = p;
        if (n === 2 && pinchStart > 0) {
          var m = midpoint();
          zoomAt(scaleStart * (dist() / pinchStart), m.x, m.y);
        }
      }
      function onUp(e) {
        delete pts[e.pointerId];
        if (Object.keys(pts).length < 2) pinchStart = 0;
      }
      function onWheel(e) {
        e.preventDefault();
        var p = toStage(e);
        zoomAt(scale * (e.deltaY < 0 ? 1.1 : 0.9), p.x, p.y);
      }
      function onZoomSlider() {
        zoomAt(baseScale * parseFloat(zoom.value), fL + D / 2, fT + D / 2);
      }

      function cleanup() {
        stage.removeEventListener("pointerdown", onDown);
        stage.removeEventListener("pointermove", onMove);
        stage.removeEventListener("pointerup", onUp);
        stage.removeEventListener("pointercancel", onUp);
        stage.removeEventListener("wheel", onWheel);
        zoom.removeEventListener("input", onZoomSlider);
        document.getElementById("jcrop-done").onclick = null;
        document.getElementById("jcrop-cancel").onclick = null;
        bg.classList.remove("show");
        img.onload = null; img.src = "";
        try { URL.revokeObjectURL(objectUrl); } catch (e) {}
      }
      function finish(blob) { cleanup(); resolve(blob); }

      img.onload = function () {
        nw = img.naturalWidth || 1; nh = img.naturalHeight || 1;
        img.style.width = nw + "px"; img.style.height = nh + "px";
        bg.classList.add("show");
        // layout after the overlay is visible so stage has real dimensions
        requestAnimationFrame(layout);
      };
      img.src = objectUrl;

      stage.addEventListener("pointerdown", onDown);
      stage.addEventListener("pointermove", onMove);
      stage.addEventListener("pointerup", onUp);
      stage.addEventListener("pointercancel", onUp);
      stage.addEventListener("wheel", onWheel, { passive: false });
      zoom.addEventListener("input", onZoomSlider);

      document.getElementById("jcrop-cancel").onclick = function () { finish(null); };
      document.getElementById("jcrop-done").onclick = function () {
        // source square in natural-image coords for the framed circle's bounding box
        var sx = (fL - tx) / scale, sy = (fT - ty) / scale, ss = D / scale;
        var c = document.createElement("canvas"); c.width = OUT; c.height = OUT;
        var ctx = c.getContext("2d");
        ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, OUT, OUT);
        ctx.drawImage(img, sx, sy, ss, ss, 0, 0, OUT, OUT);
        c.toBlob(function (blob) {
          finish(blob || null);
        }, "image/jpeg", 0.9);
      };
    });
  };
})();
