(function () {
  "use strict";

  const toolConfig = {
    pksim: {
      label: "PK-Sim",
      short: "PK",
      className: "pksim",
      color: "#2f6fae",
      description: "导入 PK-Sim 导出的 Cmax、AUC、Tmax 和浓度-时间曲线，与本次 BE/PBBM 结果单独比较。",
    },
    gastroplus: {
      label: "GastroPlus",
      short: "GP",
      className: "gastroplus",
      color: "#c15f32",
      description: "导入 GastroPlus 模拟结果，与本次 BE/PBBM 的暴露指标、曲线和 BE 结论单独比较。",
    },
  };
  const crossState = {
    currentResult: null,
    runId: null,
    imported: { pksim: {}, gastroplus: {} },
    comparisons: { pksim: null, gastroplus: null },
  };

  function injectStyles() {
    if ($("#be-cross-validation-style")) return;
    const style = document.createElement("style");
    style.id = "be-cross-validation-style";
    style.textContent = `
      .cross-validation{min-width:0}
      .cross-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}
      .cross-head-copy{display:flex;gap:12px;align-items:flex-start}
      .cross-head-mark{display:grid;place-items:center;flex:0 0 42px;width:42px;height:42px;border:1px solid #cbd8da;border-radius:8px;background:#f6f9f9;color:#315c67;font-weight:950}
      .cross-head h3{margin:0 0 5px}.cross-head .copy{font-size:13px}
      .cross-summary{display:none;margin-top:14px;padding:13px;border:1px solid #cad8da;border-radius:8px;background:#f7faf9}
      .cross-summary.show{display:block}.cross-summary-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}
      .cross-summary-item{padding:10px 12px;border:1px solid #d6e0e1;border-radius:7px;background:#fff}
      .cross-summary-item small,.cross-summary-item strong{display:block}.cross-summary-item small{color:var(--muted);margin-bottom:4px}
      .cross-portals{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
      .cross-tool{min-width:0;border:1px solid #ccd8da;border-radius:8px;background:#fff;overflow:hidden}
      .cross-tool summary{display:flex;align-items:center;gap:12px;min-height:92px;padding:15px 16px;cursor:pointer;list-style:none}
      .cross-tool summary::-webkit-details-marker{display:none}.cross-tool summary::after{content:"展开";margin-left:auto;color:var(--muted);font-size:12px;font-weight:900}
      .cross-tool[open] summary::after{content:"收起"}
      .cross-tool.pksim{border-top:4px solid #2f6fae}.cross-tool.gastroplus{border-top:4px solid #c15f32}
      .cross-tool-icon{display:grid;place-items:center;flex:0 0 48px;width:48px;height:48px;border-radius:8px;color:#fff;font-size:14px;font-weight:1000}
      .pksim .cross-tool-icon{background:#2f6fae}.gastroplus .cross-tool-icon{background:#c15f32}
      .cross-tool-title{min-width:0}.cross-tool-title strong{display:block;font-size:18px;color:var(--ink)}
      .cross-tool-title span{display:block;margin-top:4px;color:var(--muted);font-size:12px;line-height:1.45}
      .cross-tool-state{display:inline-flex!important;width:max-content;margin-top:7px!important;padding:4px 7px;border-radius:5px;background:#eef3f4;color:#52686e!important;font-size:11px!important;font-weight:900}
      .cross-tool-body{padding:0 16px 16px;border-top:1px solid #dce4e5}
      .cross-import-bar{display:flex;gap:8px;flex-wrap:wrap;padding:14px 0 10px}
      .cross-import-bar button{padding:9px 11px;border-radius:7px;font-size:12px}
      .cross-import-note{margin-bottom:12px;padding:9px 11px;border-left:3px solid #879ba0;background:#f7f9f9;color:var(--muted);font-size:11px;line-height:1.55}
      .cross-fields{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px}
      .cross-fields label{font-size:12px}.cross-fields input,.cross-fields select{padding:9px 10px;border-radius:7px}
      .cross-curve-input{margin-top:10px}.cross-curve-input textarea{min-height:116px;border-radius:7px;font-family:"Cascadia Code",Consolas,monospace;font-size:12px}
      .cross-run{width:100%;margin-top:11px;border-radius:7px}
      .cross-result{display:none;margin-top:14px;padding-top:14px;border-top:1px solid #dce4e5}.cross-result.show{display:block}
      .cross-verdict{display:grid;grid-template-columns:auto 1fr;gap:11px;align-items:center;padding:12px;border:1px solid #d6e0e1;border-radius:8px;background:#f8faf9}
      .cross-verdict-mark{display:grid;place-items:center;min-width:82px;min-height:56px;border-radius:7px;color:#fff;font-weight:1000}
      .cross-verdict.consistent .cross-verdict-mark{background:#1e7f5c}.cross-verdict.partial .cross-verdict-mark{background:#a66612}
      .cross-verdict.conflict .cross-verdict-mark{background:#b13b2e}.cross-verdict.not_comparable .cross-verdict-mark{background:#66777d}
      .cross-verdict strong,.cross-verdict small{display:block}.cross-verdict small{margin-top:4px;color:var(--muted);line-height:1.5}
      .cross-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:10px}
      .cross-metric{padding:10px;border:1px solid #dce4e5;border-radius:7px;background:#fff;box-shadow:inset 3px 0 0 #899da2}
      .cross-metric.pass{box-shadow:inset 3px 0 0 var(--good)}.cross-metric.review{box-shadow:inset 3px 0 0 var(--warn)}.cross-metric.fail{box-shadow:inset 3px 0 0 var(--bad)}
      .cross-metric small,.cross-metric strong,.cross-metric span{display:block}.cross-metric small{color:var(--muted)}.cross-metric strong{margin:5px 0;font-size:14px}.cross-metric span{font-size:11px;color:#6e8085}
      .cross-chart-card{margin-top:10px;padding:11px;border:1px solid #dce4e5;border-radius:8px;background:#fff}
      .cross-chart-head{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:8px}
      .cross-chart-head strong{font-size:13px}.cross-chart-head span{font-size:11px;color:var(--muted)}
      .cross-chart{width:100%;height:260px;border:1px solid #e0e7e7;border-radius:7px;background:#fbfcfc}
      .cross-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:9px}
      .cross-stat{padding:9px;border-radius:7px;background:#f5f8f8}.cross-stat small,.cross-stat strong{display:block}.cross-stat small{color:var(--muted)}
      .cross-alerts{display:grid;gap:6px;margin-top:10px}.cross-alert{padding:8px 10px;border-radius:6px;background:#fff8ea;color:#76500f;font-size:11px;line-height:1.5}
      .cross-alert.blocker{background:#fff1ef;color:#8d342b}
      @media(max-width:980px){.cross-portals{grid-template-columns:1fr}.cross-fields{grid-template-columns:repeat(2,minmax(0,1fr))}.cross-summary-grid,.cross-metrics{grid-template-columns:1fr}}
      @media(max-width:560px){.cross-head{display:block}.cross-fields{grid-template-columns:1fr}.cross-tool summary{align-items:flex-start}.cross-verdict{grid-template-columns:1fr}.cross-stats{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  function field(tool, label, key, type = "number", step = "0.001", placeholder = "") {
    return `<label>${label}<input data-cross-field="${key}" type="${type}" ${step ? `step="${step}"` : ""} placeholder="${esc(placeholder)}"></label>`;
  }

  function toolPanel(tool) {
    const config = toolConfig[tool];
    return `
      <details class="cross-tool ${config.className}" data-cross-tool="${tool}">
        <summary>
          <span class="cross-tool-icon">${config.short}</span>
          <span class="cross-tool-title">
            <strong>与 ${config.label} 结果对比</strong>
            <span>${config.description}</span>
            <span class="cross-tool-state" data-cross-state>等待导入结果</span>
          </span>
        </summary>
        <div class="cross-tool-body">
          <div class="cross-import-bar">
            <input data-cross-file type="file" accept=".csv,.json,text/csv,application/json" hidden>
            <button class="ghost" data-cross-choose type="button">选择 CSV / JSON</button>
            <button class="ghost" data-cross-template type="button">下载导入模板</button>
            <button class="ghost" data-cross-clear type="button">清空此入口</button>
          </div>
          <div class="cross-import-note">导入文件不会改变当前 BE 结果。请确保剂量、给药途径和空腹/餐后条件与本次 BE 一致。</div>
          <div class="cross-fields">
            ${field(tool, "软件版本", "version", "text", "", "例如 12.0")}
            ${field(tool, "剂量 mg", "dose_mg")}
            <label>给药途径<select data-cross-field="route"><option value="">待确认</option><option value="po">口服</option><option value="iv">静脉</option></select></label>
            <label>进食条件<select data-cross-field="food_state"><option value="">待确认</option><option value="fasted">空腹</option><option value="fed">餐后</option><option value="both">空腹 + 餐后</option></select></label>
            ${field(tool, "Cmax T/R", "cmax_ratio")}
            ${field(tool, "AUC T/R", "auc_ratio")}
            ${field(tool, "Tmax 差异 h", "tmax_delta_h")}
            <label>外部 BE 结论<select data-cross-field="be_pass"><option value="">自动判断</option><option value="true">通过</option><option value="false">未通过</option></select></label>
            ${field(tool, "Cmax 90% CI 下限", "cmax_ci_low")}
            ${field(tool, "Cmax 90% CI 上限", "cmax_ci_high")}
            ${field(tool, "AUC 90% CI 下限", "auc_ci_low")}
            ${field(tool, "AUC 90% CI 上限", "auc_ci_high")}
          </div>
          <label class="cross-curve-input">浓度-时间曲线
            <small>每行：time_h, reference_conc, test_conc；至少填写 time_h 与 test_conc</small>
            <textarea data-cross-curve placeholder="0,0,0&#10;0.5,12.4,11.9&#10;1,20.3,19.6"></textarea>
          </label>
          <button class="cross-run" data-cross-run type="button">开始与 ${config.label} 对比</button>
          <div class="cross-result" data-cross-result></div>
        </div>
      </details>`;
  }

  function mountCrossValidation() {
    if ($("#be-cross-validation")) return;
    injectStyles();
    const section = document.createElement("section");
    section.id = "be-cross-validation";
    section.className = "section cross-validation";
    section.hidden = true;
    section.innerHTML = `
      <div class="cross-head">
        <div class="cross-head-copy">
          <div class="cross-head-mark">CV</div>
          <div>
            <h3>外部工具交叉验证</h3>
            <div class="copy">两个入口相互独立。先选择对应软件，再导入结果；系统不会把 PK-Sim 与 GastroPlus 数据混在一起。</div>
          </div>
        </div>
        <span class="tag">结果导入对比</span>
      </div>
      <div class="cross-summary" id="cross-summary"></div>
      <div class="cross-portals">${toolPanel("pksim")}${toolPanel("gastroplus")}</div>`;
    $("#comparison-dashboard").insertAdjacentElement("afterend", section);
    $$("[data-cross-tool]", section).forEach(bindToolPanel);
  }

  function bindToolPanel(panel) {
    const tool = panel.dataset.crossTool;
    const fileInput = $("[data-cross-file]", panel);
    $("[data-cross-choose]", panel).onclick = () => fileInput.click();
    fileInput.onchange = async () => {
      const file = fileInput.files?.[0];
      if (!file) return;
      try {
        const imported = await parseFile(file);
        imported.source_file = file.name;
        crossState.imported[tool] = imported;
        populatePanel(panel, imported);
        $("[data-cross-state]", panel).textContent = `已导入 ${file.name}`;
      } catch (error) {
        alert(`导入失败：${String(error.message || error)}`);
      } finally {
        fileInput.value = "";
      }
    };
    $("[data-cross-template]", panel).onclick = () => downloadTemplate(tool);
    $("[data-cross-clear]", panel).onclick = () => clearTool(tool);
    $("[data-cross-run]", panel).onclick = () => compareTool(tool);
  }

  function normalizeKey(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[()%]/g, "")
      .replace(/[\s./-]+/g, "_");
  }

  function parseCsv(text) {
    const rows = [];
    let row = [];
    let cell = "";
    let quoted = false;
    for (let index = 0; index < text.length; index += 1) {
      const char = text[index];
      if (char === '"') {
        if (quoted && text[index + 1] === '"') {
          cell += '"';
          index += 1;
        } else {
          quoted = !quoted;
        }
      } else if (char === "," && !quoted) {
        row.push(cell.trim());
        cell = "";
      } else if ((char === "\n" || char === "\r") && !quoted) {
        if (char === "\r" && text[index + 1] === "\n") index += 1;
        row.push(cell.trim());
        if (row.some((value) => value !== "")) rows.push(row);
        row = [];
        cell = "";
      } else {
        cell += char;
      }
    }
    row.push(cell.trim());
    if (row.some((value) => value !== "")) rows.push(row);
    if (rows.length < 2) throw new Error("CSV 至少需要表头和一行数据");
    const headers = rows[0].map(normalizeKey);
    if (headers[0] === "metric" && headers[1] === "value") {
      const result = {};
      rows.slice(1).forEach((values) => {
        if (values[0]) result[normalizeKey(values[0])] = values[1];
      });
      return normalizeImported(result);
    }
    const objects = rows.slice(1).map((values) =>
      Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""]))
    );
    const first = objects.find((item) => Object.values(item).some(Boolean)) || {};
    const result = { ...first };
    result.rows = objects;
    return normalizeImported(result);
  }

  function pick(source, aliases) {
    for (const alias of aliases) {
      const value = source?.[alias];
      if (value !== undefined && value !== null && value !== "") return value;
    }
    return "";
  }

  function numeric(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function normalizeCurveRows(rows) {
    if (!Array.isArray(rows)) return { reference_curve: [], test_curve: [] };
    const reference_curve = [];
    const test_curve = [];
    rows.forEach((raw) => {
      const row = Object.fromEntries(Object.entries(raw || {}).map(([key, value]) => [normalizeKey(key), value]));
      const time = numeric(pick(row, ["time_h", "time", "hour", "hours", "x"]));
      const reference = numeric(pick(row, ["reference_conc_ng_ml", "reference_conc", "reference", "ref_conc", "ref"]));
      const test = numeric(pick(row, ["test_conc_ng_ml", "test_conc", "test", "concentration", "conc_ng_ml", "conc", "value", "y"]));
      if (time === null || time < 0) return;
      if (reference !== null && reference >= 0) reference_curve.push({ time_h: time, conc_ng_ml: reference });
      if (test !== null && test >= 0) test_curve.push({ time_h: time, conc_ng_ml: test });
    });
    return { reference_curve, test_curve };
  }

  function normalizeImported(raw) {
    const source = raw?.data && typeof raw.data === "object" ? raw.data : raw || {};
    const normalized = Object.fromEntries(Object.entries(source).map(([key, value]) => [normalizeKey(key), value]));
    const curves = normalizeCurveRows(
      source.rows ||
      source.curve ||
      source.concentration_time_curve ||
      []
    );
    const directReference = normalizeCurveRows(source.reference_curve || []).test_curve;
    const directTest = normalizeCurveRows(source.test_curve || []).test_curve;
    return {
      version: pick(normalized, ["version", "software_version"]),
      project_name: pick(normalized, ["project_name", "project"]),
      dose_mg: numeric(pick(normalized, ["dose_mg", "dose"])),
      route: pick(normalized, ["route", "administration_route"]),
      food_state: pick(normalized, ["food_state", "food_condition", "condition"]),
      cmax_ratio: numeric(pick(normalized, ["cmax_ratio", "cmax_tr", "cmax_t_r"])),
      auc_ratio: numeric(pick(normalized, ["auc_ratio", "auc_tr", "auc_t_r"])),
      tmax_delta_h: numeric(pick(normalized, ["tmax_delta_h", "tmax_delta"])),
      cmax_ci_low: numeric(pick(normalized, ["cmax_ci_low", "cmax_90ci_low"])),
      cmax_ci_high: numeric(pick(normalized, ["cmax_ci_high", "cmax_90ci_high"])),
      auc_ci_low: numeric(pick(normalized, ["auc_ci_low", "auc_90ci_low"])),
      auc_ci_high: numeric(pick(normalized, ["auc_ci_high", "auc_90ci_high"])),
      be_pass: pick(normalized, ["be_pass", "decision", "be_result"]),
      reference_curve: directReference.length ? directReference : curves.reference_curve,
      test_curve: directTest.length ? directTest : curves.test_curve,
    };
  }

  async function parseFile(file) {
    const text = await file.text();
    if (file.name.toLowerCase().endsWith(".json") || file.type.includes("json")) {
      return normalizeImported(JSON.parse(text));
    }
    return parseCsv(text.replace(/^\uFEFF/, ""));
  }

  function populatePanel(panel, data) {
    $$("[data-cross-field]", panel).forEach((element) => {
      const value = data[element.dataset.crossField];
      if (value !== undefined && value !== null) element.value = String(value);
    });
    const times = new Map();
    (data.reference_curve || []).forEach((row) => {
      times.set(row.time_h, { time_h: row.time_h, reference: row.conc_ng_ml, test: "" });
    });
    (data.test_curve || []).forEach((row) => {
      const current = times.get(row.time_h) || { time_h: row.time_h, reference: "", test: "" };
      current.test = row.conc_ng_ml;
      times.set(row.time_h, current);
    });
    $("[data-cross-curve]", panel).value = [...times.values()]
      .sort((left, right) => left.time_h - right.time_h)
      .map((row) => `${row.time_h},${row.reference},${row.test}`)
      .join("\n");
  }

  function readCurve(text) {
    const rows = String(text || "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => line.split(/[\t,;]/).map((value) => value.trim()));
    const reference_curve = [];
    const test_curve = [];
    rows.forEach((values) => {
      const time = numeric(values[0]);
      const reference = numeric(values[1]);
      const test = numeric(values.length >= 3 ? values[2] : values[1]);
      if (time === null || time < 0) return;
      if (values.length >= 3 && reference !== null && reference >= 0) {
        reference_curve.push({ time_h: time, conc_ng_ml: reference });
      }
      if (test !== null && test >= 0) test_curve.push({ time_h: time, conc_ng_ml: test });
    });
    return { reference_curve, test_curve };
  }

  function panelPayload(tool) {
    const panel = $(`[data-cross-tool="${tool}"]`);
    const result = { ...crossState.imported[tool] };
    $$("[data-cross-field]", panel).forEach((element) => {
      let value = element.value.trim();
      if (element.type === "number") value = value === "" ? null : Number(value);
      if (element.dataset.crossField === "be_pass" && value !== "") value = value === "true";
      result[element.dataset.crossField] = value;
    });
    return { ...result, ...readCurve($("[data-cross-curve]", panel).value) };
  }

  async function compareTool(tool) {
    if (!crossState.currentResult) return alert("请先运行 BE 风险预测");
    const panel = $(`[data-cross-tool="${tool}"]`);
    const button = $("[data-cross-run]", panel);
    button.disabled = true;
    button.textContent = "正在计算一致性...";
    try {
      const response = await fetch("/api/v1/be/cross-validation/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tool,
          current_result: crossState.currentResult,
          current_request: payload(),
          external_result: panelPayload(tool),
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
      crossState.comparisons[tool] = body.data;
      renderResult(tool, body.data);
      $("[data-cross-state]", panel).textContent = `比较完成：${body.data.status_label}`;
      updateCombinedSummary();
    } catch (error) {
      alert(`对比失败：${String(error.message || error)}`);
    } finally {
      button.disabled = false;
      button.textContent = `开始与 ${toolConfig[tool].label} 对比`;
    }
  }

  function metricCard(row, tool) {
    const unit = row.unit ? ` ${row.unit}` : "";
    const delta = row.delta == null ? "缺少数据" : `${row.delta >= 0 ? "+" : ""}${fmt(row.delta, row.key === "tmax_delta_h" ? 2 : 3)}${unit}`;
    return `<div class="cross-metric ${row.state}">
      <small>${esc(row.label)}</small>
      <strong>${fmt(row.current, 3)} → ${fmt(row.external, 3)}${unit}</strong>
      <span>本系统 → ${esc(toolConfig[tool].label)} / 差值 ${esc(delta)}</span>
    </div>`;
  }

  function renderResult(tool, data) {
    const panel = $(`[data-cross-tool="${tool}"]`);
    const result = $("[data-cross-result]", panel);
    const testStats = data.test_curve_stats || {};
    const alerts = [
      ...(data.blockers || []).map((message) => `<div class="cross-alert blocker">${esc(message)}</div>`),
      ...(data.condition_warnings || []).map((message) => `<div class="cross-alert">${esc(message)}</div>`),
    ].join("");
    result.classList.add("show");
    result.innerHTML = `
      <div class="cross-verdict ${esc(data.status)}">
        <div class="cross-verdict-mark">${esc(data.status_label)}</div>
        <div><strong>${esc(data.tool_label)} 交叉验证结论</strong><small>${esc(data.message)} 外部结论依据：${esc(data.external_decision_basis)}</small></div>
      </div>
      <div class="cross-metrics">${(data.metrics || []).map((row) => metricCard(row, tool)).join("")}</div>
      <div class="cross-chart-card">
        <div class="cross-chart-head"><strong>Test 浓度-时间曲线叠加</strong><span>本系统 BE/PBBM vs ${esc(data.tool_label)}</span></div>
        <svg class="cross-chart" id="cross-chart-${tool}" viewBox="0 0 720 310" preserveAspectRatio="none"></svg>
        <div class="cross-stats">
          <div class="cross-stat"><small>曲线相关系数</small><strong>${fmt(testStats.correlation, 3)}</strong></div>
          <div class="cross-stat"><small>归一化 RMSE</small><strong>${testStats.nrmse_pct == null ? "-" : `${fmt(testStats.nrmse_pct, 1)}%`}</strong></div>
          <div class="cross-stat"><small>匹配时间点</small><strong>${esc(testStats.pairs ?? 0)}</strong></div>
        </div>
      </div>
      ${alerts ? `<div class="cross-alerts">${alerts}</div>` : ""}`;
    const internal = (data.curves?.internal_test || []).map((row) => ({ x: Number(row.time_h), y: Number(row.conc_ng_ml) }));
    const external = (data.curves?.external_test || []).map((row) => ({ x: Number(row.time_h), y: Number(row.conc_ng_ml) }));
    draw(
      `#cross-chart-${tool}`,
      [
        { name: "本系统 BE/PBBM Test", color: "#204d63", points: internal },
        { name: `${data.tool_label} Test`, color: toolConfig[tool].color, points: external },
      ],
      "Time",
      "ng/mL"
    );
  }

  function updateCombinedSummary() {
    const summary = $("#cross-summary");
    const entries = Object.entries(crossState.comparisons).filter(([, value]) => value);
    if (!entries.length) {
      summary.classList.remove("show");
      summary.innerHTML = "";
      return;
    }
    let overall = "等待另一工具";
    if (entries.length === 2) {
      const statuses = entries.map(([, value]) => value.status);
      overall = statuses.includes("conflict")
        ? "存在结论冲突"
        : statuses.includes("not_comparable")
        ? "部分不可比较"
        : statuses.every((status) => status === "consistent")
        ? "双工具一致"
        : "总体部分一致";
    }
    summary.classList.add("show");
    summary.innerHTML = `<div class="cross-summary-grid">
      <div class="cross-summary-item"><small>综合状态</small><strong>${esc(overall)}</strong></div>
      ${["pksim", "gastroplus"].map((tool) => {
        const result = crossState.comparisons[tool];
        return `<div class="cross-summary-item"><small>${toolConfig[tool].label}</small><strong>${esc(result?.status_label || "尚未比较")}</strong></div>`;
      }).join("")}
    </div>`;
  }

  function clearTool(tool) {
    const panel = $(`[data-cross-tool="${tool}"]`);
    crossState.imported[tool] = {};
    crossState.comparisons[tool] = null;
    $$("[data-cross-field]", panel).forEach((element) => {
      element.value = "";
    });
    $("[data-cross-curve]", panel).value = "";
    $("[data-cross-result]", panel).classList.remove("show");
    $("[data-cross-result]", panel).innerHTML = "";
    $("[data-cross-state]", panel).textContent = "等待导入结果";
    updateCombinedSummary();
  }

  function downloadTemplate(tool) {
    const content = [
      "version,dose_mg,route,food_state,cmax_ratio,auc_ratio,tmax_delta_h,cmax_ci_low,cmax_ci_high,auc_ci_low,auc_ci_high,be_pass,time_h,reference_conc_ng_ml,test_conc_ng_ml",
      "12.0,10,po,fasted,0.98,1.02,0.2,0.91,1.06,0.95,1.09,true,0,0,0",
      ",,,,,,,,,,,,0.5,12.4,11.9",
      ",,,,,,,,,,,,1,20.3,19.6",
      ",,,,,,,,,,,,2,17.2,16.8",
      ",,,,,,,,,,,,4,10.8,10.5",
    ].join("\n");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
    link.download = `${tool}_be_cross_validation_template.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  window.showCrossValidation = function showCrossValidation(data) {
    mountCrossValidation();
    const section = $("#be-cross-validation");
    section.hidden = false;
    const runId = data?.run_id || JSON.stringify(data?.summary || {});
    if (crossState.runId && crossState.runId !== runId) {
      crossState.comparisons = { pksim: null, gastroplus: null };
      $$("[data-cross-result]", section).forEach((element) => {
        element.classList.remove("show");
        element.innerHTML = "";
      });
      $$("[data-cross-state]", section).forEach((element) => {
        element.textContent = "BE 已更新，请重新比较";
      });
      updateCombinedSummary();
    }
    crossState.currentResult = data;
    crossState.runId = runId;
  };

  mountCrossValidation();
  $("#clear-result").addEventListener("click", () => {
    $("#be-cross-validation").hidden = true;
    crossState.currentResult = null;
    crossState.runId = null;
    crossState.comparisons = { pksim: null, gastroplus: null };
    updateCombinedSummary();
  });
})();
