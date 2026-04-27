(function () {
  function readMinEmitMs(configNode) {
    if (!configNode || !configNode.dataset) {
      return 0;
    }
    var raw = configNode.dataset.minEmitMs;
    if (!raw) {
      return 0;
    }
    var parsed = parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
  }

  function emitRuntimeEvent(buttonId, payload) {
    var button = document.getElementById(buttonId);
    if (!button) {
      return;
    }

    button.title = JSON.stringify(payload);
    button.click();
  }

  function connectRuntimeStream() {
    if (typeof window.EventSource === "undefined") {
      return;
    }

    var eventButtonId = "runtime-sse-event";
    var configNode = document.getElementById("runtime-sse-config");
    var streamUrl = "/api/dashboard-stream";
    var minEmitMs = readMinEmitMs(configNode);

    var lastEmitAt = 0;
    var pendingPayload = null;
    var pendingTimer = null;

    function throttledEmit(payload) {
      if (!minEmitMs) {
        emitRuntimeEvent(eventButtonId, payload);
        return;
      }

      var now = Date.now();
      var delta = now - lastEmitAt;
      if (lastEmitAt === 0 || delta >= minEmitMs) {
        lastEmitAt = now;
        emitRuntimeEvent(eventButtonId, payload);
        return;
      }

      pendingPayload = payload;
      if (pendingTimer) {
        return;
      }

      pendingTimer = setTimeout(function () {
        pendingTimer = null;
        if (!pendingPayload) {
          return;
        }
        lastEmitAt = Date.now();
        emitRuntimeEvent(eventButtonId, pendingPayload);
        pendingPayload = null;
      }, Math.max(10, minEmitMs - delta));
    }

    if (configNode && configNode.dataset && configNode.dataset.streamUrl) {
      streamUrl = configNode.dataset.streamUrl;
    }

    if (configNode && configNode.dataset && configNode.dataset.streamToken) {
      streamUrl += "?stream_token=" + encodeURIComponent(configNode.dataset.streamToken);
    }

    var source = new EventSource(streamUrl);

    source.onopen = function () {
      throttledEmit({
        runtime_status: {
          text: "SSE 실시간 연결 정상: " + streamUrl,
          level: "success",
          source: "sse",
          last_error: "",
          sensor_ok: true,
          alerts_ok: true,
          sensor_error: "",
          alerts_error: ""
        }
      });
    };

    source.onmessage = function (event) {
      if (!event || !event.data) {
        return;
      }

      throttledEmit(JSON.parse(event.data));
    };

    source.onerror = function () {
      throttledEmit({
        runtime_status: {
          text: "SSE 연결이 끊겨 폴링 모드로 전환합니다.",
          level: "warning",
          source: "sse-error",
          last_error: "EventSource disconnected",
          sensor_ok: false,
          alerts_ok: false,
          sensor_error: "EventSource disconnected",
          alerts_error: "EventSource disconnected"
        }
      });
    };

    window.addEventListener("beforeunload", function () {
      source.close();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", connectRuntimeStream);
  } else {
    connectRuntimeStream();
  }
})();
