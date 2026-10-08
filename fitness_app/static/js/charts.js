/**
 * Chart rendering using Chart.js
 *
 * To add a new chart: give the <canvas> an id, add a renderer function here, and
 * add a block at the bottom that fetches its data and calls the renderer. The
 * pattern is identical for every chart on the site.
 */

// Chart.js CDN - load in base.html
// <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>

// Chart instances are kept so a toggle can re-render with different data
// without stacking duplicate charts on the same canvas.
const chartRegistry = {};

/**
 * Human-readable names for measurement sources, matching the labels used on the
 * profile page so a reading is labelled the same way everywhere.
 */
const SOURCE_LABELS = {
    manual: 'Manual entry',
    wii_fit: 'Wii Fit',
    technogym: 'Technogym',
    health_connect: 'Health Connect',
};

function sourceLabel(source) {
    return SOURCE_LABELS[source] || (source || 'unknown').replace(/_/g, ' ');
}

/**
 * Destroy any existing chart on a canvas before drawing a new one.
 * Without this, re-rendering on a toggle draws on top of the old chart.
 */
function clearChart(canvasId) {
    if (chartRegistry[canvasId]) {
        chartRegistry[canvasId].destroy();
        delete chartRegistry[canvasId];
    }
}

/**
 * Build a tooltip label showing the value, source and time.
 * A reading the user set aside is marked so it is never confused with an
 * active one.
 */
function measurementTooltip(context) {
    const point = context.dataset.data[context.dataIndex];
    if (point && typeof point === 'object' && point.meta) {
        const time = point.meta.time ? ` at ${point.meta.time}` : '';
        const setAside = point.meta.superseded ? ' (set aside)' : '';
        return `${point.meta.value}${point.meta.unit ? ' ' + point.meta.unit : ''}` +
               ` — ${sourceLabel(point.meta.source)}${time}${setAside}`;
    }
    return context.formattedValue;
}

/** Colour used for readings the user has chosen to ignore. */
const SET_ASIDE_COLOUR = '#c4c4c4';

/**
 * Colours for the two body measurement charts.
 *
 * Weight and BMI are plotted the same way, so they share one renderer and differ
 * only in colour and unit. Adding a third measurement chart therefore means one
 * more entry here, not another copy of this function.
 */
const MEASUREMENT_STYLES = {
    weight: { unit: 'kg', label: 'Weight (kg)', axis: 'Weight (kg)', rgb: '37, 99, 235' },
    bmi:    { unit: '',    label: 'BMI',         axis: 'BMI',         rgb: '22, 163, 74' },
};

/**
 * Shared options for the body measurement charts.
 *
 * @param {string} yTitle  Label for the value axis.
 */
function measurementChartOptions(yTitle) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        // Points share labels when a day has several readings, so hover needs to
        // pick the single nearest point rather than every point on that column.
        interaction: { mode: 'nearest', intersect: true },
        plugins: {
            legend: { display: false },
            tooltip: {
                callbacks: { label: measurementTooltip }
            }
        },
        scales: {
            y: {
                // Never start at zero: a weight chart anchored at 0 compresses
                // every meaningful change into a flat line.
                beginAtZero: false,
                title: { display: true, text: yTitle }
            },
            x: {
                title: { display: true, text: 'Date' }
            }
        }
    };
}

/**
 * Convert a chart payload into points that carry their own metadata, so the
 * tooltip can show the source without a second lookup.
 *
 * @param {object} payload  Response from /api/charts/weight or /bmi.
 * @param {string} unit     Unit suffix for the tooltip ('' for BMI).
 */
function toPoints(payload, unit) {
    // Plain guards instead of ?. / ?? so the measurement charts keep working
    // on older phone browsers (the stats page's inline chart uses no modern
    // syntax, which is why it kept drawing where these charts did not).
    var sources = payload.sources || [];
    var setAsideFlags = payload.superseded || [];
    var times = payload.times || [];
    return payload.values.map(function (value, i) {
        return {
            y: value,
            meta: {
                value: value,
                unit: unit,
                source: sources[i],
                superseded: setAsideFlags[i] === true,
                time: times[i] != null ? times[i] : null
            }
        };
    });
}

/**
 * Draw a body measurement line chart.
 *
 * Readings the user has set aside are still plotted when the "show readings
 * I've set aside" toggle is on, but drawn hollow and grey so they read as
 * "recorded but not in use" rather than as part of the current trend.
 *
 * @param {string} canvasId      Id of the canvas to draw on.
 * @param {object} data          API payload for this measurement type.
 * @param {string} measurementType  Key into MEASUREMENT_STYLES.
 * @returns {object|null} The Chart instance, or null if the canvas is absent.
 */
function createMeasurementChart(canvasId, data, measurementType) {
    clearChart(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;

    const style = MEASUREMENT_STYLES[measurementType];
    if (!style) {
        console.error(`No style defined for measurement type "${measurementType}"`);
        return null;
    }

    // The API always sends this array, but default it so a partial payload
    // cannot throw and leave the page with a blank canvas. Plain || rather
    // than ?? for older phone browsers (see toPoints).
    const setAside = data.superseded || [];

    chartRegistry[canvasId] = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.labels,
            datasets: [{
                label: style.label,
                data: toPoints(data, style.unit),
                borderColor: `rgb(${style.rgb})`,
                backgroundColor: `rgba(${style.rgb}, 0.1)`,
                tension: 0.1,
                fill: true,
                pointRadius: 4,
                pointHoverRadius: 6,
                // Grey the line segment leading into any set-aside point.
                segment: {
                    borderColor: segment =>
                        setAside[segment.p1DataIndex]
                            ? SET_ASIDE_COLOUR
                            : `rgb(${style.rgb})`
                },
                pointBackgroundColor: setAside.map(s =>
                    s ? '#ffffff' : `rgb(${style.rgb})`),
                pointBorderColor: setAside.map(s =>
                    s ? SET_ASIDE_COLOUR : `rgb(${style.rgb})`),
                // A diamond reads as "not in use" more clearly than a hollow
                // circle, which just looks like a hover state.
                pointStyle: setAside.map(s => s ? 'rectRot' : 'circle'),
            },
            // Weight goal, when set: a dashed target line across the chart.
            // Plain numbers, so the shared tooltip falls back to the value.
            ...(data.goal != null ? [{
                label: 'Goal',
                data: data.labels.map(() => data.goal),
                borderColor: '#16a34a',
                borderDash: [6, 4],
                borderWidth: 2,
                pointRadius: 0,
                pointHoverRadius: 0,
                fill: false,
            }] : [])]
        },
        options: measurementChartOptions(style.axis)
    });

    return chartRegistry[canvasId];
}

/** Weight over time. Thin wrapper so page code stays readable. */
function createWeightChart(canvasId, data) {
    return createMeasurementChart(canvasId, data, 'weight');
}

/** BMI over time. Thin wrapper so page code stays readable. */
function createBMIChart(canvasId, data) {
    return createMeasurementChart(canvasId, data, 'bmi');
}

/**
 * Create a bar chart for activity duration over time
 */
function createActivityChart(canvasId, data) {
    clearChart(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    chartRegistry[canvasId] = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.labels,
            datasets: [{
                label: 'Duration (minutes)',
                data: data.durations.map(d => Math.round(d / 60)),
                backgroundColor: 'rgba(37, 99, 235, 0.7)',
                borderColor: 'rgb(37, 99, 235)',
                borderWidth: 1,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: {
                    display: true,
                    text: 'Activity Duration'
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Duration (minutes)'
                    }
                },
                x: {
                    title: {
                        display: true,
                        text: 'Date'
                    }
                }
            }
        }
    });
}

/**
 * Create a bar chart for activity calories over time
 */
function createCaloriesChart(canvasId, data) {
    clearChart(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    chartRegistry[canvasId] = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.labels,
            datasets: [{
                label: 'Calories',
                data: data.calories,
                backgroundColor: 'rgba(220, 38, 38, 0.7)',
                borderColor: 'rgb(220, 38, 38)',
                borderWidth: 1,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: {
                    display: true,
                    text: 'Calories Burned'
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Calories'
                    }
                },
                x: {
                    title: {
                        display: true,
                        text: 'Date'
                    }
                }
            }
        }
    });
}

/**
 * Fetch a body measurement series and draw it, honouring the "show readings
 * I've set aside" toggle. A failed load writes an explanation next to the
 * canvas instead of leaving it silently blank — an empty chart with no
 * message reads as "no data" when the truth may be "could not load".
 */
function loadMeasurementChart(canvasId, endpoint, renderer) {
    const toggle = document.getElementById(`${canvasId}-include-superseded`);
    const includeSuperseded = toggle && toggle.checked;

    // Guard: without the chart library (blocked script, corrupt file),
    // say so once rather than throwing on every chart.
    if (typeof Chart === 'undefined') {
        chartError(canvasId, 'Charts unavailable: the chart library did not load.');
        return;
    }

    fetch(`${endpoint}?include_superseded=${includeSuperseded}`)
        .then(response => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
        })
        .then(data => {
            clearChartError(canvasId);
            if (!data.labels || !data.labels.length) {
                chartError(canvasId, 'No readings to plot yet.');
                return;
            }
            // A throw inside the renderer would otherwise leave a blank
            // canvas with no explanation. Surface it instead — the message
            // names the cause so it can be reported and fixed.
            try {
                renderer(canvasId, data);
            } catch (err) {
                console.error(`Error drawing ${endpoint}:`, err);
                chartError(canvasId, `Could not draw chart: ${err.message || err}`);
            }
        })
        .catch(error => {
            console.error(`Error loading ${endpoint}:`, error);
            chartError(canvasId, 'Could not load chart data.');
        });
}

/** Show an inline message beside a canvas that failed to draw. */
function chartError(canvasId, message) {
    clearChartError(canvasId);
    const canvas = document.getElementById(canvasId);
    if (!canvas || !canvas.parentElement) return;
    const note = document.createElement('p');
    note.className = 'text-muted chart-error';
    note.setAttribute('data-chart-error-for', canvasId);
    note.textContent = message;
    canvas.parentElement.appendChild(note);
}

/** Remove a previous load message before a fresh attempt. */
function clearChartError(canvasId) {
    document.querySelectorAll(`[data-chart-error-for="${canvasId}"]`).forEach(el => el.remove());
}

/**
 * Load and render all charts on the page
 */
document.addEventListener('DOMContentLoaded', function() {

    // Weight chart, with its set-aside toggle
    if (document.getElementById('weight-chart')) {
        loadMeasurementChart('weight-chart', '/api/charts/weight', createWeightChart);

        const toggle = document.getElementById('weight-include-superseded');
        if (toggle) {
            toggle.addEventListener('change', () =>
                loadMeasurementChart('weight-chart', '/api/charts/weight', createWeightChart));
        }
    }

    // BMI chart, with its set-aside toggle
    if (document.getElementById('bmi-chart')) {
        loadMeasurementChart('bmi-chart', '/api/charts/bmi', createBMIChart);

        const toggle = document.getElementById('bmi-include-superseded');
        if (toggle) {
            toggle.addEventListener('change', () =>
                loadMeasurementChart('bmi-chart', '/api/charts/bmi', createBMIChart));
        }
    }

    // Activity charts, reloaded by the timeframe tabs (30 days default).
    let activityDays = 30;

    function loadActivityCharts() {
        fetch(`/api/charts/activities?days=${activityDays}`)
            .then(response => response.json())
            .then(data => {
                if (document.getElementById('activity-chart')) {
                    createActivityChart('activity-chart', data);
                }
            })
            .catch(error => console.error('Error loading activity data:', error));

        fetch(`/api/charts/activities?days=${activityDays}`)
            .then(response => response.json())
            .then(data => {
                if (document.getElementById('calories-chart')) {
                    createCaloriesChart('calories-chart', data);
                }
            })
            .catch(error => console.error('Error loading calories data:', error));
    }

    if (document.getElementById('activity-chart') || document.getElementById('calories-chart')) {
        loadActivityCharts();

        document.querySelectorAll('#timeframe-tabs .chip').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('#timeframe-tabs .chip').forEach(
                    other => other.classList.remove('active'));
                btn.classList.add('active');
                activityDays = parseInt(btn.getAttribute('data-days'), 10) || 30;
                loadActivityCharts();
            });
        });
    }
});