(function chartInteractionsModule() {
  const observed = new WeakSet();
  const activeState = new WeakMap();

  // ── SVG Utilities ──

  function parseViewBox(svg) {
    const raw = (svg.getAttribute("viewBox") || "").trim().split(/\s+/).map(Number);
    if (raw.length !== 4 || raw.some(function (n) { return Number.isNaN(n); })) return null;
    return { x: raw[0], y: raw[1], width: raw[2], height: raw[3] };
  }

  function setViewBox(svg, vb) {
    svg.setAttribute("viewBox", vb.x + " " + vb.y + " " + vb.width + " " + vb.height);
  }

  function svgPoint(svg, clientX, clientY) {
    var pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    var m = svg.getScreenCTM();
    if (!m) return { x: 0, y: 0 };
    return pt.matrixTransform(m.inverse());
  }

  function clampViewBox(next, base) {
    var minW = Math.max(base.width * 0.03, 24);
    var minH = Math.max(base.height * 0.05, 18);
    var w = Math.min(Math.max(next.width, minW), base.width);
    var h = Math.min(Math.max(next.height, minH), base.height);
    var x = Math.min(Math.max(next.x, base.x), base.x + base.width - w);
    var y = Math.min(Math.max(next.y, base.y), base.y + base.height - h);
    return { x: x, y: y, width: w, height: h };
  }

  function zoomAbout(svg, base, cur, fx, fy, cx, cy) {
    var nw = cur.width * fx;
    var nh = cur.height * fy;
    return clampViewBox({
      x: cx - nw * ((cx - cur.x) / cur.width),
      y: cy - nh * ((cy - cur.y) / cur.height),
      width: nw,
      height: nh,
    }, base);
  }

  function panBy(svg, base, cur, dx, dy) {
    return clampViewBox({
      x: cur.x + dx, y: cur.y + dy,
      width: cur.width, height: cur.height,
    }, base);
  }

  // ── Data Parsing ──

  function parseSeriesData(svg) {
    try {
      var raw = svg.getAttribute("data-series");
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  function parseSeriesMeta(svg) {
    try {
      var raw = svg.getAttribute("data-series-meta");
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  function isMultiSeries(svg) {
    var meta = parseSeriesMeta(svg);
    return meta && meta.length > 0;
  }

  function state(svg) {
    var st = activeState.get(svg);
    if (!st) { st = {}; activeState.set(svg, st); }
    return st;
  }

  // ── Formatting ──

  function formatValue(val) {
    if (val === null || val === undefined) return "--";
    if (typeof val === "number") {
      if (Number.isInteger(val)) return String(val);
      return val.toFixed(2);
    }
    return String(val);
  }

  function fmtTime(ts) {
    var d = new Date(ts);
    var mo = String(d.getMonth() + 1).padStart(2, "0");
    var dd = String(d.getDate()).padStart(2, "0");
    var hh = String(d.getHours()).padStart(2, "0");
    var mm = String(d.getMinutes()).padStart(2, "0");
    return mo + "/" + dd + " " + hh + ":" + mm;
  }

  function fmtTimeFull(ts) {
    var d = new Date(ts);
    var mo = String(d.getMonth() + 1).padStart(2, "0");
    var dd = String(d.getDate()).padStart(2, "0");
    var hh = String(d.getHours()).padStart(2, "0");
    var mm = String(d.getMinutes()).padStart(2, "0");
    var ss = String(d.getSeconds()).padStart(2, "0");
    return mo + "/" + dd + " " + hh + ":" + mm + ":" + ss;
  }

  function niceStep(range, maxSteps) {
    var rough = range / (maxSteps || 5);
    var exp = Math.pow(10, Math.floor(Math.log10(rough)));
    var mant = rough / exp;
    var nice;
    if (mant <= 1.5) nice = 1;
    else if (mant <= 3.5) nice = 2;
    else if (mant <= 7.5) nice = 5;
    else nice = 10;
    return nice * exp;
  }

  // ── Dynamic Axis System ──

  function ensureAxisLayer(svg) {
    var layer = svg.querySelector(".chart-axis-layer");
    if (layer) return layer;
    var ns = "http://www.w3.org/2000/svg";
    layer = document.createElementNS(ns, "g");
    layer.setAttribute("class", "chart-axis-layer");
    layer.style.pointerEvents = "none";
    svg.insertBefore(layer, svg.firstChild);
    return layer;
  }

  function updateAxes(svg, viewBox, baseViewBox) {
    var layer = ensureAxisLayer(svg);
    var data = parseSeriesData(svg);
    var meta = parseSeriesMeta(svg);
    if (!data || !data.length || !viewBox) { layer.innerHTML = ""; return; }

    var ns = "http://www.w3.org/2000/svg";
    layer.innerHTML = "";

    // -- Y-axis labels --
    // Find data value range from visible data points
    var yMinVal = Infinity, yMaxVal = -Infinity;
    var yDataFound = false;

    if (meta && meta.length) {
      // Multi-series: use the first metric's values
      var firstKey = meta[0].key + "_v";
      for (var i = 0; i < data.length; i++) {
        var v = data[i][firstKey];
        if (v !== undefined) {
          if (v < yMinVal) yMinVal = v;
          if (v > yMaxVal) yMaxVal = v;
          yDataFound = true;
        }
      }
    } else {
      // Single series: use v field
      for (var j = 0; j < data.length; j++) {
        if (data[j].v !== undefined) {
          if (data[j].v < yMinVal) yMinVal = data[j].v;
          if (data[j].v > yMaxVal) yMaxVal = data[j].v;
          yDataFound = true;
        }
      }
    }
    if (!yDataFound) yDataFound = false;

    // Get the Y range in SVG space from the visible data
    var visibleYMin = Infinity, visibleYMax = -Infinity;
    for (var k = 0; k < data.length; k++) {
      if (meta && meta.length) {
        var y = data[k][meta[0].key];
      } else {
        var y = data[k].y;
      }
      if (y !== undefined && data[k].x >= viewBox.x - 10 && data[k].x <= viewBox.x + viewBox.width + 10) {
        if (y < visibleYMin) visibleYMin = y;
        if (y > visibleYMax) visibleYMax = y;
      }
    }

    // Map SVG Y to data values
    if (yDataFound && visibleYMin < Infinity && visibleYMax > -Infinity && visibleYMax > visibleYMin) {
      // Linear mapping: dataValue = yMinVal + (visibleYMax - y) / (visibleYMax - visibleYMin) * (yMaxVal - yMinVal)
      var svgYRange = visibleYMax - visibleYMin;
      var valRange = yMaxVal - yMinVal;
      var yStep = niceStep(valRange * (viewBox.height / svgYRange), 6);
      if (yStep > 0) {
        // Work back from SVG to data to find nice values
        // Find top and bottom data values in view
        var viewTopVal = yMinVal + (visibleYMax - viewBox.y) / svgYRange * valRange;
        var viewBotVal = yMinVal + (visibleYMax - (viewBox.y + viewBox.height)) / svgYRange * valRange;

        var firstTick = Math.ceil(Math.min(viewTopVal, viewBotVal) / yStep) * yStep;
        var lastTick = Math.floor(Math.max(viewTopVal, viewBotVal) / yStep) * yStep;

        for (var tv = firstTick; tv <= lastTick + yStep * 0.5; tv += yStep) {
          // Convert data value to SVG Y
          var svgY = visibleYMax - (tv - yMinVal) / valRange * svgYRange;
          if (svgY >= viewBox.y - 10 && svgY <= viewBox.y + viewBox.height + 10) {
            var text = document.createElementNS(ns, "text");
            text.setAttribute("class", "chart-axis-y-label");
            text.setAttribute("x", String(viewBox.x + 8));
            text.setAttribute("y", String(svgY + 3));
            text.setAttribute("font-size", "11");
            text.setAttribute("fill", "#4a5568");
            text.textContent = formatValue(tv);
            layer.appendChild(text);

            // Subtle tick line
            var tick = document.createElementNS(ns, "line");
            tick.setAttribute("class", "chart-axis-tick");
            tick.setAttribute("x1", String(viewBox.x));
            tick.setAttribute("y1", String(svgY));
            tick.setAttribute("x2", String(viewBox.x + 6));
            tick.setAttribute("y2", String(svgY));
            tick.setAttribute("stroke", "#4a5568");
            tick.setAttribute("stroke-width", "0.8");
            layer.appendChild(tick);
          }
        }
      }
    }

    // -- X-axis labels (time) --
    var tsData = [];
    for (var m = 0; m < data.length; m++) {
      var d = data[m];
      if (d.ts && d.x >= viewBox.x - 10 && d.x <= viewBox.x + viewBox.width + 10) {
        tsData.push({ x: d.x, ts: d.ts });
      }
    }
    if (tsData.length >= 2) {
      var xStartTs = tsData[0].ts;
      var xEndTs = tsData[tsData.length - 1].ts;
      var xStartX = tsData[0].x;
      var xEndX = tsData[tsData.length - 1].x;
      var xSpan = xEndTs - xStartTs;
      var xPxSpan = xEndX - xStartX;

      if (xSpan > 0 && xPxSpan > 10) {
        var timeStep = niceStep(xSpan, 8);

        var firstTimeTick = Math.ceil(xStartTs / timeStep) * timeStep;
        // only show visible ticks
        var visStartTs = xStartTs + (viewBox.x - xStartX) / xPxSpan * xSpan;
        var visEndTs = xStartTs + (viewBox.x + viewBox.width - xStartX) / xPxSpan * xSpan;
        var tickStart = Math.ceil(Math.min(visStartTs, visEndTs) / timeStep) * timeStep;
        var tickEnd = Math.floor(Math.max(visStartTs, visEndTs) / timeStep) * timeStep;

        var labelCount = 0;
        for (var tt = tickStart; tt <= tickEnd + timeStep * 0.5; tt += timeStep) {
          var svgX = xStartX + (tt - xStartTs) / xSpan * xPxSpan;
          if (svgX >= viewBox.x - 5 && svgX <= viewBox.x + viewBox.width + 5) {
            labelCount++;
            var xLabel = document.createElementNS(ns, "text");
            xLabel.setAttribute("class", "chart-axis-x-label");
            xLabel.setAttribute("x", String(svgX));
            xLabel.setAttribute("y", String(viewBox.y + viewBox.height - 4));
            xLabel.setAttribute("text-anchor", "middle");
            xLabel.setAttribute("font-size", "10");
            xLabel.setAttribute("fill", "#4a5568");
            xLabel.textContent = fmtTime(tt);
            layer.appendChild(xLabel);

            var xTick = document.createElementNS(ns, "line");
            xTick.setAttribute("class", "chart-axis-tick");
            xTick.setAttribute("x1", String(svgX));
            xTick.setAttribute("y1", String(viewBox.y + viewBox.height - 6));
            xTick.setAttribute("x2", String(svgX));
            xTick.setAttribute("y2", String(viewBox.y + viewBox.height));
            xTick.setAttribute("stroke", "rgba(74,85,104,0.3)");
            xTick.setAttribute("stroke-width", "0.6");
            layer.appendChild(xTick);

            // Light vertical grid
            var vGrid = document.createElementNS(ns, "line");
            vGrid.setAttribute("class", "chart-axis-vgrid");
            vGrid.setAttribute("x1", String(svgX));
            vGrid.setAttribute("y1", String(viewBox.y));
            vGrid.setAttribute("x2", String(svgX));
            vGrid.setAttribute("y2", String(viewBox.y + viewBox.height));
            vGrid.setAttribute("stroke", "rgba(74,85,104,0.08)");
            vGrid.setAttribute("stroke-width", "0.6");
            layer.appendChild(vGrid);
          }
          if (labelCount > 12) break;
        }
      }
    }
  }

  // ── Crosshair ──

  function ensureCrosshairLayer(svg) {
    var layer = svg.querySelector(".chart-crosshair-layer");
    if (layer) return layer;
    var ns = "http://www.w3.org/2000/svg";
    layer = document.createElementNS(ns, "g");
    layer.setAttribute("class", "chart-crosshair-layer");
    layer.style.pointerEvents = "none";
    var vLine = document.createElementNS(ns, "line");
    vLine.setAttribute("class", "chart-crosshair-v");
    vLine.setAttribute("visibility", "hidden");
    layer.appendChild(vLine);
    svg.appendChild(layer);
    return layer;
  }

  function findNearestPoint(seriesData, targetX) {
    if (!seriesData || !seriesData.length) return null;
    var lo = 0, hi = seriesData.length - 1;
    while (hi - lo > 1) {
      var mid = (lo + hi) >> 1;
      if (seriesData[mid].x < targetX) lo = mid;
      else hi = mid;
    }
    return Math.abs(seriesData[lo].x - targetX) <= Math.abs(seriesData[hi].x - targetX)
      ? seriesData[lo] : seriesData[hi];
  }

  function updateCrosshair(svg, crosshairLayer, point, svgH) {
    var vLine = crosshairLayer.querySelector(".chart-crosshair-v");
    if (!vLine) return;
    if (!point) {
      vLine.setAttribute("visibility", "hidden");
      crosshairLayer.querySelectorAll(".chart-crosshair-h").forEach(function (l) {
        l.setAttribute("visibility", "hidden");
      });
      return;
    }
    vLine.setAttribute("x1", String(point.x));
    vLine.setAttribute("y1", "0");
    vLine.setAttribute("x2", String(point.x));
    vLine.setAttribute("y2", String(svgH));
    vLine.setAttribute("visibility", "visible");

    crosshairLayer.querySelectorAll(".chart-crosshair-h").forEach(function (l) { l.remove(); });

    var meta = parseSeriesMeta(svg);
    var ns = "http://www.w3.org/2000/svg";
    if (meta && meta.length) {
      for (var i = 0; i < meta.length; i++) {
        var key = meta[i].key;
        if (point[key] !== undefined) {
          var hLine = document.createElementNS(ns, "line");
          hLine.setAttribute("class", "chart-crosshair-h");
          hLine.setAttribute("x1", "0");
          hLine.setAttribute("y1", String(point[key]));
          hLine.setAttribute("x2", String(point.x - 4));
          hLine.setAttribute("y2", String(point[key]));
          hLine.setAttribute("stroke", meta[i].color);
          hLine.setAttribute("stroke-width", "1.2");
          hLine.setAttribute("stroke-dasharray", "3 3");
          crosshairLayer.appendChild(hLine);
        }
      }
    } else {
      if (point.y !== undefined) {
        var hl = document.createElementNS(ns, "line");
        hl.setAttribute("class", "chart-crosshair-h");
        hl.setAttribute("x1", "0");
        hl.setAttribute("y1", String(point.y));
        hl.setAttribute("x2", String(point.x - 4));
        hl.setAttribute("y2", String(point.y));
        hl.setAttribute("stroke", "#4a5568");
        hl.setAttribute("stroke-width", "1.2");
        hl.setAttribute("stroke-dasharray", "3 3");
        crosshairLayer.appendChild(hl);
      }
    }
  }

  // ── Tooltip ──

  function ensureTooltipEl(host) {
    var tip = host.querySelector(".chart-crosshair-tooltip");
    if (tip) return tip;
    tip = document.createElement("div");
    tip.className = "chart-crosshair-tooltip hidden";
    host.appendChild(tip);
    return tip;
  }

  function showCrosshairTooltip(tip, host, point, meta, clientX, clientY) {
    if (!point) { tip.classList.add("hidden"); return; }
    var rect = host.getBoundingClientRect();
    var left = clientX - rect.left + 16;
    var top = clientY - rect.top - 12;
    if (left + 260 > rect.width) left = clientX - rect.left - 270;
    if (top < 4) top = 4;
    if (top + 120 > rect.height) top = rect.height - 130;

    var html = "";
    if (meta && meta.length) {
      var tsStr = point.ts ? fmtTimeFull(point.ts) : "";
      html += "<div class=\"crosshair-tip-time\">" + tsStr + "</div>";
      for (var i = 0; i < meta.length; i++) {
        var m = meta[i];
        var val = point[m.key + "_v"];
        html += "<div class=\"crosshair-tip-row\"><span class=\"crosshair-tip-dot\" style=\"background:" + m.color + "\"></span>" + m.label + " <strong>" + formatValue(val) + "</strong> " + (m.unit || "") + "</div>";
      }
    } else {
      if (point.ts) html += "<div class=\"crosshair-tip-time\">" + fmtTimeFull(point.ts) + "</div>";
      html += "<div style=\"font-size:13px\">" + (point.label || "") + "</div>";
      html += "<div style=\"font-weight:700;font-size:15px\">" + formatValue(point.v) + "</div>";
    }

    tip.innerHTML = html;
    tip.style.left = left + "px";
    tip.style.top = top + "px";
    tip.classList.remove("hidden");
  }

  // ── Value Labels ──

  function ensureValueLabelLayer(svg) {
    var layer = svg.querySelector(".chart-value-label-layer");
    if (layer) return layer;
    var ns = "http://www.w3.org/2000/svg";
    layer = document.createElementNS(ns, "g");
    layer.setAttribute("class", "chart-value-label-layer");
    layer.style.pointerEvents = "none";
    layer.style.display = "none";
    svg.appendChild(layer);
    return layer;
  }

  function renderValueLabels(svg, seriesData, meta) {
    var layer = ensureValueLabelLayer(svg);
    var cur = parseViewBox(svg);
    var base = state(svg).baseViewBox;
    if (!cur || !base || !seriesData || !seriesData.length) {
      layer.style.display = "none";
      return;
    }
    layer.innerHTML = "";

    var ns = "http://www.w3.org/2000/svg";
    var margin = cur.width * 0.05;
    var visible = seriesData.filter(function (pt) {
      return pt.x >= cur.x - margin && pt.x <= cur.x + cur.width + margin;
    });
    if (!visible.length) { layer.style.display = "none"; return; }

    var step = Math.max(1, Math.ceil(visible.length / 25));

    function paint(pt, key, val, color, yOff) {
      var t = document.createElementNS(ns, "text");
      t.setAttribute("x", String(pt.x));
      t.setAttribute("y", String(pt[key] + yOff));
      t.setAttribute("text-anchor", "middle");
      t.setAttribute("font-size", "9");
      t.setAttribute("fill", color || "#4a5568");
      t.style.paintOrder = "stroke";
      t.style.stroke = "rgba(255,255,255,0.7)";
      t.style.strokeWidth = "2px";
      t.textContent = formatValue(val);
      layer.appendChild(t);
    }

    if (meta && meta.length) {
      for (var mi = 0; mi < meta.length; mi++) {
        var metric = meta[mi];
        var offY = -6 - mi * 13;
        for (var i = 0; i < visible.length; i += step) {
          var pt = visible[i];
          var val = pt[metric.key + "_v"];
          if (val !== undefined) paint(pt, metric.key, val, metric.color, offY);
        }
      }
    } else {
      for (var j = 0; j < visible.length; j += step) {
        paint(visible[j], "y", visible[j].v, null, -8);
      }
    }
    layer.style.display = "block";
  }

  // ── Stats Panel ──

  function ensureStatsPanel(host) {
    var panel = host.querySelector(".chart-stats-panel");
    if (panel) return panel;
    panel = document.createElement("div");
    panel.className = "chart-stats-panel hidden";
    host.insertBefore(panel, host.firstChild);
    return panel;
  }

  function showStatsPanel(panel, svg, selPoints, startTs, endTs) {
    if (!selPoints || !selPoints.length) { panel.classList.add("hidden"); return; }
    var meta = parseSeriesMeta(svg);

    var timeRange = "";
    if (startTs && endTs) {
      timeRange = fmtTimeFull(startTs) + " ~ " + fmtTimeFull(endTs);
    }

    var html = '<div class="stats-panel-head"><strong>选区统计</strong><span>' + selPoints.length + ' 点';
    if (timeRange) html += ' | ' + timeRange;
    html += '</span><button type="button" class="stats-panel-close" title="关闭">&#10005;</button></div>';
    html += '<div style="font-size:11px;color:var(--muted);margin-bottom:6px">已按此时间范围筛选数据，点击重置按钮恢复全量。</div>';

    if (meta && meta.length) {
      html += '<div class="stats-panel-grid">';
      for (var i = 0; i < meta.length; i++) {
        var key = meta[i].key;
        var vals = selPoints.map(function (pt) { return pt[key + "_v"]; }).filter(function (v) { return v !== undefined; });
        if (vals.length) {
          var mn = Math.min.apply(null, vals);
          var mx = Math.max.apply(null, vals);
          var avg = vals.reduce(function (a, b) { return a + b; }, 0) / vals.length;
          html += '<div class="stats-panel-item"><span class="crosshair-tip-dot" style="background:' + meta[i].color + '"></span>' +
            meta[i].label + ' <span class="stats-val">最小 ' + formatValue(mn) + '</span><span class="stats-val">最大 ' + formatValue(mx) + '</span><span class="stats-val">均值 ' + formatValue(avg) + '</span></div>';
        }
      }
      html += '</div>';
    } else {
      var vals2 = selPoints.map(function (pt) { return pt.v; }).filter(function (v) { return v !== undefined; });
      if (vals2.length) {
        var smn = Math.min.apply(null, vals2), smx = Math.max.apply(null, vals2);
        var savg = vals2.reduce(function (a, b) { return a + b; }, 0) / vals2.length;
        html += '<div class="stats-panel-grid"><div class="stats-panel-item">最小 ' + formatValue(smn) + ' 最大 ' + formatValue(smx) + ' 均值 ' + formatValue(savg) + '</div></div>';
      }
    }

    panel.innerHTML = html;
    panel.classList.remove("hidden");
    panel.querySelector(".stats-panel-close").addEventListener("click", function () {
      panel.classList.add("hidden");
    });
  }

  // ── Brush Selection Layer ──

  function ensureSelectionOverlay(svg) {
    var layer = svg.querySelector(".chart-selection-layer");
    if (layer) return layer;
    var ns = "http://www.w3.org/2000/svg";
    layer = document.createElementNS(ns, "g");
    layer.setAttribute("class", "chart-selection-layer");
    layer.style.pointerEvents = "none";

    var rect = document.createElementNS(ns, "rect");
    rect.setAttribute("class", "chart-selection-rect");
    rect.setAttribute("visibility", "hidden");
    layer.appendChild(rect);

    // Selection label (shows the range being selected)
    var label = document.createElementNS(ns, "text");
    label.setAttribute("class", "chart-selection-label");
    label.setAttribute("visibility", "hidden");
    label.setAttribute("text-anchor", "middle");
    label.setAttribute("font-size", "12");
    label.setAttribute("fill", "#2c6d76");
    label.setAttribute("font-weight", "600");
    layer.appendChild(label);

    svg.appendChild(layer);
    return layer;
  }

  // ── Toolbar ──

  function ensureToolbar(host, svg, baseViewBox) {
    var bar = host.querySelector(".chart-interaction-toolbar");
    if (bar) return bar;

    bar = document.createElement("div");
    bar.className = "chart-interaction-toolbar";
    bar.innerHTML =
      '<div class="ci-group">' +
        '<button type="button" class="ci-btn" data-act="reset" title="重置缩放 (R)">&#8634; 重置</button>' +
        '<button type="button" class="ci-btn" data-act="zoom-in" title="放大 (+)">+</button>' +
        '<button type="button" class="ci-btn" data-act="zoom-out" title="缩小 (-)">&minus;</button>' +
      '</div>' +
      '<div class="ci-group">' +
        '<button type="button" class="ci-btn" data-act="pan-left" title="左移 (&larr;)">&#8592;</button>' +
        '<button type="button" class="ci-btn" data-act="pan-right" title="右移 (&rarr;)">&#8594;</button>' +
        '<button type="button" class="ci-btn" data-act="pan-up" title="上移">&uarr;</button>' +
        '<button type="button" class="ci-btn" data-act="pan-down" title="下移">&darr;</button>' +
      '</div>' +
      '<div class="ci-group">' +
        '<button type="button" class="ci-btn" data-act="y-tighten" title="Y轴收紧">Y+</button>' +
        '<button type="button" class="ci-btn" data-act="y-relax" title="Y轴放宽">Y&minus;</button>' +
      '</div>' +
      '<div class="ci-group">' +
        '<button type="button" class="ci-btn ci-toggle" data-act="toggle-labels" title="数值标签">标签</button>' +
      '</div>' +
      '<div class="ci-group">' +
        '<button type="button" class="ci-btn ci-fullscreen" data-act="fullscreen" title="全屏显示 (F)">&#9974; 全屏</button>' +
      '</div>' +
      '<span class="ci-hint">滚轮缩放 | 拖框筛选 | 悬停查看 | R/&larr;&rarr;&uarr;&darr; 快捷键</span>';

    host.insertBefore(bar, svg);

    bar.querySelectorAll("[data-act]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var cur = parseViewBox(svg) || baseViewBox;
        var cx = cur.x + cur.width / 2;
        var cy = cur.y + cur.height / 2;
        var nxt = cur;
        switch (btn.dataset.act) {
          case "reset":
            nxt = { x: baseViewBox.x, y: baseViewBox.y, width: baseViewBox.width, height: baseViewBox.height };
            break;
          case "zoom-in":
            nxt = zoomAbout(svg, baseViewBox, cur, 0.82, 0.82, cx, cy);
            break;
          case "zoom-out":
            nxt = zoomAbout(svg, baseViewBox, cur, 1.22, 1.22, cx, cy);
            break;
          case "y-tighten":
            nxt = zoomAbout(svg, baseViewBox, cur, 1, 0.82, cx, cy);
            break;
          case "y-relax":
            nxt = zoomAbout(svg, baseViewBox, cur, 1, 1.22, cx, cy);
            break;
          case "pan-left":
            nxt = panBy(svg, baseViewBox, cur, -cur.width * 0.15, 0);
            break;
          case "pan-right":
            nxt = panBy(svg, baseViewBox, cur, cur.width * 0.15, 0);
            break;
          case "pan-up":
            nxt = panBy(svg, baseViewBox, cur, 0, -cur.height * 0.15);
            break;
          case "pan-down":
            nxt = panBy(svg, baseViewBox, cur, 0, cur.height * 0.15);
            break;
          case "toggle-labels":
            toggleLabels(svg, btn);
            return;
          case "fullscreen":
            toggleChartFullscreen(host, svg, btn);
            return;
        }
        setViewBox(svg, nxt);
        onViewChanged(svg, host);
      });
    });
    return bar;
  }

  // ── Fullscreen toggle ──

  function clearChartFullscreenPage() {
    document.querySelectorAll(".chart-fullscreen-page").forEach(function (page) {
      page.classList.remove("chart-fullscreen-page");
    });
  }

  function toggleChartFullscreen(host, svg, btn) {
    var isActive = host.classList.contains("chart-fullscreen");
    var page = host.closest(".page");
    if (isActive) {
      host.classList.remove("chart-fullscreen");
      document.body.classList.remove("chart-fullscreen-active");
      clearChartFullscreenPage();
      btn.innerHTML = "&#9974; 全屏";
      btn.title = "全屏显示 (F)";
    } else {
      clearChartFullscreenPage();
      host.classList.add("chart-fullscreen");
      document.body.classList.add("chart-fullscreen-active");
      if (page) page.classList.add("chart-fullscreen-page");
      btn.innerHTML = "&#10005; 退出全屏";
      btn.title = "退出全屏 (Esc)";
    }
    // Refresh axis after layout change
    setTimeout(function () {
      var cur = parseViewBox(svg);
      var base = state(svg).baseViewBox;
      if (cur && base) updateAxes(svg, cur, base);
    }, 150);
  }

  function toggleLabels(svg, btn) {
    var st = state(svg);
    st.labelsVisible = !st.labelsVisible;
    var layer = ensureValueLabelLayer(svg);
    if (st.labelsVisible) {
      btn.classList.add("active");
      renderValueLabels(svg, parseSeriesData(svg), parseSeriesMeta(svg));
    } else {
      btn.classList.remove("active");
      layer.style.display = "none";
      layer.innerHTML = "";
    }
  }

  // ── Post-ViewChange Hook ──

  function onViewChanged(svg, host) {
    var st = state(svg);
    var cur = parseViewBox(svg);
    if (!cur) return;
    updateAxes(svg, cur, st.baseViewBox);
    if (st.labelsVisible) {
      renderValueLabels(svg, parseSeriesData(svg), parseSeriesMeta(svg));
    }
  }

  // ── Main Binding ──

  var globalDrag = null;
  var currentSvg = null;

  window.addEventListener("mouseup", function (event) {
    if (!globalDrag || !currentSvg) return;
    var svg = currentSvg;
    var baseViewBox = state(svg).baseViewBox;
    var point = svgPoint(svg, event.clientX, event.clientY);
    var host = svg.closest(".interactive-chart-host");
    var statsPanel = host ? host.querySelector(".chart-stats-panel") : null;

    if (globalDrag.mode === "select") {
      var sx = Math.min(globalDrag.start.x, point.x);
      var sw = Math.abs(point.x - globalDrag.start.x);
      if (sw > baseViewBox.width * 0.01) {
        // Find the time range of the selected X region
        var seriesData = parseSeriesData(svg);
        var selPoints = seriesData.filter(function (d) {
          return d.x >= sx && d.x <= sx + sw;
        });
        if (selPoints.length >= 2) {
          var startTs = selPoints[0].ts;
          var endTs = selPoints[selPoints.length - 1].ts;
          if (startTs && endTs && startTs < endTs) {
            // Dispatch custom event for the app to handle data filtering
            var filterEvt = new CustomEvent("chart:apply-filter", {
              bubbles: true,
              detail: { startTs: startTs, endTs: endTs, pointCount: selPoints.length }
            });
            svg.dispatchEvent(filterEvt);
            // Show confirmation in stats panel
            if (statsPanel) showStatsPanel(statsPanel, svg, selPoints, startTs, endTs);
          }
        } else {
          if (statsPanel) showStatsPanel(statsPanel, svg, null, null, null);
        }
      }
    }

    // Hide selection overlay
    var selLayer = svg.querySelector(".chart-selection-layer");
    if (selLayer) {
      var selRect = selLayer.querySelector(".chart-selection-rect");
      var selLabel = selLayer.querySelector(".chart-selection-label");
      if (selRect) selRect.setAttribute("visibility", "hidden");
      if (selLabel) selLabel.setAttribute("visibility", "hidden");
    }

    globalDrag = null;
    currentSvg = null;
  });

  function bindInteractiveChart(host) {
    var svg = host.querySelector("svg.chart-svg");
    if (!svg || observed.has(svg)) return;
    var baseViewBox = parseViewBox(svg);
    if (!baseViewBox) return;

    observed.add(svg);
    host.classList.add("interactive-chart-host");

    var st = state(svg);
    st.baseViewBox = baseViewBox;

    ensureToolbar(host, svg, baseViewBox);
    var crosshairLayer = ensureCrosshairLayer(svg);
    ensureAxisLayer(svg);
    var selectionLayer = ensureSelectionOverlay(svg);
    var selectionRect = selectionLayer.querySelector(".chart-selection-rect");
    var selectionLabel = selectionLayer.querySelector(".chart-selection-label");
    var tooltipEl = ensureTooltipEl(host);
    var statsPanel = ensureStatsPanel(host);
    var seriesData = parseSeriesData(svg);
    var seriesMeta = parseSeriesMeta(svg);
    var svgHeight = baseViewBox.height;

    // Initial axis render
    updateAxes(svg, baseViewBox, baseViewBox);

    // ── Mouse move: crosshair or brush/pan ──
    svg.addEventListener("mousemove", function (event) {
      if (globalDrag && currentSvg === svg) {
        var pt = svgPoint(svg, event.clientX, event.clientY);
        if (globalDrag.mode === "select") {
          var x = Math.min(globalDrag.start.x, pt.x);
          var y = Math.min(globalDrag.start.y, pt.y);
          var w = Math.abs(pt.x - globalDrag.start.x);
          var h = Math.abs(pt.y - globalDrag.start.y);
          selectionRect.setAttribute("x", String(x));
          selectionRect.setAttribute("y", String(y));
          selectionRect.setAttribute("width", String(w));
          selectionRect.setAttribute("height", String(h));
          selectionRect.setAttribute("visibility", "visible");

          // Show range label
          if (w > 10 && h > 10) {
            var midX = x + w / 2;
            var midY = y - 8;
            var data = parseSeriesData(svg);
            var rangeInfo = "";
            if (data && data.length) {
              var vis = data.filter(function (d) { return d.x >= x && d.x <= x + w; });
              if (vis.length >= 2 && vis[0].ts && vis[vis.length - 1].ts) {
                rangeInfo = fmtTime(vis[0].ts) + " ~ " + fmtTime(vis[vis.length - 1].ts) + " (" + vis.length + "点)";
              }
            }
            selectionLabel.setAttribute("x", String(midX));
            selectionLabel.setAttribute("y", String(midY));
            selectionLabel.setAttribute("visibility", "visible");
            selectionLabel.textContent = rangeInfo || (w.toFixed(0) + " x " + h.toFixed(0));
          }
          return;
        }
        if (globalDrag.mode === "pan") {
          var dx = globalDrag.start.x - pt.x;
          var dy = globalDrag.start.y - pt.y;
          setViewBox(svg, panBy(svg, baseViewBox, globalDrag.startViewBox, dx, dy));
          onViewChanged(svg, host);
        }
        return;
      }

      var isEventDot = event.target.closest("[data-event-index]");
      if (isEventDot) {
        var vLine = crosshairLayer.querySelector(".chart-crosshair-v");
        if (vLine) vLine.setAttribute("visibility", "hidden");
        crosshairLayer.querySelectorAll(".chart-crosshair-h").forEach(function (l) { l.remove(); });
        tooltipEl.classList.add("hidden");
        return;
      }

      // Crosshair
      var svgPt = svgPoint(svg, event.clientX, event.clientY);
      var nearest = findNearestPoint(seriesData, svgPt.x);
      updateCrosshair(svg, crosshairLayer, nearest, svgHeight);
      showCrosshairTooltip(tooltipEl, host, nearest, seriesMeta, event.clientX, event.clientY);
    });

    svg.addEventListener("mouseleave", function () {
      var vLine = crosshairLayer.querySelector(".chart-crosshair-v");
      if (vLine) vLine.setAttribute("visibility", "hidden");
      crosshairLayer.querySelectorAll(".chart-crosshair-h").forEach(function (l) { l.remove(); });
      tooltipEl.classList.add("hidden");
      if (globalDrag && globalDrag.mode === "select" && currentSvg === svg) {
        selectionRect.setAttribute("visibility", "hidden");
        selectionLabel.setAttribute("visibility", "hidden");
      }
    });

    // ── Wheel zoom ──
    var wheelTimer = null;
    svg.addEventListener("wheel", function (event) {
      event.preventDefault();
      var cur = parseViewBox(svg) || baseViewBox;
      var pt = svgPoint(svg, event.clientX, event.clientY);
      var factor = event.deltaY < 0 ? 0.86 : 1.16;
      var nxt;
      if (event.shiftKey) {
        nxt = zoomAbout(svg, baseViewBox, cur, 1, factor, pt.x, pt.y);
      } else if (event.altKey) {
        nxt = zoomAbout(svg, baseViewBox, cur, factor, 1, pt.x, pt.y);
      } else {
        nxt = zoomAbout(svg, baseViewBox, cur, factor, factor, pt.x, pt.y);
      }
      setViewBox(svg, nxt);
      clearTimeout(wheelTimer);
      wheelTimer = setTimeout(function () { onViewChanged(svg, host); }, 60);
      // Quick axis update for smooth scroll feel
      updateAxes(svg, nxt, baseViewBox);
    }, { passive: false });

    // ── Mouse down: start brush or pan ──
    svg.addEventListener("mousedown", function (event) {
      if (event.button !== 0) return;
      var pt = svgPoint(svg, event.clientX, event.clientY);
      var isPan = event.shiftKey || event.altKey || event.ctrlKey;
      var isEventDot = event.target.closest("[data-event-index]");
      if (isEventDot) return;

      globalDrag = {
        mode: isPan ? "pan" : "select",
        start: pt,
        startViewBox: parseViewBox(svg) || baseViewBox,
      };
      currentSvg = svg;

      if (!isPan) {
        selectionRect.setAttribute("x", String(pt.x));
        selectionRect.setAttribute("y", String(pt.y));
        selectionRect.setAttribute("width", "0");
        selectionRect.setAttribute("height", "0");
        selectionRect.setAttribute("visibility", "visible");
        selectionLabel.setAttribute("visibility", "hidden");
      }
      tooltipEl.classList.add("hidden");
    });
  }

  // ── Keyboard Shortcuts ──

  var hoveredHost = null;
  document.addEventListener("mouseover", function (event) {
    var h = event.target.closest(".interactive-chart-host");
    if (h) hoveredHost = h;
  });
  document.addEventListener("mouseout", function (event) {
    if (hoveredHost && !hoveredHost.contains(event.relatedTarget)) hoveredHost = null;
  });

  document.addEventListener("keydown", function (event) {
    if (!hoveredHost) return;
    var tgt = event.target;
    if (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA" || tgt.tagName === "SELECT" || tgt.isContentEditable) return;

    var svg = hoveredHost.querySelector("svg.chart-svg");
    if (!svg || globalDrag) return;
    var base = parseViewBox(svg);
    var cur = parseViewBox(svg) || base;
    if (!base || !cur) return;

    var cx = cur.x + cur.width / 2;
    var cy = cur.y + cur.height / 2;
    var nxt = null;

    switch (event.key) {
      case "r": case "R":
        nxt = { x: base.x, y: base.y, width: base.width, height: base.height };
        break;
      case "+": case "=":
        nxt = zoomAbout(svg, base, cur, 0.84, 0.84, cx, cy);
        break;
      case "-":
        nxt = zoomAbout(svg, base, cur, 1.2, 1.2, cx, cy);
        break;
      case "ArrowLeft":
        nxt = panBy(svg, base, cur, -cur.width * 0.12, 0);
        break;
      case "ArrowRight":
        nxt = panBy(svg, base, cur, cur.width * 0.12, 0);
        break;
      case "ArrowUp":
        nxt = panBy(svg, base, cur, 0, -cur.height * 0.12);
        break;
      case "ArrowDown":
        nxt = panBy(svg, base, cur, 0, cur.height * 0.12);
        break;
      case "f": case "F":
        var fsBtn = hoveredHost.querySelector(".ci-fullscreen");
        if (fsBtn) { toggleChartFullscreen(hoveredHost, svg, fsBtn); return; }
        break;
    }
    if (nxt) {
      event.preventDefault();
      setViewBox(svg, nxt);
      onViewChanged(svg, hoveredHost);
    }
  });

  // Esc: exit chart fullscreen globally
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      var fsHost = document.querySelector(".chart-fullscreen");
      if (fsHost) {
        var btn = fsHost.querySelector(".ci-fullscreen");
        var svg = fsHost.querySelector("svg.chart-svg");
        if (btn && svg) toggleChartFullscreen(fsHost, svg, btn);
      }
    }
  });

  // ── Auto-detect & Bind ──

  function enhanceCharts() {
    document.querySelectorAll(".chart-host, #envChart").forEach(function (host) {
      if (host.querySelector("svg.chart-svg")) {
        bindInteractiveChart(host);
      }
    });
  }

  var observer = new MutationObserver(function () { enhanceCharts(); });

  function boot() {
    try {
      enhanceCharts();
      observer.observe(document.body, { childList: true, subtree: true });
    } catch (e) {
      console.error("[chart_interactions] boot error:", e);
    }
  }

  if (document.readyState === "loading") {
    window.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
