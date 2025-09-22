const jsonHeaders = {
  "Content-Type": "application/json; charset=utf-8",
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "Content-Type,Authorization",
  "Access-Control-Allow-Methods": "OPTIONS,GET,POST,DELETE"
};

function send(statusCode, body) {
  return { statusCode, headers: jsonHeaders, body: JSON.stringify(body) };
}

// Simple in-memory store (resets on cold start)
const stories = {};
let counter = 0; // Sequential IDs (001, 002, ...)

exports.handler = async (event) => {
  try {
    const method = event.requestContext?.http?.method || event.httpMethod || "POST";
    const rawPath = event.rawPath || event.path || "";
    const stage = event.requestContext?.stage || "";

    // Normalize path (strip stage like "/prod")
    const path = stage && rawPath.startsWith("/" + stage)
      ? rawPath.slice(stage.length + 1)
      : rawPath;

    // Handle CORS preflight
    if (method === "OPTIONS") {
      return { statusCode: 200, headers: jsonHeaders, body: "" };
    }

    // --- POST /stories/prepare ---
    if (method === "POST" && path === "/stories/prepare") {
      counter++;
      const story_id = "story_mock_" + String(counter).padStart(3, "0"); // story_mock_001
      stories[story_id] = { start_ts: Date.now() };

      return send(201, {
        story_id,
        hls_url: `https://cdn.lunebi.com/stories/mock/${story_id}/playlist.m3u8`
      });
    }

    // --- POST /stories/{id} ---
    const mPostStory = path.match(/^\/stories\/([^/]+)$/);
    if (method === "POST" && mPostStory) {
      const story_id = mPostStory[1];
      if (!stories[story_id]) {
        return send(404, { error: "story_not_found", story_id });
      }
      // Mark story as "processing"
      stories[story_id].processing = true;
      return send(202, { ok: true, story_id });
    }

    // --- GET /stories/{id}/status ---
    const mStatus = path.match(/^\/stories\/([^/]+)\/status$/);
    if (method === "GET" && mStatus) {
      const story_id = mStatus[1];
      const rec = stories[story_id];
      if (!rec) return send(404, { error: "story_not_found", story_id });

      const elapsed = (Date.now() - rec.start_ts) / 1000;
      let status = "initializing", progress = 0, ready = false, download_url = null;

      if (elapsed > 2 && elapsed <= 5) {
        status = "buffering"; progress = 25;
      } else if (elapsed > 5 && elapsed <= 15) {
        status = "streaming"; progress = 50;
      } else if (elapsed > 15 && elapsed <= 25) {
        status = "finalizing"; progress = 75;
      } else if (elapsed > 25) {
        status = "complete"; progress = 100; ready = true;
        download_url = `https://cdn.lunebi.com/stories/mock/${story_id}/final/story.m4a`;
      }

      return send(200, {
        story_id,
        status,
        progress_pct: progress,
        ready_for_download: ready,
        download_url
      });
    }

    // --- No matching route ---
    return send(404, { error: "not_found", path });

  } catch (err) {
    console.error("Handler error:", err);
    return send(500, { error: "internal_error", message: String(err) });
  }
};

