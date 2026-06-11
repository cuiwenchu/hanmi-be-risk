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
        <div class="be-agent-title">
          <div class="be-agent-mark" aria-hidden="true">AI</div>
          <div>
            <h2>8. BE 优化 Agent</h2>
            <div class="copy">用中文说明研发目标，Agent 将基于本次 BE 结果准备受试制剂参数方案。</div>
          </div>
        </div>
        <span class="be-agent-status">已连接本次结果</span>
      </div>
      <div class="be-agent-workspace">
        <div class="be-agent-chat">
          <div class="be-agent-log" id="be-agent-log" aria-live="polite"></div>
          <div class="agent-quick-prompts" aria-label="常用优化目标">
            <button type="button" data-agent-prompt="让 Cmax 更接近参比，同时尽量保持 AUC 不变">Cmax 接近参比</button>
            <button type="button" data-agent-prompt="提高多介质溶出相似性和 f2">提高溶出 f2</button>
            <button type="button" data-agent-prompt="请小幅改善 Cmax、AUC 和溶出 f2，使其接近参比">降低失败风险</button>
          </div>
          <div class="agent-composer">
            <textarea id="agent-input" maxlength="2000" placeholder="请输入改善方向，例如：略微提高 Cmax，同时保持 AUC 不变"></textarea>
            <button class="btn" id="agent-send-btn" type="button">发送 ↑</button>
          </div>
          <div class="agent-composer-meta"><span>Ctrl + Enter 发送</span><span>不会自动应用或运行</span></div>
        </div>
        <aside class="agent-side">
          <div class="agent-side-title"><strong>参数方案</strong><span>Test only</span></div>
          <div class="agent-empty" id="agent-empty">提出优化目标后，此处将显示参数调整、BE/PBBM 预计算结果和应用按钮。</div>
          <div class="agent-proposal" id="agent-proposal" hidden>
            <div class="agent-proposal-head">
              <div>
                <h3>待应用参数建议</h3>
                <div class="copy">已按当前结果完成预计算。</div>
              </div>
              <button class="btn" id="agent-apply-btn" type="button" disabled>应用到受试制剂</button>
            </div>
            <div class="agent-preview" id="agent-preview"></div>
            <div id="agent-change-table"></div>
            <div class="agent-warnings" id="agent-warnings" hidden></div>
          </div>
          <div class="agent-safety">仅允许修改 Test 的处方与工艺参数。SMILES、盐型、晶型、pKa、logP、PPB、清除率及 API 供应商保持锁定。</div>
        </aside>
      </div>
      `;
    $(".shell").appendChild(section);
    $("#agent-send-btn").onclick = sendBeAgent;
    $("#agent-apply-btn").onclick = applyBeAgentProposal;
    $$("[data-agent-prompt]", section).forEach((button) => {
      button.onclick = () => {
        $("#agent-input").value = button.dataset.agentPrompt;
        $("#agent-input").focus();
      };
    });
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
    if (role === "system") {
      row.textContent = content;
    } else {
      const avatar = document.createElement("div");
      avatar.className = "agent-avatar";
      avatar.textContent = role === "user" ? "您" : "AI";
      const body = document.createElement("div");
      body.className = "agent-message-body";
      const name = document.createElement("div");
      name.className = "agent-message-name";
      name.textContent = role === "user" ? "张明团队" : "BE 优化 Agent";
      const message = document.createElement("div");
      message.className = "agent-message-content";
      message.textContent = content;
      body.append(name, message);
      row.append(avatar, body);
    }
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
    $("#agent-empty").hidden = false;
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
    const empty = $("#agent-empty");
    if (empty) empty.hidden = false;
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
    $("#agent-empty").hidden = true;
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
    loading.className = "agent-message assistant agent-loading";
    loading.innerHTML = '<div class="agent-avatar">AI</div><div class="agent-message-body"><div class="agent-message-name">BE 优化 Agent</div><div class="agent-message-content">正在分析目标并预计算参数</div></div>';
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
