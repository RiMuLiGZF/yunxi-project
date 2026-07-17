/**
 * YunXi UI Kit - Chart Component
 * 云汐组件库 - 图表组件（轻量 Canvas 实现）
 * 支持柱状图(bar)、折线图(line)、饼图(pie)
 */

(function (global) {
  'use strict';

  const DEFAULT_COLORS = [
    '#2563eb', // primary
    '#0891b2', // secondary
    '#059669', // success
    '#d97706', // warning
    '#dc2626', // error
    '#7c3aed', // purple
    '#db2777', // pink
    '#0891b2', // cyan
  ];

  const Chart = {
    /**
     * Create a chart
     * @param {Object} options
     * @param {string} options.type - bar | line | pie
     * @param {Array} [options.data] - Chart data
     * @param {Array} [options.labels] - X-axis labels
     * @param {Array} [options.series] - Data series (for multi-series)
     * @param {string} [options.title]
     * @param {number} [options.height=300]
     * @param {boolean} [options.legend=true]
     * @param {boolean} [options.tooltip=true]
     * @param {Array} [options.colors]
     * @returns {HTMLElement}
     */
    create(options) {
      options = options || {};
      const type = options.type || 'bar';
      const colors = options.colors || DEFAULT_COLORS;

      const container = document.createElement('div');
      container.className = 'yx-chart';
      if (options.height) container.style.height = options.height + 'px';

      // Title
      if (options.title) {
        const title = document.createElement('div');
        title.className = 'yx-chart__title';
        title.textContent = options.title;
        container.appendChild(title);
      }

      // Canvas
      const canvasWrap = document.createElement('div');
      canvasWrap.style.position = 'relative';
      canvasWrap.style.flex = '1';

      const canvas = document.createElement('canvas');
      canvas.className = 'yx-chart__canvas';
      canvasWrap.appendChild(canvas);

      // Tooltip
      const tooltip = document.createElement('div');
      tooltip.className = 'yx-chart__tooltip';
      canvasWrap.appendChild(tooltip);

      container.appendChild(canvasWrap);

      // Legend
      let legendEl = null;
      if (options.legend !== false && (type === 'pie' || (options.series && options.series.length > 1))) {
        legendEl = document.createElement('div');
        legendEl.className = 'yx-chart__legend';
        container.appendChild(legendEl);
      }

      // Get data
      function getData() {
        if (type === 'pie') {
          return options.data || [];
        }
        if (options.series) return options.series;
        if (options.data) return [{ name: '', data: options.data }];
        return [];
      }

      function getLabels() {
        return options.labels || [];
      }

      // Render
      function render() {
        const rect = canvasWrap.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        const width = rect.width;
        const height = options.height || 300;

        canvas.width = width * dpr;
        canvas.height = height * dpr;
        canvas.style.width = width + 'px';
        canvas.style.height = height + 'px';

        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        ctx.clearRect(0, 0, width, height);

        const data = getData();
        const labels = getLabels();

        if (type === 'bar') {
          drawBar(ctx, data, labels, width, height);
        } else if (type === 'line') {
          drawLine(ctx, data, labels, width, height);
        } else if (type === 'pie') {
          drawPie(ctx, data, width, height);
        }
      }

      function drawBar(ctx, series, labels, width, height) {
        const padding = { top: 20, right: 20, bottom: 40, left: 50 };
        const chartW = width - padding.left - padding.right;
        const chartH = height - padding.top - padding.bottom;

        // Find max value
        let maxVal = 0;
        series.forEach(function (s) {
          s.data.forEach(function (v) {
            if (v > maxVal) maxVal = v;
          });
        });
        maxVal = Math.ceil(maxVal * 1.1);
        if (maxVal === 0) maxVal = 1;

        // Grid lines
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.15)';
        ctx.lineWidth = 1;
        const gridCount = 5;
        for (let i = 0; i <= gridCount; i++) {
          const y = padding.top + (chartH / gridCount) * i;
          ctx.beginPath();
          ctx.moveTo(padding.left, y);
          ctx.lineTo(width - padding.right, y);
          ctx.stroke();

          // Y-axis label
          const val = Math.round(maxVal - (maxVal / gridCount) * i);
          ctx.fillStyle = 'var(--yx-color-text-tertiary)';
          ctx.fillStyle = '#94a3b8';
          ctx.font = '11px sans-serif';
          ctx.textAlign = 'right';
          ctx.textBaseline = 'middle';
          ctx.fillText(String(val), padding.left - 8, y);
        }

        // Bars
        const groupCount = labels.length;
        const seriesCount = series.length;
        const groupWidth = chartW / groupCount;
        const barWidth = Math.min(32, (groupWidth - 16) / seriesCount);

        labels.forEach(function (label, i) {
          const groupX = padding.left + groupWidth * i + groupWidth / 2;

          series.forEach(function (s, si) {
            const val = s.data[i] || 0;
            const barH = (val / maxVal) * chartH;
            const barX = groupX - (seriesCount * barWidth) / 2 + si * barWidth + (seriesCount > 1 ? 2 : 0);
            const barY = padding.top + chartH - barH;

            ctx.fillStyle = colors[si % colors.length];
            ctx.beginPath();
            ctx.roundRect(barX, barY, barWidth - (seriesCount > 1 ? 4 : 0), barH, [4, 4, 0, 0]);
            ctx.fill();
          });

          // X-axis label
          ctx.fillStyle = '#94a3b8';
          ctx.font = '11px sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'top';
          ctx.fillText(label, groupX, height - padding.bottom + 8);
        });

        // Store for tooltip
        canvas._chartData = { series, labels, padding, chartW, chartH, maxVal, type: 'bar' };
      }

      function drawLine(ctx, series, labels, width, height) {
        const padding = { top: 20, right: 20, bottom: 40, left: 50 };
        const chartW = width - padding.left - padding.right;
        const chartH = height - padding.top - padding.bottom;

        let maxVal = 0;
        let minVal = Infinity;
        series.forEach(function (s) {
          s.data.forEach(function (v) {
            if (v > maxVal) maxVal = v;
            if (v < minVal) minVal = v;
          });
        });
        maxVal = Math.ceil(maxVal * 1.1);
        if (minVal > 0) minVal = 0;
        else minVal = Math.floor(minVal * 1.1);
        const range = maxVal - minVal || 1;

        // Grid lines
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.15)';
        ctx.lineWidth = 1;
        const gridCount = 5;
        for (let i = 0; i <= gridCount; i++) {
          const y = padding.top + (chartH / gridCount) * i;
          ctx.beginPath();
          ctx.moveTo(padding.left, y);
          ctx.lineTo(width - padding.right, y);
          ctx.stroke();

          const val = Math.round(maxVal - (range / gridCount) * i);
          ctx.fillStyle = '#94a3b8';
          ctx.font = '11px sans-serif';
          ctx.textAlign = 'right';
          ctx.textBaseline = 'middle';
          ctx.fillText(String(val), padding.left - 8, y);
        }

        // Lines
        const pointCount = labels.length;
        const stepX = chartW / (pointCount - 1 || 1);

        series.forEach(function (s, si) {
          const color = colors[si % colors.length];

          // Area fill
          ctx.beginPath();
          s.data.forEach(function (val, i) {
            const x = padding.left + stepX * i;
            const y = padding.top + chartH - ((val - minVal) / range) * chartH;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
          });
          ctx.lineTo(padding.left + stepX * (s.data.length - 1), padding.top + chartH);
          ctx.lineTo(padding.left, padding.top + chartH);
          ctx.closePath();
          const gradient = ctx.createLinearGradient(0, padding.top, 0, padding.top + chartH);
          gradient.addColorStop(0, color + '20');
          gradient.addColorStop(1, color + '05');
          ctx.fillStyle = gradient;
          ctx.fill();

          // Line
          ctx.beginPath();
          ctx.strokeStyle = color;
          ctx.lineWidth = 2;
          ctx.lineJoin = 'round';
          s.data.forEach(function (val, i) {
            const x = padding.left + stepX * i;
            const y = padding.top + chartH - ((val - minVal) / range) * chartH;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
          });
          ctx.stroke();

          // Points
          s.data.forEach(function (val, i) {
            const x = padding.left + stepX * i;
            const y = padding.top + chartH - ((val - minVal) / range) * chartH;
            ctx.beginPath();
            ctx.arc(x, y, 3, 0, Math.PI * 2);
            ctx.fillStyle = '#fff';
            ctx.fill();
            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            ctx.stroke();
          });
        });

        // X-axis labels
        labels.forEach(function (label, i) {
          const x = padding.left + stepX * i;
          ctx.fillStyle = '#94a3b8';
          ctx.font = '11px sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'top';
          ctx.fillText(label, x, height - padding.bottom + 8);
        });

        canvas._chartData = { series, labels, padding, chartW, chartH, maxVal, minVal, range, stepX, type: 'line' };
      }

      function drawPie(ctx, data, width, height) {
        const centerX = width / 2;
        const centerY = height / 2;
        const radius = Math.min(width, height) / 2 - 30;
        const innerRadius = radius * 0.6;

        const total = data.reduce(function (sum, d) { return sum + (d.value || 0); }, 0);
        if (total === 0) return;

        let startAngle = -Math.PI / 2;

        data.forEach(function (d, i) {
          const value = d.value || 0;
          const sliceAngle = (value / total) * Math.PI * 2;
          const endAngle = startAngle + sliceAngle;

          ctx.beginPath();
          ctx.arc(centerX, centerY, radius, startAngle, endAngle);
          ctx.arc(centerX, centerY, innerRadius, endAngle, startAngle, true);
          ctx.closePath();
          ctx.fillStyle = d.color || colors[i % colors.length];
          ctx.fill();

          // Border between slices
          ctx.strokeStyle = '#fff';
          ctx.lineWidth = 2;
          ctx.stroke();

          startAngle = endAngle;
        });

        // Center text
        ctx.fillStyle = 'var(--yx-color-text-primary)';
        ctx.fillStyle = '#0f172a';
        ctx.font = 'bold 20px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(String(total), centerX, centerY - 8);
        ctx.font = '11px sans-serif';
        ctx.fillStyle = '#94a3b8';
        ctx.fillText('总计', centerX, centerY + 12);

        canvas._chartData = { data, centerX, centerY, radius, innerRadius, total, type: 'pie' };

        // Update legend
        if (legendEl) {
          legendEl.innerHTML = '';
          data.forEach(function (d, i) {
            const item = document.createElement('span');
            item.className = 'yx-chart__legend-item';
            item.innerHTML = '<span class="yx-chart__legend-dot" style="background:' + (d.color || colors[i % colors.length]) + '"></span>' +
              (d.name || '') + ' (' + (d.value || 0) + ')';
            legendEl.appendChild(item);
          });
        }
      }

      // Tooltip handling
      canvas.addEventListener('mousemove', function (e) {
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const d = canvas._chartData;
        if (!d) return;

        if (d.type === 'bar' || d.type === 'line') {
          const labels = d.labels;
          const stepX = d.type === 'line' ? d.stepX : (d.chartW / labels.length);
          const index = Math.round((x - d.padding.left) / stepX);

          if (index >= 0 && index < labels.length) {
            let html = '<div class="yx-chart__tooltip-title">' + labels[index] + '</div>';
            d.series.forEach(function (s, si) {
              const val = s.data[index] || 0;
              const name = s.name || ('系列' + (si + 1));
              html += '<div class="yx-chart__tooltip-item"><span class="yx-chart__tooltip-dot" style="background:' + colors[si % colors.length] + '"></span>' + name + ': ' + val + '</div>';
            });
            tooltip.innerHTML = html;
            tooltip.classList.add('yx-chart__tooltip--visible');

            const tipRect = tooltip.getBoundingClientRect();
            tooltip.style.left = Math.min(x + 10, rect.width - tipRect.width - 10) + 'px';
            tooltip.style.top = Math.max(0, y - 10 - tipRect.height) + 'px';
          } else {
            tooltip.classList.remove('yx-chart__tooltip--visible');
          }
        } else if (d.type === 'pie') {
          const dx = x - d.centerX;
          const dy = y - d.centerY;
          const dist = Math.sqrt(dx * dx + dy * dy);

          if (dist >= d.innerRadius && dist <= d.radius) {
            let angle = Math.atan2(dy, dx);
            if (angle < -Math.PI / 2) angle += Math.PI * 2;
            let startAngle = -Math.PI / 2;

            for (let i = 0; i < d.data.length; i++) {
              const sliceAngle = (d.data[i].value / d.total) * Math.PI * 2;
              const endAngle = startAngle + sliceAngle;
              if (angle >= startAngle && angle < endAngle) {
                tooltip.innerHTML = '<div class="yx-chart__tooltip-title">' + (d.data[i].name || '') + '</div>' +
                  '<div>数值: ' + d.data[i].value + '</div>' +
                  '<div>占比: ' + ((d.data[i].value / d.total) * 100).toFixed(1) + '%</div>';
                tooltip.classList.add('yx-chart__tooltip--visible');
                const tipRect = tooltip.getBoundingClientRect();
                tooltip.style.left = Math.min(x + 10, rect.width - tipRect.width - 10) + 'px';
                tooltip.style.top = Math.max(0, y - 10 - tipRect.height) + 'px';
                break;
              }
              startAngle = endAngle;
            }
          } else {
            tooltip.classList.remove('yx-chart__tooltip--visible');
          }
        }
      });

      canvas.addEventListener('mouseleave', function () {
        tooltip.classList.remove('yx-chart__tooltip--visible');
      });

      // Initial render
      requestAnimationFrame(render);

      // Resize observer
      if ('ResizeObserver' in window) {
        const ro = new ResizeObserver(function () {
          render();
        });
        ro.observe(canvasWrap);
      }

      container._chart = {
        render: render,
        setData: function (newData) {
          options.data = newData;
          render();
        },
        setOptions: function (newOptions) {
          Object.assign(options, newOptions);
          render();
        }
      };

      return container;
    },

    /**
     * Create a bar chart
     */
    bar(options) {
      options.type = 'bar';
      return this.create(options);
    },

    /**
     * Create a line chart
     */
    line(options) {
      options.type = 'line';
      return this.create(options);
    },

    /**
     * Create a pie chart
     */
    pie(options) {
      options.type = 'pie';
      return this.create(options);
    }
  };

  global.YunXiUI = global.YunXiUI || {};
  global.YunXiUI.Chart = Chart;

})(typeof window !== 'undefined' ? window : this);
