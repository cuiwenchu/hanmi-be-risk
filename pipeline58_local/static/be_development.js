(function () {
  "use strict";

  const mediaDefinitions = [
    ["ph1.2", "pH 1.2"],
    ["ph4.5", "pH 4.5"],
    ["ph6.8", "pH 6.8"],
    ["fassif", "FaSSIF"],
    ["fessif", "FeSSIF"],
  ];

  function injectStyles() {
    if ($("#be-development-style")) return;
    const style = document.createElement("style");
    style.id = "be-development-style";
    style.textContent = `
      .development-evidence{min-width:0;overflow:hidden;border:1px solid #cadadd;background:#f8faf9;border-radius:8px;padding:16px}
      .development-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
      .development-score{min-width:94px;padding:9px 12px;border:1px solid #c9dadd;border-radius:8px;background:#fff;text-align:center}
      .development-score strong,.development-score small{display:block}.development-score strong{font-size:20px;color:#215d6a}
      .development-steps{min-width:0;display:grid;gap:10px;margin-top:14px}
      .development-steps details{min-width:0;border:1px solid #d7e1e1;border-radius:8px;background:#fff;overflow:hidden}
      .development-steps summary{cursor:pointer;padding:12px 14px;font-weight:800;color:#203b43;list-style:none}
      .development-steps summary::-webkit-details-marker{display:none}
      .development-steps summary::after{content:"+";float:right;color:#527078}.development-steps details[open] summary::after{content:"-"}
      .dev-body{min-width:0;padding:0 14px 14px}.dev-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
      .dev-grid.two{grid-template-columns:repeat(2,minmax(0,1fr))}
      .dev-row{display:grid;grid-template-columns:1.1fr .8fr repeat(6,.7fr) 36px;gap:7px;align-items:end;padding:9px 0;border-bottom:1px solid #edf1f1}
      .dev-api-row{grid-template-columns:1.1fr 1fr 1fr repeat(7,.65fr) 36px;min-width:1050px}
      .dev-scroll{width:100%;min-width:0;max-width:100%;overflow-x:auto}.dev-row input,.dev-row select{min-width:0}
      .dev-row .remove{height:42px}.dev-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:10px}
      .dev-media{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
      .dev-medium{border:1px solid #dce5e5;border-radius:8px;padding:11px;background:#fbfcfc}
      .dev-medium h4{margin:0 0 8px}.dev-medium textarea{min-height:92px}
      .dev-result{margin-top:14px;border-top:1px solid #d7e1e1;padding-top:14px}
      .dev-stage-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
      .dev-stage{padding:9px;border:1px solid #dce5e5;border-radius:7px;background:#fff}
      .dev-stage strong,.dev-stage small{display:block}.dev-stage i{display:block;height:5px;margin-top:7px;border-radius:5px;background:#dfe9e9;overflow:hidden}
      .dev-stage i::before{content:"";display:block;height:100%;width:var(--w);background:#2b7280}
      .dev-result-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}
      .dev-result-panel{border:1px solid #dce5e5;border-radius:8px;padding:11px;background:#fff}
      .dev-missing{margin:8px 0 0;padding-left:19px;color:#76530e}.dev-missing li{margin:5px 0}
      @media(max-width:980px){.development-head{display:block}.development-score{margin-top:10px}.dev-grid,.dev-grid.two,.dev-media,.dev-stage-grid,.dev-result-grid{grid-template-columns:1fr}.dev-row{min-width:900px}}
    `;
    document.head.appendChild(style);
  }

  function input(label, key, value = "", type = "text", step = "") {
    return `<label>${label}<input data-dev-field="${key}" type="${type}" ${step ? `step="${step}"` : ""} value="${esc(value)}"></label>`;
  }

  function lotRow(preset = {}) {
    const row = document.createElement("div");
    row.className = "dev-row";
    row.dataset.devLot = "";
    row.innerHTML = `
      ${input("批号", "lot_no", preset.lot_no)}
      ${input("市场", "market", preset.market)}
      ${input("含量 %", "assay_pct", preset.assay_pct, "number", "0.01")}
      ${input("总杂质 %", "total_impurities_pct", preset.total_impurities_pct, "number", "0.001")}
      ${input("硬度 N", "hardness_n", preset.hardness_n, "number", "0.1")}
      ${input("崩解 min", "disintegration_min", preset.disintegration_min, "number", "0.1")}
      ${input("水分 %", "water_pct", preset.water_pct, "number", "0.01")}
      ${input("片重 RSD%", "weight_rsd_pct", preset.weight_rsd_pct, "number", "0.01")}
      <button class="remove" type="button" title="删除">x</button>`;
    $(".remove", row).onclick = () => row.remove();
    $("#dev-lots").appendChild(row);
  }

  function apiRow(preset = {}) {
    const row = document.createElement("div");
    row.className = "dev-row dev-api-row";
    row.dataset.devApi = "";
    row.innerHTML = `
      ${input("API 成分", "name", preset.name)}
      ${input("盐型", "salt_form", preset.salt_form)}
      ${input("晶型", "polymorph", preset.polymorph)}
      ${input("D10 μm", "d10_um", preset.d10_um, "number", "0.1")}
      ${input("D50 μm", "d50_um", preset.d50_um, "number", "0.1")}
      ${input("D90 μm", "d90_um", preset.d90_um, "number", "0.1")}
      ${input("pH1.2 溶解度", "solubility_ph12", preset.solubility_ph12, "number", "0.0001")}
      ${input("pH4.5 溶解度", "solubility_ph45", preset.solubility_ph45, "number", "0.0001")}
      ${input("pH6.8 溶解度", "solubility_ph68", preset.solubility_ph68, "number", "0.0001")}
      ${input("比表面积", "surface_area_m2_g", preset.surface_area_m2_g, "number", "0.01")}
      <button class="remove" type="button" title="删除">x</button>`;
    $(".remove", row).onclick = () => row.remove();
    $("#dev-api-components").appendChild(row);
  }

  function mediaCard(key, label) {
    return `<div class="dev-medium" data-dev-medium="${key}"><h4>${label}</h4>
      <div class="dev-grid two">
        <label>Reference 曲线<small>time, released %</small><textarea data-dev-field="reference_profile"></textarea></label>
        <label>Test 曲线<small>time, released %</small><textarea data-dev-field="test_profile"></textarea></label>
      </div>
      <label>来源 / 条件<small>方法、转速、装置、批号</small><input data-dev-field="source"></label>
    </div>`;
  }

  function mountDevelopmentEvidence() {
    if ($("#development-evidence")) return;
    injectStyles();
    const section = document.createElement("div");
    section.id = "development-evidence";
    section.className = "section development-evidence";
    section.innerHTML = `
      <div class="development-head">
        <div><h3>原研开发证据包</h3><div class="copy">按开发顺序补全参比制剂身份、商业批次、API 特性、多介质溶出、工艺、模型校准和 BE 试验设计。未实测值请留空。</div></div>
        <div class="development-score"><small>开发准备度</small><strong id="dev-score">待运行</strong><small id="dev-level">尚未评估</small></div>
      </div>
      <div class="development-steps">
        <details open><summary>1. 参比制剂身份与 RLD 确认</summary><div class="dev-body"><div class="dev-grid" id="dev-identity">
          ${input("商品名", "brand_name")}
          ${input("持证商 / 生产企业", "manufacturer")}
          ${input("目标市场 / 国家", "market")}
          ${input("规格", "strength")}
          ${input("批准号 / 申请号", "application_no")}
          <label>参比地位<select data-dev-field="reference_status"><option value="">待核实</option><option value="RLD">RLD</option><option value="reference">指定参比制剂</option><option value="comparator">对照药</option></select></label>
          ${input("核实来源", "verification_source")}
          <label>身份核实<small>核实后才能作为固定基准</small><span class="tag"><input data-dev-field="verified" type="checkbox"> 已核实</span></label>
        </div></div></details>
        <details><summary>2. 参比制剂多批次实测（建议 ≥ 3 批）</summary><div class="dev-body"><div class="dev-scroll" id="dev-lots"></div><div class="dev-actions"><button class="ghost" id="dev-add-lot" type="button">添加批次</button></div></div></details>
        <details><summary>3. API 关键特性（复方按成分分别录入）</summary><div class="dev-body"><div class="dev-scroll" id="dev-api-components"></div><div class="dev-actions"><button class="ghost" id="dev-add-api" type="button">添加 API 成分</button></div></div></details>
        <details><summary>4. 多介质溶出曲线</summary><div class="dev-body"><div class="dev-media">${mediaDefinitions.map(([key, label]) => mediaCard(key, label)).join("")}</div></div></details>
        <details><summary>5. 处方与工艺参数范围</summary><div class="dev-body"><div class="dev-grid" id="dev-process">
          ${input("混合时间 min", "blend_time_min", "", "number", "0.1")}
          ${input("制粒终点 / 方式", "granulation_endpoint")}
          ${input("干燥温度 °C", "drying_temp_c", "", "number", "0.1")}
          ${input("干燥终点 LOD%", "lod_pct", "", "number", "0.01")}
          ${input("压片力下限 kN", "compression_min_kn", "", "number", "0.1")}
          ${input("压片力上限 kN", "compression_max_kn", "", "number", "0.1")}
          ${input("包衣增重 %", "coating_gain_pct", "", "number", "0.01")}
          ${input("目标硬度 N", "tablet_hardness_n", "", "number", "0.1")}
        </div></div></details>
        <details><summary>6. 模型实测校准</summary><div class="dev-body"><div class="dev-grid" id="dev-calibration">
          ${input("Reference Cmax", "reference_cmax", "", "number", "0.0001")}
          ${input("Test Cmax", "test_cmax", "", "number", "0.0001")}
          ${input("Reference AUC", "reference_auc", "", "number", "0.0001")}
          ${input("Test AUC", "test_auc", "", "number", "0.0001")}
          ${input("数据来源 / 试验编号", "source")}
          <label>校准启用<small>仅在四项实测值齐全时生效</small><span class="tag"><input data-dev-field="enabled" type="checkbox"> 使用实测校准评估</span></label>
        </div></div></details>
        <details><summary>7. BE 试验设计与成功概率</summary><div class="dev-body"><div class="dev-grid" id="dev-design">
          <label>给药状态<select data-dev-field="food_state"><option value="fasted">空腹</option><option value="fed">餐后</option><option value="both">空腹 + 餐后</option></select></label>
          <label>试验设计<select data-dev-field="study_design"><option value="2x2 crossover">2×2 交叉</option><option value="replicate">重复交叉</option><option value="parallel">平行设计</option></select></label>
          ${input("洗脱期 days", "washout_days", "7", "number", "1")}
          ${input("计划受试者数", "subject_n", "36", "number", "1")}
          ${input("预估 CV%", "cv_pct", "28", "number", "0.1")}
          ${input("脱落率 %", "dropout_pct", "10", "number", "0.1")}
          ${input("目标把握度 %", "target_power_pct", "80", "number", "1")}
        </div></div></details>
      </div>
      <div class="dev-result" id="development-result"><div class="hint">运行 BE 后显示各阶段准备度、缺失优先项、多介质 f2、模型误差和 BE 成功概率。</div></div>`;
    $("#reference-source-panel").insertAdjacentElement("afterend", section);
    $("#dev-add-lot").onclick = () => lotRow();
    $("#dev-add-api").onclick = () => apiRow();
    for (let index = 0; index < 3; index += 1) lotRow();
    apiRow();
  }

  function readFields(root) {
    const result = {};
    $$("[data-dev-field]", root).forEach((element) => {
      let value = element.type === "checkbox" ? element.checked : element.value.trim();
      if (element.type === "number") value = value === "" ? null : Number(value);
      result[element.dataset.devField] = value;
    });
    return result;
  }

  window.getDevelopmentEvidencePayload = function getDevelopmentEvidencePayload() {
    return {
      reference_identity: readFields($("#dev-identity")),
      reference_lots: $$("[data-dev-lot]").map(readFields),
      api_components: $$("[data-dev-api]").map(readFields),
      dissolution_media: $$("[data-dev-medium]").map((row) => ({
        medium: row.dataset.devMedium,
        label: $("h4", row).textContent,
        ...readFields(row),
      })),
      process_parameters: readFields($("#dev-process")),
      model_calibration: readFields($("#dev-calibration")),
      be_design: readFields($("#dev-design")),
    };
  };

  function setFields(root, values) {
    Object.entries(values || {}).forEach(([key, value]) => {
      const element = $(`[data-dev-field="${key}"]`, root);
      if (!element) return;
      if (element.type === "checkbox") element.checked = Boolean(value);
      else element.value = value ?? "";
    });
  }

  function resetRows(container, presets, builder) {
    container.innerHTML = "";
    presets.forEach(builder);
  }

  function loadSanofiEvidenceDemo() {
    setFields($("#dev-identity"), {
      brand_name: "依折麦布瑞舒伐他汀钙片 10 mg/10 mg",
      manufacturer: "SANOFI / 原研企业（待按目标市场核实）",
      market: "",
      strength: "10 mg / 10 mg",
      application_no: "",
      reference_status: "",
      verification_source: "FDA / EMA / PMDA / 当地参比制剂目录",
      verified: false,
    });
    resetRows($("#dev-lots"), [{}, {}, {}], lotRow);
    resetRows(
      $("#dev-api-components"),
      [
        { name: "依折麦布", salt_form: "游离型" },
        { name: "瑞舒伐他汀钙", salt_form: "钙盐" },
      ],
      apiRow
    );
    $$("[data-dev-medium]").forEach((row) => setFields(row, { reference_profile: "", test_profile: "", source: "" }));
    const ph68 = $('[data-dev-medium="ph6.8"]');
    setFields(ph68, {
      reference_profile: fieldValue("reference", "dissolution_profile", ""),
      test_profile: fieldValue("test", "dissolution_profile", ""),
      source: "系统示例曲线，必须用目标市场 RLD 实测数据替换",
    });
    setFields($("#dev-process"), {
      granulation_endpoint: "Test 直接压片（工艺范围待确认）",
      compression_min_kn: 12,
      compression_max_kn: 18,
    });
    setFields($("#dev-calibration"), {
      reference_cmax: "",
      test_cmax: "",
      reference_auc: "",
      test_auc: "",
      source: "",
      enabled: false,
    });
    setFields($("#dev-design"), {
      food_state: "fasted",
      study_design: "2x2 crossover",
      washout_days: 7,
      subject_n: 36,
      cv_pct: 28,
      dropout_pct: 10,
      target_power_pct: 80,
    });
    $("#dev-score").textContent = "待运行";
    $("#dev-level").textContent = "示例缺口待补全";
  }

  function stageCard(row) {
    const percent = Math.max(0, Math.min(100, Number(row.score) / Number(row.max) * 100));
    return `<div class="dev-stage"><small>${esc(row.label)}</small><strong>${fmt(row.score, 1)} / ${esc(row.max)}</strong><i style="--w:${percent}%"></i></div>`;
  }

  window.showDevelopmentEvidenceResult = function showDevelopmentEvidenceResult(data) {
    const result = data?.development_evidence;
    if (!result) return;
    $("#dev-score").textContent = `${fmt(result.readiness_score, 1)} / 100`;
    $("#dev-level").textContent = `准备度 ${result.readiness_level}`;
    const mediaRows = (result.media_results || []).map((row) => [
      esc(row.label),
      row.available ? fmt(row.f2, 2) : "数据不足",
      row.pass === true ? "通过" : row.pass === false ? "未通过" : "待补充",
      esc(row.source || "-"),
    ]);
    const design = result.be_design || {};
    const calibration = result.calibration || {};
    $("#development-result").innerHTML = `
      <div class="dev-stage-grid">${(result.stages || []).map(stageCard).join("")}</div>
      <div class="dev-result-grid">
        <div class="dev-result-panel"><h4>当前优先补充项</h4><ul class="dev-missing">${(result.missing_priorities || []).map((item) => `<li>${esc(item)}</li>`).join("") || "<li>关键开发数据已基本齐全。</li>"}</ul></div>
        <div class="dev-result-panel"><h4>BE 试验设计估算</h4>
          <div class="metrics">
            ${metric("当前成功概率", design.overall_success_probability_pct == null ? "-" : `${fmt(design.overall_success_probability_pct, 1)}%`, "AUC/Cmax 中较低值")}
            ${metric("有效受试者数", esc(design.effective_n ?? "-"), `计划 ${design.subject_n ?? "-"} / 脱落 ${fmt(design.dropout_pct, 1)}%`)}
            ${metric("建议入组数", esc(design.recommended_subject_n ?? ">120"), `目标把握度 ${Math.round(Number(design.target_power_pct) || 0)}%`)}
            ${metric("设计", esc(design.study_design || "-"), esc(design.food_state || "-"))}
          </div>
        </div>
      </div>
      <div class="dev-result-grid">
        <div class="dev-result-panel"><h4>多介质溶出 f2</h4><div class="table-wrap">${table(["介质", "f2", "判断", "来源"], mediaRows)}</div></div>
        <div class="dev-result-panel"><h4>模型实测校准</h4>${calibration.available ? `<div class="metrics">${metric("实测 AUC T/R", fmt(calibration.observed_auc_ratio, 3), `预测误差 ${fmt(calibration.auc_prediction_error_pct, 1)}%`)}${metric("实测 Cmax T/R", fmt(calibration.observed_cmax_ratio, 3), `预测误差 ${fmt(calibration.cmax_prediction_error_pct, 1)}%`)}</div>` : '<div class="hint">尚未导入完整的 Reference/Test Cmax 与 AUC 实测数据。</div>'}</div>
      </div>`;
  };

  mountDevelopmentEvidence();
  $("#load-sanofi-demo").addEventListener("click", loadSanofiEvidenceDemo);
  $("#clear-result").addEventListener("click", () => {
    $("#development-result").innerHTML = '<div class="hint">运行 BE 后显示各阶段准备度、缺失优先项、多介质 f2、模型误差和 BE 成功概率。</div>';
    $("#dev-score").textContent = "待运行";
    $("#dev-level").textContent = "尚未评估";
  });
})();
