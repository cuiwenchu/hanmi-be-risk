(function () {
  "use strict";

  function mountBeAgent() {
    if ($("#be-agent-card")) return;
    const section = document.createElement("section");
    section.className = "card be-agent-card";
    section.id = "be-agent-card";
    section.hidden = true;
    section.innerHTML = `
      <div class="be-agent-head">
        <div>
          <div class="kicker">Result-aware formulation assistant</div>
          <h2>8. BE 优化 Agent</h2>
          <div class="copy">BE 运行完成后，可用中文、韩文或英文说明改善方向。Agent 只准备受试制剂参数，不会自动应用或自动运行。</div>
        </div>
        <span class="be-agent-status">结果已连接</span>
      </div>
      <div class="be-agent-log" id="be-agent-log" aria-live="polite"></div>
      <div class="agent-proposal" id="agent-proposal" hidden>
        <div class="agent-proposal-head">
          <div>
            <h3>待应用参数建议</h3>
            <div class="copy">应用前已用当前 BE/PBBM 引擎进行预计算。</div>
          </div>
          <button class="btn" id="agent-apply-btn" type="button" disabled>应用到受试制剂</button>
        </div>
        <div class="agent-preview" id="agent-preview"></div>
        <div id="agent-change-table"></div>
        <div class="agent-warnings" id="agent-warnings" hidden></div>
      </div>
      <div class="agent-composer">
        <textarea id="agent-input" maxlength="2000" placeholder="例如：略微提高 Cmax，同时保持 AUC 不变"></textarea>
        <button class="btn" id="agent-send-btn" type="button">发送</button>
      </div>
      <div class="agent-safety">安全限制：仅修改 Test 受试制剂的允许参数。SMILES、盐型、晶型、pKa、logP、PPB、清除率及 API 供应商不会由 Agent 自动改写。</div>`;
    $(".shell").appendChild(section);
    $("#agent-send-btn").onclick = sendBeAgent;
    $("#agent-apply-btn").onclick = applyBeAgentProposal;
    $("#agent-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        sendBeAgent();
      }
    });
  }

  function agentAddMessage(role, text) {
    const content = String(text || "").trim();
    if (!content) return;
    agentMessages.push({ role, content });
    if (agentMessages.length > 12) agentMessages = agentMessages.slice(-12);
    const row = document.createElement("div");
    row.className = `agent-message ${role}`;
    row.textContent = content;
    $("#be-agent-log").appendChild(row);
    $("#be-agent-log").scrollTop = $("#be-agent-log").scrollHeight;
  }

  window.showBeAgent = function showBeAgent(data) {
    mountBeAgent();
    const card = $("#be-agent-card");
    const runId = data?.run_id || String(Date.now());
    card.hidden = false;
    if (agentResultRunId === runId) return;
    lastAgentProposal = null;
    $("#agent-proposal").hidden = true;
    $("#agent-apply-btn").disabled = true;
    if (agentResultRunId) {
      agentAddMessage("system", "新的 BE 结果已连接。后续建议将以本次结果重新计算。");
    } else {
      agentAddMessage(
        "assistant",
        "BE 结果已连接。请说明希望改善的方向，Agent 将根据当前结果准备 Test 参数调整方案，并在应用前显示预计算结果。"
      );
    }
    agentResultRunId = runId;
  };

  function clearBeAgent() {
    lastAgentProposal = null;
    agentMessages = [];
    agentResultRunId = null;
    const card = $("#be-agent-card");
    if (card) card.hidden = true;
    const log = $("#be-agent-log");
    if (log) log.innerHTML = "";
    const proposal = $("#agent-proposal");
    if (proposal) proposal.hidden = true;
    const input = $("#agent-input");
    if (input) input.value = "";
  }

  function agentMetric(label, current, predicted, digits = 3) {
    return `<div class="agent-preview-item"><small>${esc(label)}</small><strong>${fmt(current, digits)} &rarr; ${fmt(predicted, digits)}</strong></div>`;
  }

  function renderAgentProposal(data) {
    const patch = data.patch || {};
    const preview = data.preview || {};
    const current = preview.current || {};
    const predicted = preview.predicted || {};
    const changes = patch.changes || [];
    $("#agent-proposal").hidden = false;
    $("#agent-apply-btn").disabled = !changes.length;
    $("#agent-preview").innerHTML = preview.predicted
      ? [
          agentMetric("AUC T/R", current.auc_ratio, predicted.auc_ratio),
          agentMetric("Cmax T/R", current.cmax_ratio, predicted.cmax_ratio),
          agentMetric("溶出 f2", current.f2, predicted.f2, 2),
          `<div class="agent-preview-item"><small>BE Risk</small><strong>${esc(current.risk || "-")} &rarr; ${esc(predicted.risk || "-")}</strong></div>`,
        ].join("")
      : '<div class="copy">没有可预计算的参数变更。</div>';
    $("#agent-change-table").innerHTML = changes.length
      ? table(
          ["参数", "当前 Test", "建议值", "单位", "理由"],
          changes.map((item) => [
            esc(item.label || item.field),
            esc(item.current ?? "-"),
            esc(item.suggested ?? "-"),
            esc(item.unit || ""),
            esc(item.reason || ""),
          ])
        )
      : '<div class="hint">没有生成可应用的参数。请明确 Cmax、AUC、f2、溶出速度或接近参比等目标。</div>';
    const warnings = patch.warnings || [];
    $("#agent-warnings").hidden = !warnings.length;
    $("#agent-warnings").innerHTML = warnings.map((item) => `<div>${esc(item)}</div>`).join("");
  }

  async function sendBeAgent() {
    if (!lastResult) {
      alert("请先运行 BE 风险预测");
      return;
    }
    const input = $("#agent-input");
    const message = input.value.trim();
    if (!message) return;
    agentAddMessage("user", message);
    input.value = "";
    const button = $("#agent-send-btn");
    button.disabled = true;
    const loading = document.createElement("div");
    loading.className = "agent-message system";
    loading.textContent = "正在解释目标并预计算建议...";
    $("#be-agent-log").appendChild(loading);
    try {
      const response = await fetch("/api/v1/be/agent/suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          request: payload(),
          result: lastResult,
          conversation: agentMessages.slice(-6),
          previous_intent: lastAgentProposal?.intent || {},
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
      lastAgentProposal = body.data;
      agentAddMessage(
        "assistant",
        body.data.assistant_message || "参数建议已准备，请确认预计算结果后再应用。"
      );
      renderAgentProposal(body.data);
    } catch (error) {
      agentAddMessage("assistant", `Agent 请求失败：${String(error.message || error)}`);
    } finally {
      loading.remove();
      button.disabled = false;
      input.focus();
    }
  }

  function applyBeAgentProposal() {
    if (!lastAgentProposal) return;
    const allowed = new Set([
      "solubility_mg_ml",
      "particle_size_um",
      "dissolution_30min_pct",
      "compression_force_kn",
      "dissolution_profile",
      "release_type",
      "coating",
    ]);
    const patch = lastAgentProposal.patch || {};
    if (lastResult) resultBeforeAppliedSuggestion = lastResult;
    Object.entries(patch.fields || {}).forEach(([field, value]) => {
      if (allowed.has(field)) setv("test", field, value);
    });
    const names = {
      disintegrant: "交联羧甲纤维素钠",
      lubricant: "硬脂酸镁",
      solubilizer: "十二烷基硫酸钠",
      binder: "聚维酮K30",
    };
    (patch.excipients || []).forEach((item) => {
      if (names[item.role]) {
        setRoleAmount("test", item.role, item.name || names[item.role], item.amount_pct);
      }
    });
    $("#agent-apply-btn").disabled = true;
    $("#status").className = "status ok";
    $("#status").textContent =
      "Agent 建议已应用到 Test 受试制剂。请点击“运行 BE 风险预测”验证新结果。";
    agentAddMessage(
      "system",
      "建议值已写入 Test。系统未自动运行，请检查参数后手动运行 BE。"
    );
  }

  mountBeAgent();
  $("#clear-result").addEventListener("click", clearBeAgent);
})();
