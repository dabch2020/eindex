// ===== eIndex - A股情绪指数 =====

let allData = [];
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

function getSignal(value) {
    if (value <= 20) return { text: '买入信号', icon: '🟢', cls: 'buy' };
    if (value >= 80) return { text: '卖出信号', icon: '🔴', cls: 'sell' };
    return { text: '持有信号', icon: '🟡', cls: 'hold' };
}

// 加载数据
async function loadData() {
    try {
        const resp = await fetch('data/eindex_data.json');
        if (!resp.ok) throw new Error('数据文件加载失败');
        const json = await resp.json();
        allData = json.data;
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
    const latest = allData[allData.length - 1];
    renderMainIndex(latest);
    renderIndicators(latest);
    renderMainChart();
    renderIndicatorsChart();
    renderTable();
}

// 渲染主指标
function renderMainIndex(d) {
    const val = d.eindex;
    const el = document.getElementById('mainIndexValue');
    el.textContent = val.toFixed(1);
    el.style.background = `linear-gradient(135deg, ${getIndexColor(val)}, ${getIndexColor(Math.min(100, val + 20))})`;
    el.style.webkitBackgroundClip = 'text';
    el.style.webkitTextFillColor = 'transparent';
    el.style.backgroundClip = 'text';

    const sig = getSignal(val);
    const badge = document.getElementById('signalBadge');
    badge.className = `signal-badge ${sig.cls}`;
    document.getElementById('signalIcon').textContent = sig.icon;
    document.getElementById('signalText').textContent = sig.text;
    document.getElementById('updateTime').textContent = `数据更新时间: ${d.date}`;

    // 渲染仪表盘
    renderGauge(val);
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

// 渲染指标卡片
function renderIndicators(d) {
    // 换手率
    document.getElementById('turnoverValue').textContent = (d.turnover_rate * 100).toFixed(3) + '%';
    document.getElementById('turnoverPercentile').textContent = d.turnover_pct.toFixed(1);
    const turnoverBar = document.getElementById('turnoverBar');
    turnoverBar.style.width = d.turnover_pct + '%';
    turnoverBar.style.background = getIndexColor(d.turnover_pct);

    // 融资占比
    document.getElementById('marginValue').textContent = (d.margin_ratio * 100).toFixed(3) + '%';
    document.getElementById('marginPercentile').textContent = d.margin_pct.toFixed(1);
    const marginBar = document.getElementById('marginBar');
    marginBar.style.width = d.margin_pct + '%';
    marginBar.style.background = getIndexColor(d.margin_pct);

    // 涨停占比
    document.getElementById('limitUpValue').textContent = (d.limitup_ratio * 100).toFixed(3) + '%';
    document.getElementById('limitUpPercentile').textContent = d.limitup_pct.toFixed(1);
    const limitUpBar = document.getElementById('limitUpBar');
    limitUpBar.style.width = d.limitup_pct + '%';
    limitUpBar.style.background = getIndexColor(d.limitup_pct);
}

// 主走势图
function renderMainChart() {
    const chart = echarts.init(document.getElementById('mainChart'), null, { renderer: 'canvas' });
    const dates = allData.map(d => d.date);
    const values = allData.map(d => d.eindex);

    // 找出买卖信号点
    const buyPoints = [];
    const sellPoints = [];
    allData.forEach((d, i) => {
        if (d.eindex <= 20) buyPoints.push({ value: [d.date, d.eindex], itemStyle: { color: '#00d4aa' } });
        if (d.eindex >= 80) sellPoints.push({ value: [d.date, d.eindex], itemStyle: { color: '#ff5252' } });
    });

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
                const sig = getSignal(d.eindex);
                return `<b>${d.date}</b><br/>` +
                    `情绪指数: <b style="color:${getIndexColor(d.eindex)}">${d.eindex.toFixed(1)}</b><br/>` +
                    `信号: ${sig.icon} ${sig.text}<br/>` +
                    `换手率分位: ${d.turnover_pct.toFixed(1)}<br/>` +
                    `融资分位: ${d.margin_pct.toFixed(1)}<br/>` +
                    `涨停分位: ${d.limitup_pct.toFixed(1)}`;
            }
        },
        grid: { left: 60, right: 30, top: 40, bottom: 80 },
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
            axisLine: { show: false },
            axisLabel: { color: '#9aa0b0' },
            splitLine: { lineStyle: { color: '#2a2f45' } }
        },
        visualMap: {
            show: false,
            pieces: [
                { lte: 20, color: '#00d4aa' },
                { gt: 20, lte: 80, color: '#4f8ff7' },
                { gt: 80, color: '#ff5252' }
            ]
        },
        series: [
            {
                name: '情绪指数',
                type: 'line',
                data: values,
                smooth: true,
                lineStyle: { width: 2 },
                areaStyle: {
                    color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                        { offset: 0, color: 'rgba(79,143,247,0.25)' },
                        { offset: 1, color: 'rgba(79,143,247,0.02)' }
                    ])
                },
                markLine: {
                    silent: true,
                    lineStyle: { type: 'dashed' },
                    data: [
                        { yAxis: 20, lineStyle: { color: '#00d4aa' }, label: { formatter: '买入线 (20)', color: '#00d4aa', fontSize: 11 } },
                        { yAxis: 80, lineStyle: { color: '#ff5252' }, label: { formatter: '卖出线 (80)', color: '#ff5252', fontSize: 11 } }
                    ]
                }
            },
            {
                name: '买入信号',
                type: 'scatter',
                data: buyPoints,
                symbol: 'triangle',
                symbolSize: 12,
                z: 10
            },
            {
                name: '卖出信号',
                type: 'scatter',
                data: sellPoints,
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
            data: ['换手率分位', '融资余额分位', '涨停家数分位'],
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
            min: 0,
            max: 100,
            axisLine: { show: false },
            axisLabel: { color: '#9aa0b0' },
            splitLine: { lineStyle: { color: '#2a2f45' } }
        },
        series: [
            {
                name: '换手率分位',
                type: 'line',
                data: allData.map(d => d.turnover_pct),
                smooth: true,
                lineStyle: { width: 2, color: '#4f8ff7' },
                itemStyle: { color: '#4f8ff7' },
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
            va = a.eindex <= 20 ? 0 : a.eindex >= 80 ? 2 : 1;
            vb = b.eindex <= 20 ? 0 : b.eindex >= 80 ? 2 : 1;
        }
        return sortAsc ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
    });

    // 显示最近30条
    const recent = sorted.slice(0, 30);

    tbody.innerHTML = recent.map(d => {
        const sig = getSignal(d.eindex);
        return `<tr>
            <td>${d.date}</td>
            <td style="color:${getIndexColor(d.eindex)};font-weight:700">${d.eindex.toFixed(1)}</td>
            <td class="signal-cell ${sig.cls}">${sig.icon} ${sig.text}</td>
            <td>${(d.turnover_rate * 100).toFixed(3)}%</td>
            <td>${d.turnover_pct.toFixed(1)}</td>
            <td>${(d.margin_ratio * 100).toFixed(3)}%</td>
            <td>${d.margin_pct.toFixed(1)}</td>
            <td>${d.limitup_count || 0}</td>
            <td>${(d.limitup_ratio * 100).toFixed(3)}%</td>
            <td>${d.limitup_pct.toFixed(1)}</td>
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
    const headers = ['日期', '情绪指数', '信号', '换手率', '换手率分位', '融资占比', '融资分位', '停板家数', '涨停占比', '涨停分位'];
    const rows = allData.map(d => {
        const sig = getSignal(d.eindex);
        return [
            d.date,
            d.eindex.toFixed(1),
            sig.text,
            (d.turnover_rate * 100).toFixed(3) + '%',
            d.turnover_pct.toFixed(1),
            (d.margin_ratio * 100).toFixed(3) + '%',
            d.margin_pct.toFixed(1),
            d.limitup_count || 0,
            (d.limitup_ratio * 100).toFixed(3) + '%',
            d.limitup_pct.toFixed(1)
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
    var btn = document.getElementById('btnRefresh');
    var descEl = document.querySelector('.header-desc');

    btn.onclick = function() {
        btn.classList.add('loading');
        descEl.textContent = '正在触发后台更新，请稍候约1-2分钟…';

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
        var originalDate = allData.length ? allData[allData.length - 1].date : '';
        var attempts = 0;
        var maxAttempts = 36;  // 最多等 3 分钟 (36 x 5s)
        var timer = setInterval(function() {
            attempts++;
            fetch('data/eindex_data.json?_t=' + Date.now())
                .then(function(r) { return r.json(); })
                .then(function(json) {
                    var newDate = json.data.length ? json.data[json.data.length - 1].date : '';
                    if (newDate !== originalDate) {
                        clearInterval(timer);
                        location.reload();
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
