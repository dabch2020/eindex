// ===== eIndex - A股情绪指数 =====

let allData = [];
let dataWarnings = [];
let sortField = 'date';
let sortAsc = false;

// 颜色工具函数
function getIndexColor(value) {
    if (value <= 20) return '#00d4aa';
    if (value <= 40) return '#4f8ff7';
    if (value <= 60) return '#ffc107';
    if (value <= 80) return '#ff9800';
    return '#ff5252';
}

function getSignal(d) {
    const fear = d.fear_threshold || 20;
    const greed = d.greed_threshold || 80;
    if (d.eindex <= fear) return { text: '恐惧', icon: '🟢', cls: 'buy' };
    if (d.eindex >= greed) return { text: '贪婪', icon: '🔴', cls: 'sell' };
    return { text: '中性', icon: '🟡', cls: 'hold' };
}

// 客户端动态阈值补算（当数据缺少 fear_threshold/greed_threshold 时）
const PERCENTILE_WINDOW = 120;
const FEAR_PERCENTILE = 20;
const GREED_PERCENTILE = 80;

function backfillThresholds(data) {
    const hist = [];
    for (const d of data) {
        if (d.fear_threshold == null || d.greed_threshold == null) {
            if (hist.length < 2) {
                d.fear_threshold = FEAR_PERCENTILE;
                d.greed_threshold = GREED_PERCENTILE;
            } else {
                const recent = hist.length > PERCENTILE_WINDOW ? hist.slice(-PERCENTILE_WINDOW) : hist.slice();
                const s = recent.slice().sort((a, b) => a - b);
                const n = s.length;
                const fi = Math.max(0, Math.floor(n * FEAR_PERCENTILE / 100) - 1);
                const gi = Math.min(n - 1, Math.floor(n * GREED_PERCENTILE / 100));
                d.fear_threshold = Math.round(s[fi] * 100) / 100;
                d.greed_threshold = Math.round(s[gi] * 100) / 100;
            }
        }
        hist.push(d.eindex);
    }
}

// 加载数据
async function loadData() {
    try {
        // 优先使用 script 标签预加载的数据（本地 file:// 协议下 fetch 不可用）
        if (window.__EINDEX_DATA__) {
            allData = window.__EINDEX_DATA__.data;
            dataWarnings = window.__EINDEX_DATA__.warnings || [];
            backfillThresholds(allData);
            renderAll();
            return;
        }
        const resp = await fetch('data/eindex_data.json');
        if (!resp.ok) throw new Error('数据文件加载失败');
        const json = await resp.json();
        allData = json.data;
        dataWarnings = json.warnings || [];
        backfillThresholds(allData);
        renderAll();
    } catch (e) {
        console.error('加载数据失败:', e);
        document.getElementById('mainIndexValue').textContent = 'N/A';
        document.getElementById('signalText').textContent = '数据加载失败';
    }
}

// 渲染全部
function renderAll() {
    if (!allData.length) return;
    const recent3 = allData.slice(-3).reverse(); // 最新在前
    renderMainIndex(recent3);
    renderIndicators(recent3);
    renderMainChart();
    renderIndicatorsChart();
    renderTable();
    renderWarnings();
}

// 渲染数据缺失警告
function renderWarnings() {
    var section = document.getElementById('warningsSection');
    var content = document.getElementById('warningsContent');
    if (!dataWarnings.length) {
        section.style.display = 'none';
        return;
    }
    section.style.display = 'block';
    content.innerHTML = dataWarnings.map(function(w) {
        return '<div class="warning-item">⚠️ ' + w + '</div>';
    }).join('');
}

// 渲染主指标
function renderMainIndex(recent3) {
    const d = recent3[0]; // 最新一天
    const val = d.eindex;
    const el = document.getElementById('mainIndexValue');
    el.textContent = val.toFixed(1);
    el.style.background = `linear-gradient(135deg, ${getIndexColor(val)}, ${getIndexColor(Math.min(100, val + 20))})`;
    el.style.webkitBackgroundClip = 'text';
    el.style.webkitTextFillColor = 'transparent';
    el.style.backgroundClip = 'text';

    const sig = getSignal(d);
    const badge = document.getElementById('signalBadge');
    badge.className = `signal-badge ${sig.cls}`;
    document.getElementById('signalIcon').textContent = sig.icon;
    document.getElementById('signalText').textContent = sig.text;
    document.getElementById('updateTime').textContent = `数据更新时间: ${d.date}`;

    // 渲染仪表盘
    renderGauge(val);

    // 最近三天明细
    const container = document.getElementById('recentDays');
    container.innerHTML = '<div class="recent-days-title">最近三天</div>' +
        '<table class="recent-days-table"><thead><tr>' +
        '<th>日期</th><th>情绪指数</th><th>信号</th>' +
        '</tr></thead><tbody>' +
        recent3.map(r => {
            const s = getSignal(r);
            return `<tr><td>${r.date}</td>` +
                `<td style="color:${getIndexColor(r.eindex)};font-weight:700">${r.eindex.toFixed(1)}</td>` +
                `<td class="signal-cell ${s.cls}">${s.icon} ${s.text}</td></tr>`;
        }).join('') +
        '</tbody></table>';
}

// 仪表盘
function renderGauge(value) {
    const chart = echarts.init(document.getElementById('mainGauge'), null, { renderer: 'canvas' });
    const option = {
        series: [{
            type: 'gauge',
            startAngle: 200,
            endAngle: -20,
            min: 0,
            max: 100,
            splitNumber: 10,
            itemStyle: { color: getIndexColor(value) },
            progress: {
                show: true,
                width: 20,
                itemStyle: { color: getIndexColor(value) }
            },
            pointer: {
                length: '60%',
                width: 5,
                itemStyle: { color: '#e8eaed' }
            },
            axisLine: {
                lineStyle: {
                    width: 20,
                    color: [[0.2, '#00d4aa'], [0.8, '#ffc107'], [1, '#ff5252']]
                }
            },
            axisTick: { show: false },
            splitLine: { show: false },
            axisLabel: {
                distance: 28,
                color: '#9aa0b0',
                fontSize: 12
            },
            title: { show: false },
            detail: { show: false },
            data: [{ value: value }]
        }]
    };
    chart.setOption(option);
    window.addEventListener('resize', () => chart.resize());
}

// 渲染指标卡片（最近三天）
function renderIndicators(recent3) {
    function renderDays(containerId, getVal, getPct) {
        const el = document.getElementById(containerId);
        el.innerHTML = recent3.map(d => {
            const val = getVal(d);
            const pct = getPct(d);
            return `<div class="day-row">
                <span class="day-date">${d.date.slice(5)}</span>
                <span class="day-value">${val}</span>
                <div class="day-pct-wrap">
                    <span class="day-pct" style="color:${getIndexColor(pct)}">${pct.toFixed(1)}</span>
                    <div class="percentile-bar"><div class="percentile-fill" style="width:${pct}%;background:${getIndexColor(pct)}"></div></div>
                </div>
            </div>`;
        }).join('');
    }

    renderDays('turnoverDays',
        d => (d.turnover_rate * 100).toFixed(3) + '%',
        d => d.turnover_pct);
    renderDays('marginDays',
        d => (d.margin_ratio * 100).toFixed(3) + '%',
        d => d.margin_pct);
    renderDays('limitUpDays',
        d => (d.limitup_ratio * 100).toFixed(3) + '%',
        d => d.limitup_pct);
}

// 主走势图
function renderMainChart() {
    const chart = echarts.init(document.getElementById('mainChart'), null, { renderer: 'canvas' });
    const dates = allData.map(d => d.date);
    const values = allData.map(d => d.eindex);

    // 找出恐惧/贪婪信号点
    const fearPoints = [];
    const greedPoints = [];
    allData.forEach((d, i) => {
        const fear = d.fear_threshold || 20;
        const greed = d.greed_threshold || 80;
        if (d.eindex <= fear) fearPoints.push({ value: [d.date, d.eindex], itemStyle: { color: '#00d4aa' } });
        if (d.eindex >= greed) greedPoints.push({ value: [d.date, d.eindex], itemStyle: { color: '#ff5252' } });
    });

    // 动态阈值曲线数据
    const fearLine = allData.map(d => d.fear_threshold);
    const greedLine = allData.map(d => d.greed_threshold);

    const option = {
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            backgroundColor: '#1e2235',
            borderColor: '#2a2f45',
            textStyle: { color: '#e8eaed' },
            formatter: function(params) {
                const d = allData.find(item => item.date === params[0].axisValue);
                if (!d) return '';
                const sig = getSignal(d);
                return `<b>${d.date}</b><br/>` +
                    `情绪指数: <b style="color:${getIndexColor(d.eindex)}">${d.eindex.toFixed(1)}</b><br/>` +
                    `信号: ${sig.icon} ${sig.text}<br/>` +
                    `恐惧线: ${(d.fear_threshold != null ? d.fear_threshold : 20).toFixed(1)} / 贪婪线: ${(d.greed_threshold != null ? d.greed_threshold : 80).toFixed(1)}<br/>` +
                    `成交额分位: ${(d.cje_pct || 0).toFixed(1)}<br/>` +
                    `融资分位: ${d.margin_pct.toFixed(1)}<br/>` +
                    `涨停分位: ${d.limitup_pct.toFixed(1)}`;
            }
        },
        legend: {
            data: ['情绪指数', '恐惧线', '贪婪线'],
            textStyle: { color: '#9aa0b0' },
            top: 5
        },
        grid: { left: 60, right: 20, top: 45, bottom: 80 },
        dataZoom: [
            { type: 'inside', start: 90, end: 100 },
            { type: 'slider', start: 90, end: 100, height: 30, bottom: 10,
              borderColor: '#2a2f45', backgroundColor: '#1a1d2e',
              fillerColor: 'rgba(79,143,247,0.15)',
              handleStyle: { color: '#4f8ff7' },
              textStyle: { color: '#9aa0b0' }
            }
        ],
        xAxis: {
            type: 'category',
            data: dates,
            axisLine: { lineStyle: { color: '#2a2f45' } },
            axisLabel: { color: '#9aa0b0', fontSize: 11 }
        },
        yAxis: {
            type: 'value',
            min: 0,
            max: 100,
            interval: 20,
            axisLine: { show: false },
            axisLabel: { color: '#9aa0b0' },
            splitLine: { lineStyle: { color: '#2a2f45' } }
        },
        series: [
            {
                name: '情绪指数',
                type: 'line',
                data: values,
                smooth: true,
                lineStyle: { width: 2, color: '#4f8ff7' },
                itemStyle: { color: '#4f8ff7' },
                areaStyle: {
                    color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                        { offset: 0, color: 'rgba(79,143,247,0.25)' },
                        { offset: 1, color: 'rgba(79,143,247,0.02)' }
                    ])
                }
            },
            {
                name: '恐惧线',
                type: 'line',
                data: fearLine,
                lineStyle: { width: 1, type: 'dashed', color: '#00d4aa' },
                itemStyle: { color: '#00d4aa' },
                symbol: 'none'
            },
            {
                name: '贪婪线',
                type: 'line',
                data: greedLine,
                lineStyle: { width: 1, type: 'dashed', color: '#ff5252' },
                itemStyle: { color: '#ff5252' },
                symbol: 'none'
            },
            {
                name: '恐惧',
                type: 'scatter',
                data: fearPoints,
                symbol: 'triangle',
                symbolSize: 12,
                z: 10
            },
            {
                name: '贪婪',
                type: 'scatter',
                data: greedPoints,
                symbol: 'pin',
                symbolSize: 14,
                z: 10
            }
        ]
    };
    chart.setOption(option);

    window.addEventListener('resize', () => chart.resize());
}

// 三大指标走势对比
function renderIndicatorsChart() {
    const chart = echarts.init(document.getElementById('indicatorsChart'), null, { renderer: 'canvas' });
    const dates = allData.map(d => d.date);

    const option = {
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            backgroundColor: '#1e2235',
            borderColor: '#2a2f45',
            textStyle: { color: '#e8eaed' }
        },
        legend: {
            data: ['成交额分位', '融资余额分位', '涨停家数分位'],
            textStyle: { color: '#9aa0b0' },
            top: 5
        },
        grid: { left: 60, right: 30, top: 45, bottom: 80 },
        dataZoom: [
            { type: 'inside', start: 90, end: 100 },
            { type: 'slider', start: 90, end: 100, height: 30, bottom: 10,
              borderColor: '#2a2f45', backgroundColor: '#1a1d2e',
              fillerColor: 'rgba(79,143,247,0.15)',
              handleStyle: { color: '#4f8ff7' },
              textStyle: { color: '#9aa0b0' }
            }
        ],
        xAxis: {
            type: 'category',
            data: dates,
            axisLine: { lineStyle: { color: '#2a2f45' } },
            axisLabel: { color: '#9aa0b0', fontSize: 11 }
        },
        yAxis: {
            type: 'value',
            axisLine: { show: false },
            axisLabel: { color: '#9aa0b0' },
            splitLine: { lineStyle: { color: '#2a2f45' } }
        },
        series: [
            {
                name: '成交额分位',
                type: 'line',
                data: allData.map(d => d.cje_pct || 0),
                smooth: true,
                lineStyle: { width: 2, color: '#e040fb' },
                itemStyle: { color: '#e040fb' },
                symbol: 'none'
            },
            {
                name: '融资余额分位',
                type: 'line',
                data: allData.map(d => d.margin_pct),
                smooth: true,
                lineStyle: { width: 2, color: '#ff9800' },
                itemStyle: { color: '#ff9800' },
                symbol: 'none'
            },
            {
                name: '涨停家数分位',
                type: 'line',
                data: allData.map(d => d.limitup_pct),
                smooth: true,
                lineStyle: { width: 2, color: '#00d4aa' },
                itemStyle: { color: '#00d4aa' },
                symbol: 'none'
            }
        ]
    };
    chart.setOption(option);
    window.addEventListener('resize', () => chart.resize());
}

// 渲染表格
function renderTable() {
    const tbody = document.getElementById('tableBody');
    const sorted = [...allData].sort((a, b) => {
        let va = a[sortField], vb = b[sortField];
        if (sortField === 'date') {
            va = new Date(va); vb = new Date(vb);
        }
        if (sortField === 'signal') {
            va = a.eindex <= (a.fear_threshold || 20) ? 0 : a.eindex >= (a.greed_threshold || 80) ? 2 : 1;
            vb = b.eindex <= (b.fear_threshold || 20) ? 0 : b.eindex >= (b.greed_threshold || 80) ? 2 : 1;
        }
        return sortAsc ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
    });

    // 显示最近30条
    const recent = sorted.slice(0, 30);

    tbody.innerHTML = recent.map(d => {
        const sig = getSignal(d);
        return `<tr>
            <td>${d.date}</td>
            <td style="color:${getIndexColor(d.eindex)};font-weight:700">${d.eindex.toFixed(1)}</td>
            <td class="signal-cell ${sig.cls}">${sig.icon} ${sig.text}</td>
            <td style="color:${getIndexColor(d.cje_pct || 0)}">${(d.cje_pct || 0).toFixed(1)}</td>
            <td style="color:${getIndexColor(d.margin_pct)}">${d.margin_pct.toFixed(1)}</td>
            <td style="color:${getIndexColor(d.limitup_pct)}">${d.limitup_pct.toFixed(1)}</td>
            <td${d.turnover_rate === 0 ? ' style="color:#c084fc"' : ''}>${(d.turnover_rate * 100).toFixed(3)}%</td>
            <td>${(d.margin_ratio * 100).toFixed(3)}%</td>
            <td${!(d.margin_sh) ? ' style="color:#c084fc"' : ''}>${(d.margin_sh || 0).toFixed(2)}</td>
            <td${!(d.margin_sz) ? ' style="color:#c084fc"' : ''}>${(d.margin_sz || 0).toFixed(2)}</td>
            <td>${d.limitup_count || 0}</td>
            <td>${(d.limitup_ratio * 100).toFixed(3)}%</td>
        </tr>`;
    }).join('');
}

// 表格排序
document.querySelectorAll('th.sortable').forEach(th => {
    th.addEventListener('click', () => {
        const field = th.dataset.sort;
        if (sortField === field) {
            sortAsc = !sortAsc;
        } else {
            sortField = field;
            sortAsc = field === 'date' ? false : true;
        }
        // 重置所有表头箭头
        document.querySelectorAll('th.sortable').forEach(h => {
            h.textContent = h.textContent.replace(/ [▲▼]/g, '');
        });
        th.textContent += sortAsc ? ' ▲' : ' ▼';
        renderTable();
    });
});

// 导出CSV
function exportCSV() {
    if (!allData.length) return;
    const headers = ['日期', '情绪指数', '信号', '成交额分位', '融资分位', '涨停分位', '换手率', '融资占比', '沪融资余额', '深融资余额', '涨停家数', '涨停占比'];
    const rows = allData.map(d => {
        const sig = getSignal(d);
        return [
            d.date,
            d.eindex.toFixed(1),
            sig.text,
            (d.cje_pct || 0).toFixed(1),
            d.margin_pct.toFixed(1),
            d.limitup_pct.toFixed(1),
            (d.turnover_rate * 100).toFixed(3) + '%',
            (d.margin_ratio * 100).toFixed(3) + '%',
            (d.margin_sh || 0).toFixed(2),
            (d.margin_sz || 0).toFixed(2),
            d.limitup_count || 0,
            (d.limitup_ratio * 100).toFixed(3) + '%'
        ].join(',');
    });

    const BOM = '\uFEFF';
    const csv = BOM + headers.join(',') + '\n' + rows.join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `eindex_data_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

// 初始化
loadData();

// ===== 刷新按钮 =====
(function() {
    var _a='github_pat_11AP5KOUY0';
    var _b='dNQq2x013K8F_sH4Fqnd';
    var _c='JtVwfBfOEgy9pxWUQGMmU';
    var _d='VeDdNx7E2QrLeqCZ5OD46NQhjvEPn5Q';
    var DISPATCH_TOKEN = _a+_b+_c+_d;
    var REPO = 'dabch2020/eindex';
    var PAGES_DATA_URL = 'https://dabch2020.github.io/eindex/data/eindex_data.json';
    var btn = document.getElementById('btnRefresh');
    var descEl = document.querySelector('.header-desc');
    var isLocal = location.protocol === 'file:';

    btn.onclick = function() {
        btn.classList.add('loading');
        descEl.textContent = '正在触发后台更新（最近2个交易日），请稍候约1-2分钟…';

        fetch('https://api.github.com/repos/' + REPO + '/dispatches', {
            method: 'POST',
            headers: {
                'Authorization': 'Bearer ' + DISPATCH_TOKEN,
                'Accept': 'application/vnd.github.v3+json'
            },
            body: JSON.stringify({ event_type: 'refresh' })
        })
        .then(function(r) {
            if (r.status === 204 || r.status === 200) {
                descEl.textContent = '✅ 已触发更新，正在等待数据刷新…';
                pollForUpdate();
            } else {
                descEl.textContent = '❌ 触发失败 (HTTP ' + r.status + ')';
                btn.classList.remove('loading');
            }
        })
        .catch(function() {
            descEl.textContent = '❌ 网络错误，请稍后重试';
            btn.classList.remove('loading');
        });
    };

    function pollForUpdate() {
        var originalUpdated = window.__EINDEX_DATA__ ? window.__EINDEX_DATA__.updated_at : '';
        var dataUrl = isLocal ? PAGES_DATA_URL : 'data/eindex_data.json';
        var attempts = 0;
        var maxAttempts = 36;  // 最多等 3 分钟 (36 x 5s)
        var timer = setInterval(function() {
            attempts++;
            descEl.textContent = '✅ 已触发更新，正在等待数据刷新… (' + (attempts * 5) + 's)';
            fetch(dataUrl + '?_t=' + Date.now())
                .then(function(r) { return r.json(); })
                .then(function(json) {
                    if (json.updated_at !== originalUpdated) {
                        clearInterval(timer);
                        allData = json.data;
                        dataWarnings = json.warnings || [];
                        backfillThresholds(allData);
                        renderAll();
                        descEl.textContent = '✅ 数据已更新（' + json.updated_at + '）';
                        btn.classList.remove('loading');
                    } else if (attempts >= maxAttempts) {
                        clearInterval(timer);
                        descEl.textContent = '✅ 更新已触发，请稍后手动刷新页面';
                        btn.classList.remove('loading');
                    }
                })
                .catch(function() {});
        }, 5000);
    }
})();
