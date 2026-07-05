const state = {
  activeTab: "highlight",
  lastResult: null,
  running: false,
};

const $ = (id) => document.getElementById(id);

const examples = {
  highlightVideos: JSON.stringify(["/path/to/video.mp4"], null, 2),
  demoInfo: JSON.stringify(
    [
      {
        start: 0,
        end: 3,
        folder: "开头素材",
        subtitle: "她刚推开门，就发现气氛不对",
      },
      {
        start: 3,
        end: 8,
        folder: "冲突素材",
        subtitle: "丈夫的沉默让她意识到事情没有那么简单",
      },
      {
        start: 8,
        end: 12,
        folder: "反转素材",
        subtitle: "下一秒，一个电话彻底改变了她的命运",
      },
    ],
    null,
    2
  ),
};

function parseJsonOrText(value) {
  const trimmed = value.trim();
  if (!trimmed) return "";
  try {
    return JSON.parse(trimmed);
  } catch {
    return trimmed;
  }
}

function getApiBase() {
  return $("apiBase").value.replace(/\/$/, "");
}

function setRunState(label, kind = "") {
  const el = $("runState");
  el.textContent = label;
  el.className = `run-state ${kind}`.trim();
}

function buildHighlightPayload() {
  const goalTimes = $("highlightGoalTimes").value
    .split(",")
    .map((item) => Number(item.trim()))
    .filter(Boolean);
  const cornerBadges = parseJsonOrText($("highlightCornerBadges").value);
  const tailFrames = parseJsonOrText($("highlightTailFrames").value);
  const textTemplate = parseJsonOrText($("highlightTextTemplate").value);
  const videoRatio = Number($("highlightVideoRatio").value || 1);
  const width = Number($("highlightWidth").value || 1080);
  const height = Number($("highlightHeight").value || 1920);
  const draftName = $("highlightDraftName").value.trim() || "高光剪辑";

  return {
    input_videos: parseJsonOrText($("highlightInputVideos").value),
    output_base_dir: $("highlightOutputDir").value.trim() || undefined,
    fps: Number($("highlightFps").value || 1),
    max_workers: Number($("highlightWorkers").value || 3),
    save_intermediate: $("highlightSaveIntermediate").checked,
    generate_draft: $("highlightGenerateDraft").checked,
    draft_output_dir: $("highlightDraftOutputDir").value.trim() || undefined,
    goal_times: goalTimes,
    base_config: {
      platform: $("highlightPlatform").value,
      material_base_path: $("highlightMaterialBasePath").value.trim() || "",
      video_ratio: videoRatio,
      global_speed: Number($("highlightGlobalSpeed").value || 1.1),
      overlay_path: Array.isArray(cornerBadges) ? cornerBadges : [],
      end_path: Array.isArray(tailFrames) ? tailFrames : [],
      width,
      height,
      fps: Number($("highlightDraftFps").value || 30),
      draft_name: draftName,
      allow_replace: true,
      global_texts: textTemplate || [],
    },
    config: {
      segment_vlm_workers: Number($("highlightSegmentWorkers").value || 3),
      selection_batch_size: Number($("highlightSelectionBatch").value || 5),
    },
  };
}

function buildCommentaryPayload() {
  const targetDuration = $("commentaryTargetDuration").value.trim();
  const cornerBadges = parseJsonOrText($("commentaryCornerBadges").value);
  const tailFrames = parseJsonOrText($("commentaryTailFrames").value);
  return {
    input_videos: parseJsonOrText($("commentaryInputVideos").value),
    demo_info: parseJsonOrText($("commentaryDemoInfo").value),
    text_template: parseJsonOrText($("commentaryTextTemplate").value),
    user_demand: $("commentaryDemand").value.trim(),
    work_dir: $("commentaryWorkDir").value.trim() || undefined,
    output_dir: $("commentaryOutputDir").value.trim() || undefined,
    draft_name: $("commentaryDraftName").value.trim() || "解说前贴",
    voice_type: $("commentaryVoice").value || "BV411_streaming",
    speed_ratio: Number($("commentarySpeed").value || 1.2),
    target_duration: targetDuration ? Number(targetDuration) : undefined,
    alignment_strategy: $("commentaryStrategy").value,
    corner_badge_files: Array.isArray(cornerBadges) ? cornerBadges : [],
    tail_frame_files: Array.isArray(tailFrames) ? tailFrames : [],
    config: {
      fps: Number($("commentaryFps").value || 0.5),
      overlap_threshold: Number($("commentaryOverlap").value || 0.5),
    },
  };
}

function updatePreviews() {
  $("highlightPreview").textContent = JSON.stringify(buildHighlightPayload(), null, 2);
  $("commentaryPreview").textContent = JSON.stringify(buildCommentaryPayload(), null, 2);
}

function addEvent(event) {
  const row = document.createElement("div");
  row.className = "event-row";

  const type = document.createElement("div");
  type.className = "event-type";
  type.textContent = event.event || event.type || "event";

  const body = document.createElement("div");
  body.className = "event-message";
  body.textContent = event.message || event.node || JSON.stringify(event);

  const meta = document.createElement("div");
  meta.className = "event-meta";
  const parts = [];
  if (event.node) parts.push(`node=${event.node}`);
  if (event.progress !== undefined && event.progress !== null) {
    parts.push(`progress=${Math.round(event.progress * 100)}%`);
  }
  if (event.task_id) parts.push(event.task_id);
  meta.textContent = parts.join(" | ");
  body.appendChild(meta);

  row.appendChild(type);
  row.appendChild(body);
  $("eventLog").appendChild(row);
  $("eventLog").scrollTop = $("eventLog").scrollHeight;
}

function setResult(result) {
  state.lastResult = result;
  $("resultBox").textContent = JSON.stringify(result, null, 2);
}

async function postSse(path, payload) {
  if (state.running) return;
  state.running = true;
  setRunState("Running", "running");
  setResult({ status: "running" });
  $("eventLog").innerHTML = "";

  try {
    const response = await fetch(`${getApiBase()}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok || !response.body) {
      throw new Error(`HTTP ${response.status}: ${await response.text()}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() || "";

      for (const chunk of chunks) {
        const line = chunk
          .split("\n")
          .find((item) => item.startsWith("data:"));
        if (!line) continue;
        const event = JSON.parse(line.slice(5).trim());
        addEvent(event);
        if (event.event === "final" || event.type === "result") {
          setResult(event.result || event);
        }
        if (event.event === "error") {
          setRunState("Error", "error");
          setResult(event);
        }
      }
    }

    if ($("runState").textContent !== "Error") {
      setRunState("Success", "success");
    }
  } catch (error) {
    const event = { event: "error", message: error.message };
    addEvent(event);
    setResult(event);
    setRunState("Error", "error");
  } finally {
    state.running = false;
  }
}

async function checkHealth() {
  $("healthStatus").textContent = "检查中...";
  try {
    const response = await fetch(`${getApiBase()}/healthz`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    $("healthStatus").textContent = data.msg === "OK" ? "连接正常" : "返回异常";
  } catch (error) {
    $("healthStatus").textContent = `连接失败：${error.message}`;
  }
}

function switchTab(tab) {
  state.activeTab = tab;
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.tab === tab);
  });
  $("highlightPanel").classList.toggle("active", tab === "highlight");
  $("commentaryPanel").classList.toggle("active", tab === "commentary");
  $("pageTitle").textContent = tab === "highlight" ? "高光分析" : "解说词生成";
  $("pageDescription").textContent =
    tab === "highlight"
      ? "调用视频高亮 workflow，实时查看节点进度和最终结果。"
      : "调用解说词 workflow，生成文案、配音时间轴和草稿 manifest。";
}

function bindEvents() {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => switchTab(item.dataset.tab));
  });

  $("healthCheck").addEventListener("click", checkHealth);
  $("fillHighlightExample").addEventListener("click", () => {
    $("highlightInputVideos").value = examples.highlightVideos;
    $("highlightOutputDir").value = "/tmp/general_video_langgraph/highlight";
    $("highlightDraftOutputDir").value = "/tmp/general_video_langgraph/highlight_draft";
    $("highlightMaterialBasePath").value = "/path/to/materials";
    $("highlightCornerBadges").value = JSON.stringify(["/path/to/badge.png"], null, 2);
    $("highlightTailFrames").value = JSON.stringify(["/path/to/end.png"], null, 2);
    updatePreviews();
  });
  $("fillCommentaryExample").addEventListener("click", () => {
    $("commentaryDemoInfo").value = examples.demoInfo;
    $("commentaryInputVideos").value = JSON.stringify(["/path/to/video.mp4"], null, 2);
    $("commentaryOutputDir").value = "/tmp/general_video_langgraph/commentary";
    $("commentaryCornerBadges").value = JSON.stringify(["/path/to/badge.png"], null, 2);
    $("commentaryTailFrames").value = JSON.stringify(["/path/to/end.png"], null, 2);
    updatePreviews();
  });

  $("commentaryDemandPreset").addEventListener("change", () => {
    $("commentaryDemand").value = $("commentaryDemandPreset").value;
    updatePreviews();
  });

  $("highlightForm").addEventListener("submit", (event) => {
    event.preventDefault();
    updatePreviews();
    postSse("/highlight_sse", buildHighlightPayload());
  });

  $("commentaryForm").addEventListener("submit", (event) => {
    event.preventDefault();
    updatePreviews();
    postSse("/commentary_sse", buildCommentaryPayload());
  });

  $("clearLog").addEventListener("click", () => {
    $("eventLog").innerHTML = "";
  });
  $("copyResult").addEventListener("click", async () => {
    await navigator.clipboard.writeText($("resultBox").textContent);
  });

  document.querySelectorAll("input, textarea, select").forEach((input) => {
    input.addEventListener("input", updatePreviews);
    input.addEventListener("change", updatePreviews);
  });
}

function init() {
  $("highlightInputVideos").value = examples.highlightVideos;
  $("highlightOutputDir").value = "/tmp/general_video_langgraph/highlight";
  $("commentaryDemoInfo").value = examples.demoInfo;
  $("commentaryOutputDir").value = "/tmp/general_video_langgraph/commentary";
  bindEvents();
  updatePreviews();
}

init();
