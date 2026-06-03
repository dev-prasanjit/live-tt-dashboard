// Global state
let currentStrategies = [];
let latestLtps = {};
let mtmChart = null;
let mtmHistoryData = [];  // [{time: 'HH:MM', pnl: number}]
let latestTodayPnl = 0;   // In-memory cache of current Today's P&L
let nseHolidaysSet = new Set();
let selectedMtmDate = ''; // active date in chart

document.addEventListener('DOMContentLoaded', async () => {
    // Initialize Theme Switcher Toggle
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
    const themeToggle = document.getElementById('themeToggle');
    if (themeToggle) {
        themeToggle.checked = (savedTheme === 'dark');
        themeToggle.addEventListener('change', (e) => {
            const theme = e.target.checked ? 'dark' : 'light';
            document.documentElement.setAttribute('data-theme', theme);
            localStorage.setItem('theme', theme);
            renderMtmChart();
        });
    }

    // Fetch market holidays on load
    await fetchMarketHolidays();

    // Initial fetch of data.json baseline
    await fetchData();

    // Initialize clock immediately and tick every second
    updateClockAndStatus();
    setInterval(updateClockAndStatus, 1000);
    
    // Fetch indices immediately and poll every 5 seconds (only during IST market hours)
    fetchIndices();
    setInterval(async () => {
        if (isMarketOpenIST()) {
            await fetchIndices();
        }
    }, 5000);

    // Manual Refresh Button Event Handler
    document.getElementById('refreshBtn').addEventListener('click', async () => {
        const btn = document.getElementById('refreshBtn');
        btn.style.opacity = '0.5';
        
        try {
            console.log("Triggering forced live fetch on backend...");
            // Trigger the python backend to fetch live data from Tradetron instantly!
            await fetch('/api/force_refresh', { method: 'POST' });
            
            // Wait 4 seconds for Playwright to grab the pages and rewrite data.json
            await new Promise(resolve => setTimeout(resolve, 4000));
            
            // Re-render the dashboard using the fresh JSON
            await fetchData();
        } catch (err) {
            console.error("Force refresh failed:", err);
            await fetchData(); // Fallback
        } finally {
            btn.style.opacity = '1';
        }
    });

    // Auto-refresh data.json every 5 minutes
    setInterval(() => {
        console.log('Auto-refreshing data.json baseline from Tradetron API...');
        fetchData();
    }, 300000); // 5 minutes

    // Poll live prices from backend and recalculate PnLs every 5 seconds (only during IST market hours)
    setInterval(async () => {
        if (isMarketOpenIST()) {
            await fetchLivePrices();
            recalculateAndRender();
        }
    }, 5000);

    // Fetch available history days and MTM history on load
    await loadHistoryDays();
    await fetchMtmHistory(selectedMtmDate);

    // Attach click listener for Chart Downloader
    const downloadBtn = document.getElementById('downloadChartBtn');
    if (downloadBtn) {
        downloadBtn.addEventListener('click', downloadChartImage);
    }

    // Record MTM snapshot and refresh chart every 1 minute during market hours (if today's chart is selected)
    setInterval(async () => {
        if (selectedMtmDate === getTodayISTString() && isMarketOpenIST()) {
            await recordMtmSnapshot();
            await fetchMtmHistory(selectedMtmDate);
        }
    }, 60000); // 1 minute
    // All Strategies MTM Accordion toggle listener
    const detailsEl = document.querySelector('details.collapse');
    if (detailsEl) {
        detailsEl.addEventListener('toggle', (e) => {
            if (e.target.open) {
                renderIndividualStrategyCharts();
            }
        });
    }
});

async function fetchData() {
    try {
        console.log("Fetching baseline data.json...");
        const response = await fetch('data.json?t=' + new Date().getTime());
        if (!response.ok) throw new Error('Data not found');
        const strategies = await response.json();
        
        // Filter valid LIVE AUTO strategies
        currentStrategies = strategies.filter(s => s && s.template && s.template.name && s.deployment_type === 'LIVE AUTO');
        
        // Record baseline values for real-time delta tracking
        currentStrategies.forEach(strat => {
            strat.initial_sum_of_pnl = parseFloat(strat.sum_of_pnl) || 0;
            strat.initial_all_pnl = parseFloat(strat.all_pnl) || 0;
            
            // Populate initial LTPs from data.json
            if (strat.calculated_positions) {
                strat.calculated_positions.forEach(pos => {
                    if (pos.Instrument) {
                        const channel = pos.Instrument.toUpperCase().replace(/\s+/g, '-');
                        if (latestLtps[channel] === undefined) {
                            latestLtps[channel] = parseFloat(pos.ltp) || 0;
                        }
                    }
                });
            }
        });

        // Perform initial calculation and render
        recalculateAndRender();
    } catch (error) {
        console.error('Error fetching data:', error);
        alert('Failed to load strategy data. Ensure data.json is present.');
    }
}

async function fetchLivePrices() {
    try {
        const response = await fetch('/api/live-prices');
        if (response.ok) {
            const data = await response.json();
            // Merge the live prices into latestLtps
            for (const channel in data) {
                const normalizedChannel = channel.toUpperCase().replace(/\s+/g, '-');
                latestLtps[normalizedChannel] = parseFloat(data[channel]);
            }
            console.log(`Live prices polled: ${Object.keys(latestLtps).length} prices active.`);
        }
    } catch (err) {
        console.error("Failed to fetch live prices from backend:", err);
    }
}

function recalculateAndRender() {
    let totalPnl = 0;
    let totalCapital = 0;
    let activeCount = 0;
    let todayPnlSum = 0;

    // Recalculate open positions and strategy sum PnLs
    currentStrategies.forEach(strat => {
        let strategyOpenPositionsPnl = 0;
        let strategyClosedPositionsPnl = 0;

        if (strat.calculated_positions) {
            strat.calculated_positions.forEach(pos => {
                const qty = parseFloat(pos.quantity) || 0;
                if (qty === 0) {
                    // Closed position: PnL is static from latest data.json
                    strategyClosedPositionsPnl += parseFloat(pos.pnl) || 0;
                } else {
                    // Open position: calculate PnL using the latest LTP
                    const channel = pos.Instrument.toUpperCase().replace(/\s+/g, '-');
                    const ltp = latestLtps[channel] !== undefined ? latestLtps[channel] : (parseFloat(pos.ltp) || 0);
                    pos.ltp = ltp;
                    
                    const price = parseFloat(pos.price) || 0;
                    const entryValue = pos.entry_value !== undefined ? parseFloat(pos.entry_value) : (price * qty);
                    
                    // PnL = LTP * Quantity - Entry Value
                    pos.pnl = ltp * qty - entryValue;
                    strategyOpenPositionsPnl += pos.pnl;
                }
            });
        }

        // Strategy current run PnL = open positions PnL + closed positions PnL
        strat.sum_of_pnl = strategyOpenPositionsPnl + strategyClosedPositionsPnl;

        // Change in the current run's PnL since the last API fetch
        const pnlChange = strat.sum_of_pnl - strat.initial_sum_of_pnl;

        // Strategy total PnL is the cumulative baseline + real-time change
        strat.all_pnl = strat.initial_all_pnl + pnlChange;

        // Today's PnL is computed from the market-open baseline
        const baseline = strat.all_pnl_at_market_open !== undefined ? parseFloat(strat.all_pnl_at_market_open) : strat.initial_all_pnl;
        strat.today_pnl = strat.all_pnl - baseline;

        // Accumulate portfolio metrics
        totalPnl += strat.all_pnl;
        const baseCap = strat.template.capital_required ? parseFloat(strat.template.capital_required) : 0;
        const multiplier = strat.minimum_multiple ? parseFloat(strat.minimum_multiple) : 1;
        totalCapital += baseCap * multiplier;
        todayPnlSum += strat.today_pnl;

        if (strat.status === 'Active' || strat.status === 'Live-Entered') {
            activeCount++;
        }
    });

    // Sort by Total PNL descending for rendering
    const displayStrategies = [...currentStrategies];
    displayStrategies.sort((a, b) => (b.all_pnl || 0) - (a.all_pnl || 0));

    // Populate Deployed Strategies Table
    const tableBody = document.querySelector('#strategyTable tbody');
    tableBody.innerHTML = '';

    // Build broker color map for broker cell background grouping
    const brokerColorPalette = [
        'rgba(99, 102, 241, 0.35)',   // indigo
        'rgba(16, 185, 129, 0.35)',   // emerald
        'rgba(245, 158, 11, 0.35)',   // amber
        'rgba(236, 72, 153, 0.30)',   // pink
        'rgba(14, 165, 233, 0.35)',   // sky
        'rgba(168, 85, 247, 0.35)',   // purple
        'rgba(234, 179, 8, 0.30)',    // yellow
        'rgba(239, 68, 68, 0.30)',    // red
    ];
    const uniqueBrokers = [...new Set(displayStrategies.map(s => s.strategy_broker?.broker?.name || 'N/A'))];
    const brokerColorMap = {};
    uniqueBrokers.forEach((name, i) => {
        brokerColorMap[name] = brokerColorPalette[i % brokerColorPalette.length];
    });

    displayStrategies.forEach(strat => {
        const baseCap = strat.template.capital_required ? parseFloat(strat.template.capital_required) : 0;
        const multiplier = strat.minimum_multiple ? parseFloat(strat.minimum_multiple) : 1;
        const cap = baseCap * multiplier;
        const lastPnl = strat.last_pnl || 0;
        const currentPnl = strat.sum_of_pnl || 0;
        const totalPnlVal = strat.all_pnl || 0;
        const name = strat.template.name;
        const runCounter = strat.run_counter || 0;
        const brokerName = strat.strategy_broker?.broker?.name || 'N/A';
        const brokerBg = brokerColorMap[brokerName] || 'transparent';

        const tr = document.createElement('tr');
        
        let badgeColorClass = 'badge-neutral';
        const status = (strat.status || '').toLowerCase();
        if (status === 'active' || status === 'live-entered') {
            badgeColorClass = 'badge-success text-success-content';
        } else if (status === 'paused') {
            badgeColorClass = 'badge-warning text-warning-content';
        } else if (status === 'exited') {
            badgeColorClass = 'badge-neutral text-neutral-content';
        } else if (status === 'error' || status === 'blocked') {
            badgeColorClass = 'badge-error text-error-content';
        } else {
            badgeColorClass = 'badge-info text-info-content';
        }

        tr.innerHTML = `
            <td><strong>${name} (${runCounter})</strong></td>
            <td><span class="badge ${badgeColorClass}">${strat.status || 'Unknown'}</span></td>
            <td class="broker-cell" style="background-color:${brokerBg}">${brokerName}</td>
            <td>${formatINR(cap)}</td>
            <td class="${totalPnlVal >= 0 ? 'positive' : 'negative'}"><strong>${formatINR(totalPnlVal)}</strong></td>
            <td class="${lastPnl >= 0 ? 'positive' : 'negative'}">${formatINR(lastPnl)}</td>
            <td class="${currentPnl >= 0 ? 'positive' : 'negative'}"><strong>${formatINR(currentPnl)}</strong></td>
        `;
        tableBody.appendChild(tr);
    });

    // Update Summary Cards
    document.getElementById('totalPnl').textContent = formatINR(totalPnl);
    document.getElementById('totalPnl').className = totalPnl >= 0 ? 'positive' : 'negative';
    
    document.getElementById('totalCapital').textContent = formatINR(totalCapital);
    document.getElementById('activeStrats').textContent = activeCount;
    
    const todayPnlPct = totalCapital > 0 ? (todayPnlSum / totalCapital) * 100 : 0;
    document.getElementById('todayPnl').innerHTML = `${formatINR(todayPnlSum)} <span class="text-sm font-semibold opacity-85 ml-2">(${todayPnlSum >= 0 ? '+' : ''}${todayPnlPct.toFixed(2)}%)</span>`;
    document.getElementById('todayPnl').className = 'stat-value text-2xl md:text-3xl font-extrabold ' + (todayPnlSum >= 0 ? 'positive' : 'negative');

    // Store latest Today's P&L for chart and snapshot synchronization
    latestTodayPnl = todayPnlSum;

    const pnlPct = totalCapital > 0 ? (totalPnl / totalCapital) * 100 : 0;
    document.getElementById('totalPnlPct').textContent = `${pnlPct.toFixed(2)}% Return on Capital`;
    document.getElementById('totalPnlPct').className = 'subtitle ' + (pnlPct >= 0 ? 'positive' : 'negative');
    
    console.log(`Recalculation complete. Today's Est. P&L: ${formatINR(todayPnlSum)}`);
}

function formatINR(num) {
    if (!num) return '₹0.00';
    return new Intl.NumberFormat('en-IN', {
        style: 'currency',
        currency: 'INR',
        maximumFractionDigits: 2
    }).format(num);
}

function renderMtmChart() {
    const ctx = document.getElementById('mtmChart').getContext('2d');
    
    if (mtmChart) {
        mtmChart.destroy();
    }

    const themeColors = getThemeColors();
    Chart.defaults.color = themeColors.text;
    Chart.defaults.font.family = "'Inter', sans-serif";

    const labels = mtmHistoryData.map(d => d.time);
    const dataPoints = mtmHistoryData.map(d => d.pnl);
    
    // Determine line color based on last data point
    const lastVal = dataPoints.length > 0 ? dataPoints[dataPoints.length - 1] : 0;

    // Collect Total P&L data values to compute min/max range
    const minVal = dataPoints.length > 0 ? Math.min(...dataPoints) : 0;
    const maxVal = dataPoints.length > 0 ? Math.max(...dataPoints) : 0;
    const range = maxVal - minVal;
    const buffer = range > 0 ? range * 0.1 : 1000;
    const rawMin = Math.min(minVal - buffer, -1000);
    const rawMax = Math.max(maxVal + buffer, 1000);
    
    // Round to nearest 5000 to keep grid lines and ticks clean
    const chartMin = Math.floor(rawMin / 5000) * 5000;
    const chartMax = Math.ceil(rawMax / 5000) * 5000;
    console.log(`Chart Min: ${chartMin}, Max: ${chartMax}`);

    // Update subtitle with latest value
    const subtitleEl = document.getElementById('mtmChartSubtitle');
    if (subtitleEl && dataPoints.length > 0) {
        subtitleEl.textContent = `Latest: ${formatINR(lastVal)} · ${dataPoints.length} data points`;
        subtitleEl.className = 'chart-subtitle text-xs font-semibold ' + (lastVal >= 0 ? 'positive' : 'negative');
    }

    // Set high/low MTM values on the main chart
    const mainHigh = dataPoints.length > 0 ? Math.max(...dataPoints) : 0;
    const mainLow = dataPoints.length > 0 ? Math.min(...dataPoints) : 0;
    const highEl = document.getElementById('mainChartHigh');
    const lowEl = document.getElementById('mainChartLow');
    if (highEl) {
        highEl.textContent = formatSignedINR(mainHigh);
        highEl.className = 'font-bold ' + (mainHigh >= 0 ? 'positive' : 'negative');
    }
    if (lowEl) {
        lowEl.textContent = formatSignedINR(mainLow);
        lowEl.className = 'font-bold ' + (mainLow >= 0 ? 'positive' : 'negative');
    }

    // Build datasets (Total P&L only)
    const datasets = [];

    datasets.push({
        label: "Total P&L",
        data: dataPoints,
        borderColor: (context) => {
            const chart = context.chart;
            const { ctx: chartCtx, chartArea, scales } = chart;
            if (!chartArea || !scales || !scales.y) return '#10b981';
            
            const yAxis = scales.y;
            const zero = yAxis.getPixelForValue(0);
            const top = chartArea.top;
            const bottom = chartArea.bottom;
            
            const gradient = chartCtx.createLinearGradient(0, top, 0, bottom);
            const zeroPos = (zero - top) / (bottom - top);
            
            if (zeroPos <= 0) {
                return '#f43f5e'; // Entirely negative
            } else if (zeroPos >= 1) {
                return '#10b981'; // Entirely positive
            } else {
                gradient.addColorStop(0, '#10b981');
                gradient.addColorStop(zeroPos, '#10b981');
                gradient.addColorStop(zeroPos, '#f43f5e');
                gradient.addColorStop(1, '#f43f5e');
                return gradient;
            }
        },
        borderWidth: 3,
        pointRadius: dataPoints.length > 60 ? 0 : 3,
        pointHoverRadius: 5,
        pointBackgroundColor: (context) => {
            const val = context.dataset.data[context.dataIndex];
            return val >= 0 ? '#10b981' : '#f43f5e';
        },
        pointBorderColor: (context) => {
            const val = context.dataset.data[context.dataIndex];
            return val >= 0 ? '#10b981' : '#f43f5e';
        },
        pointHoverBackgroundColor: (context) => {
            const val = context.dataset.data[context.dataIndex];
            return val >= 0 ? '#10b981' : '#f43f5e';
        },
        pointHoverBorderColor: (context) => {
            const val = context.dataset.data[context.dataIndex];
            return val >= 0 ? '#10b981' : '#f43f5e';
        },
        tension: 0.3,
        fill: true,
        backgroundColor: (context) => {
            const chart = context.chart;
            const { ctx: chartCtx, chartArea, scales } = chart;
            if (!chartArea || !scales || !scales.y) return 'rgba(16, 185, 129, 0.08)';
            
            const yAxis = scales.y;
            const zero = yAxis.getPixelForValue(0);
            const top = chartArea.top;
            const bottom = chartArea.bottom;
            
            const gradient = chartCtx.createLinearGradient(0, top, 0, bottom);
            const zeroPos = (zero - top) / (bottom - top);
            
            if (zeroPos <= 0) {
                gradient.addColorStop(0, 'rgba(244, 63, 94, 0.15)');
                gradient.addColorStop(1, 'rgba(244, 63, 94, 0.01)');
            } else if (zeroPos >= 1) {
                gradient.addColorStop(0, 'rgba(16, 185, 129, 0.15)');
                gradient.addColorStop(1, 'rgba(16, 185, 129, 0.01)');
            } else {
                gradient.addColorStop(0, 'rgba(16, 185, 129, 0.15)');
                gradient.addColorStop(zeroPos, 'rgba(16, 185, 129, 0.02)');
                gradient.addColorStop(zeroPos, 'rgba(244, 63, 94, 0.02)');
                gradient.addColorStop(1, 'rgba(244, 63, 94, 0.15)');
            }
            return gradient;
        }
    });

    mtmChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: datasets
        },
        options: {
            animation: false,
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    backgroundColor: 'rgba(15, 23, 42, 0.9)',
                    titleFont: { size: 13, family: 'Inter' },
                    bodyFont: { size: 14, family: 'Inter', weight: 'bold' },
                    padding: 12,
                    cornerRadius: 8,
                    callbacks: {
                        title: function(tooltipItems) {
                            return tooltipItems[0].label + ' IST';
                        },
                        label: function(context) {
                            return context.dataset.label + ': ' + formatINR(context.raw);
                        }
                    }
                }
            },
            scales: {
                y: {
                    min: chartMin,
                    max: chartMax,
                    grid: {
                        color: (context) => {
                            if (context.tick && context.tick.value === 0) {
                                  return themeColors.zeroLine;
                            }
                            return themeColors.grid;
                        },
                        lineWidth: (context) => {
                            if (context.tick && context.tick.value === 0) {
                                  return 1.5;
                            }
                            return 1;
                        },
                        drawBorder: false
                    },
                    ticks: {
                        color: themeColors.text,
                        callback: function(value) {
                            if (Math.abs(value) >= 1000) {
                                return '₹' + (value / 1000).toFixed(1) + 'k';
                            }
                            return '₹' + value;
                        }
                    }
                },
                x: {
                    grid: {
                        display: false
                    },
                    ticks: {
                        color: themeColors.text,
                        maxTicksLimit: 15,
                        maxRotation: 0
                    }
                }
            }
        }
    });

    // Render individual strategy cards in the lower section
    renderIndividualStrategyCharts();
}

function formatSignedINR(num) {
    const sign = num >= 0 ? '+' : '';
    return `${sign}${formatINR(num)}`;
}

function getDurationMinutes(historyData) {
    if (!historyData || historyData.length < 2) return 0;
    const startStr = historyData[0].time; // "HH:MM"
    const endStr = historyData[historyData.length - 1].time; // "HH:MM"
    const [startH, startM] = startStr.split(':').map(Number);
    const [endH, endM] = endStr.split(':').map(Number);
    let diff = (endH * 60 + endM) - (startH * 60 + startM);
    if (diff < 0) diff += 24 * 60;
    return diff;
}

let sparklineCharts = {};

function renderIndividualStrategyCharts() {
    const grid = document.getElementById('strategiesGrid');
    if (!grid) return;
    
    // Clear grid and destroy previous charts
    grid.innerHTML = '';
    Object.values(sparklineCharts).forEach(chart => {
        if (chart) chart.destroy();
    });
    sparklineCharts = {};
    
    const detailsEl = document.querySelector('details.collapse');
    if (detailsEl && !detailsEl.open) return;
    
    if (mtmHistoryData.length === 0) return;
    
    // Extract unique keys
    const strategyKeys = new Set();
    mtmHistoryData.forEach(pt => {
        if (pt.strategies) {
            Object.keys(pt.strategies).forEach(key => strategyKeys.add(key));
        }
    });
    
    strategyKeys.forEach((key) => {
        const colonIdx = key.indexOf(':');
        const stratId = colonIdx !== -1 ? key.substring(0, colonIdx) : '';
        const displayName = colonIdx !== -1 ? key.substring(colonIdx + 1) : key;
        
        // Extract strategy data points
        const stratData = mtmHistoryData.map(pt => {
            if (pt.strategies && pt.strategies[key] !== undefined) {
                return pt.strategies[key];
            }
            return null;
        }).filter(val => val !== null);
        
        const latestVal = stratData.length > 0 ? stratData[stratData.length - 1] : 0;
        const highVal = stratData.length > 0 ? Math.max(...stratData) : 0;
        const lowVal = stratData.length > 0 ? Math.min(...stratData) : 0;
        const duration = getDurationMinutes(mtmHistoryData);
        
        // Find capital for percentage return
        const stratObj = currentStrategies.find(s => s.id.toString() === stratId);
        let capital = 0;
        if (stratObj) {
            const baseCap = stratObj.template.capital_required ? parseFloat(stratObj.template.capital_required) : 0;
            const multiplier = stratObj.minimum_multiple ? parseFloat(stratObj.minimum_multiple) : 1;
            capital = baseCap * multiplier;
        }
        const pnlPct = capital > 0 ? (latestVal / capital) * 100 : 0;
        
        const card = document.createElement('div');
        const accentClass = latestVal >= 0 ? 'border-l-4 border-l-success' : 'border-l-4 border-l-error';
        card.className = `bg-base-100/40 backdrop-blur-md border border-base-content/10 rounded-xl p-4 flex flex-col gap-2 shadow-sm ${accentClass}`;
        card.id = `sparkline-card-${stratId}`;
        
        const valClass = latestVal >= 0 ? 'positive' : 'negative';
        const pctClass = pnlPct >= 0 ? 'positive' : 'negative';
        
        card.innerHTML = `
            <div class="flex justify-between items-start">
                <span class="text-xs font-bold opacity-80 max-w-[70%] truncate" title="${displayName}">${displayName}</span>
                <span class="text-xs font-bold ${pctClass}">${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%</span>
            </div>
            <div class="text-lg font-bold ${valClass} mt-0.5">${formatSignedINR(latestVal)}</div>
            <div class="h-[60px] w-full mt-1">
                <canvas id="canvas-${stratId}"></canvas>
            </div>
            <div class="flex justify-between items-center text-[10px] mt-1 font-semibold opacity-75">
                <span class="opacity-50 uppercase tracking-wider">${duration} MIN</span>
                <span>HIGH - <span class="positive">${formatSignedINR(highVal)}</span> · LOW - <span class="negative">${formatSignedINR(lowVal)}</span></span>
            </div>
        `;
        
        grid.appendChild(card);
        
        // Draw sparkline chart
        drawSparkline(`canvas-${stratId}`, stratData, latestVal >= 0, stratId);
    });
}

function drawSparkline(canvasId, data, isPositive, stratId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    
    const lineColor = isPositive ? '#10b981' : '#f43f5e';
    
    // Create fill gradient
    const gradient = ctx.createLinearGradient(0, 0, 0, 60);
    if (isPositive) {
        gradient.addColorStop(0, 'rgba(16, 185, 129, 0.15)');
        gradient.addColorStop(1, 'rgba(16, 185, 129, 0.01)');
    } else {
        gradient.addColorStop(0, 'rgba(244, 63, 94, 0.15)');
        gradient.addColorStop(1, 'rgba(244, 63, 94, 0.01)');
    }
    
    sparklineCharts[stratId] = new Chart(ctx, {
        type: 'line',
        data: {
            labels: new Array(data.length).fill(''),
            datasets: [{
                data: data,
                borderColor: lineColor,
                borderWidth: 1.5,
                pointRadius: 0,
                tension: 0.3,
                fill: true,
                backgroundColor: gradient
            }]
        },
        options: {
            animation: false,
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: { enabled: false }
            },
            scales: {
                x: { display: false },
                y: { display: false }
            }
        }
    });
}
}

function getBrokerShortcode(brokerName) {
    if (!brokerName) return "N/A";
    const mapping = {
        'Flattrade': 'FT',
        'Jainam Retail (XTS)': 'JR',
        'AC Agarwal Retail XTS': 'ACA'
    };
    for (const [name, code] of Object.entries(mapping)) {
        if (brokerName.toLowerCase().includes(name.toLowerCase()) || name.toLowerCase().includes(brokerName.toLowerCase())) {
            return code;
        }
    }
    // Clean and fallback
    const cleaned = brokerName.replace(/[^a-zA-Z]/g, '');
    return cleaned ? cleaned.substring(0, 3).toUpperCase() : 'BRK';
}

async function recordMtmSnapshot() {
    const todayPnl = latestTodayPnl;
    
    // Compile individual strategy P&Ls
    const strategiesPnl = {};
    currentStrategies.forEach(strat => {
        if (strat.template && strat.template.name) {
            const stratId = strat.id;
            const name = strat.template.name;
            const brokerName = strat.strategy_broker?.broker?.name || '';
            const shortcode = getBrokerShortcode(brokerName);
            const uniqueName = `${stratId}:${name} - ${shortcode}`;
            strategiesPnl[uniqueName] = strat.today_pnl || 0;
        }
    });
    
    try {
        await fetch('/api/record-mtm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                pnl: todayPnl,
                strategies: strategiesPnl
            })
        });
        console.log(`MTM snapshot recorded: ${formatINR(todayPnl)} with ${Object.keys(strategiesPnl).length} strategies.`);
    } catch (err) {
        console.error('Failed to record MTM snapshot:', err);
    }
}

async function fetchMarketHolidays() {
    try {
        const response = await fetch('/api/market-holidays');
        if (response.ok) {
            const data = await response.json();
            nseHolidaysSet = new Set(data);
            console.log(`Loaded ${nseHolidaysSet.size} market holidays from backend.`);
        }
    } catch (err) {
        console.error("Failed to fetch market holidays:", err);
    }
}

function isNseHolidayIST() {
    const now = new Date();
    const istDate = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }));
    const year = istDate.getFullYear();
    const month = String(istDate.getMonth() + 1).padStart(2, '0');
    const day = String(istDate.getDate()).padStart(2, '0');
    const dateStr = `${year}-${month}-${day}`;
    return nseHolidaysSet.has(dateStr);
}

function getTodayISTString() {
    const now = new Date();
    const istDate = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }));
    return `${istDate.getFullYear()}-${String(istDate.getMonth() + 1).padStart(2, '0')}-${String(istDate.getDate()).padStart(2, '0')}`;
}

async function loadHistoryDays() {
    try {
        const response = await fetch('/api/history-days');
        if (response.ok) {
            const days = await response.json();
            
            const select = document.getElementById('historyDaysSelect');
            if (!select) return;
            select.innerHTML = '';
            
            const todayStr = getTodayISTString();
            const uniqueDays = new Set(days);
            uniqueDays.add(todayStr);
            
            const sortedDays = Array.from(uniqueDays).sort().reverse();
            
            sortedDays.forEach(day => {
                const opt = document.createElement('option');
                opt.value = day;
                opt.textContent = day === todayStr ? `${day} (Today)` : day;
                select.appendChild(opt);
            });
            
            selectedMtmDate = todayStr;
            select.value = todayStr;
            
            select.addEventListener('change', async (e) => {
                selectedMtmDate = e.target.value;
                await fetchMtmHistory(selectedMtmDate);
            });
        }
    } catch (err) {
        console.error("Failed to load history days:", err);
    }
}

function downloadChartImage() {
    const canvas = document.getElementById('mtmChart');
    if (!canvas) return;

    const theme = localStorage.getItem('theme') || 'dark';
    const isDark = (theme === 'dark');
    const bgColor = isDark ? '#1e293b' : '#ffffff'; // slate-800 or white

    // Create temporary canvas to paint dynamic theme background
    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = canvas.width;
    tempCanvas.height = canvas.height;
    const tempCtx = tempCanvas.getContext('2d');

    tempCtx.fillStyle = bgColor;
    tempCtx.fillRect(0, 0, tempCanvas.width, tempCanvas.height);
    tempCtx.drawImage(canvas, 0, 0);

    const imageURI = tempCanvas.toDataURL("image/png");
    const link = document.createElement('a');
    link.download = `tradetron_mtm_${selectedMtmDate}.png`;
    link.href = imageURI;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

async function fetchMtmHistory(date) {
    if (!date) date = getTodayISTString();
    
    if (date === getTodayISTString() && isNseHolidayIST()) {
        mtmHistoryData = [
            { time: '09:15', pnl: 0 },
            { time: '15:30', pnl: 0 }
        ];
        renderMtmChart();
        return;
    }

    try {
        const response = await fetch(`/api/mtm-history?date=${date}`);
        if (response.ok) {
            mtmHistoryData = await response.json();
            
            // Sync last point with latestTodayPnl if market is closed
            if (date === getTodayISTString() && !isMarketOpenIST()) {
                if (mtmHistoryData.length === 0) {
                    mtmHistoryData.push({ time: '15:30', pnl: latestTodayPnl });
                } else {
                    const lastPoint = mtmHistoryData[mtmHistoryData.length - 1];
                    if (lastPoint.time === '15:30') {
                        lastPoint.pnl = latestTodayPnl;
                    } else {
                        mtmHistoryData.push({ time: '15:30', pnl: latestTodayPnl });
                    }
                }
            }
            
            renderMtmChart();
        }
    } catch (err) {
        console.error('Failed to fetch MTM history:', err);
    }
}

function isMarketOpenIST() {
    if (isNseHolidayIST()) return false;
    const now = new Date();
    
    // Convert current time to IST components
    const istDate = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }));
    
    const day = istDate.getDay(); // 0 = Sunday, 6 = Saturday
    if (day === 0 || day === 6) return false;

    const hour = istDate.getHours();
    const minute = istDate.getMinutes();

    // Market hours: 09:15 to 15:30
    if (hour < 9) return false;
    if (hour === 9 && minute < 15) return false;
    if (hour > 15) return false;
    if (hour === 15 && minute > 30) return false;

    return true;
}

// Timezone and status watch helper
function updateClockAndStatus() {
    const now = new Date();
    // Convert current time to IST components
    const options = { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
    const istTimeStr = now.toLocaleTimeString('en-US', options);
    
    // Update digital watch clock text
    const clockTextEl = document.querySelector('#watchBadge .clock-text');
    if (clockTextEl) {
        clockTextEl.textContent = `${istTimeStr} IST`;
    }
    
    // Check if market is open
    const open = isMarketOpenIST();
    const badge = document.getElementById('watchBadge');
    if (!badge) return;
    const statusText = badge.querySelector('.status-text');
    
    if (open) {
        if (!badge.classList.contains('badge-success')) {
            badge.className = 'badge badge-lg badge-success gap-2 py-4 px-4 border border-base-content/10 text-success-content';
            if (statusText) statusText.textContent = 'Live · 5s';
        }
    } else {
        if (!badge.classList.contains('badge-neutral')) {
            badge.className = 'badge badge-lg badge-neutral gap-2 py-4 px-4 border border-base-content/10 text-neutral-content';
            if (statusText) statusText.textContent = 'Closed';
        }
    }
}

async function fetchIndices() {
    try {
        const response = await fetch('/api/live-indices');
        if (response.ok) {
            const data = await response.json();
            updateIndexDOM('idxNifty', data.NIFTY);
            updateIndexDOM('idxSensex', data.SENSEX);
            updateIndexDOM('idxBankNifty', data.BANK_NIFTY);
            updateIndexDOM('idxIndiaVix', data.INDIA_VIX);
        }
    } catch (err) {
        console.error("Failed to fetch live indices:", err);
    }
}

function updateIndexDOM(elemId, data) {
    const el = document.getElementById(elemId);
    if (!el || !data) return;
    
    const valEl = el.querySelector('.index-val');
    const changeEl = el.querySelector('.index-change');
    const rowEl = el.querySelector('.index-row');
    if (!valEl || !changeEl) return;
    
    // Format price with comma
    const priceFormatted = new Intl.NumberFormat('en-IN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(data.price);
    
    valEl.textContent = priceFormatted;
    
    // Format change
    const sign = data.change >= 0 ? '+' : '';
    const changeFormatted = new Intl.NumberFormat('en-IN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(data.change);
    
    const pctFormatted = data.pct.toFixed(2);
    changeEl.textContent = `${sign}${changeFormatted} (${sign}${pctFormatted}%)`;
    
    // Apply styling class based on value
    if (rowEl) {
        if (data.change >= 0) {
            rowEl.className = 'index-row positive';
        } else {
            rowEl.className = 'index-row negative';
        }
    }
}

function getThemeColors() {
    const theme = localStorage.getItem('theme') || 'dark';
    const isDark = (theme === 'dark');
    return {
        text: isDark ? '#94a3b8' : '#475569',
        grid: isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)',
        zeroLine: isDark ? 'rgba(255, 255, 255, 0.25)' : 'rgba(0, 0, 0, 0.2)'
    };
}
