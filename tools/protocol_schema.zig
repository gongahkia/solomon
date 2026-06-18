const std = @import("std");
const proto = @import("proto_types");

pub fn main() !void {
    var gpa_impl = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa_impl.deinit();
    const allocator = gpa_impl.allocator();

    const args = try std.process.argsAlloc(allocator);
    defer std.process.argsFree(allocator, args);
    const output_path = if (args.len > 1) args[1] else "docs/protocol/v1.schema.json";

    var file = try std.fs.cwd().createFile(output_path, .{ .truncate = true });
    defer file.close();
    try file.writeAll(schema_json);
}

const schema_json =
    \\{
    \\  "$schema": "https://json-schema.org/draft/2020-12/schema",
    \\  "$id": "https://shisa.dev/schemas/protocol/v1.schema.json",
    \\  "title": "Shisa protocol v1",
    \\  "type": "object",
    \\  "oneOf": [
    \\    { "$ref": "#/$defs/renderRequest" },
    \\    { "$ref": "#/$defs/renderContinueRequest" },
    \\    { "$ref": "#/$defs/healthRequest" },
    \\    { "$ref": "#/$defs/metricsRequest" },
    \\    { "$ref": "#/$defs/reloadRequest" },
    \\    { "$ref": "#/$defs/versionRequest" },
    \\    { "$ref": "#/$defs/subscribeRequest" },
    \\    { "$ref": "#/$defs/promptResponse" },
    \\    { "$ref": "#/$defs/healthResponse" },
    \\    { "$ref": "#/$defs/metricsResponse" },
    \\    { "$ref": "#/$defs/reloadResponse" },
    \\    { "$ref": "#/$defs/versionResponse" },
    \\    { "$ref": "#/$defs/subscribeEvent" },
    \\    { "$ref": "#/$defs/errorEnvelope" }
    \\  ],
    \\  "$defs": {
    \\    "op": {
    \\      "type": "string",
    \\      "enum": ["render", "render_continue", "health", "metrics", "reload", "version", "subscribe"]
    \\    },
    \\    "shell": {
    \\      "type": "string",
    \\      "enum": ["zsh", "bash", "fish", "nu", "pwsh"]
    \\    },
    \\    "colorCaps": {
    \\      "type": "string",
    \\      "enum": ["truecolor", "256", "16", "none"]
    \\    },
    \\    "glyphCaps": {
    \\      "type": "string",
    \\      "enum": ["nerdfont", "unicode", "ascii"]
    \\    },
    \\    "cloudCtx": {
    \\      "type": "object",
    \\      "additionalProperties": true,
    \\      "properties": {
    \\        "aws": { "type": "boolean" },
    \\        "gcp": { "type": "boolean" },
    \\        "azure": { "type": "boolean" },
    \\        "kubernetes": { "type": "boolean" }
    \\      }
    \\    },
    \\    "riskTierColor": {
    \\      "type": "string",
    \\      "enum": ["fg", "muted", "accent", "success", "warning", "danger"]
    \\    },
    \\    "riskTier": {
    \\      "type": "object",
    \\      "additionalProperties": true,
    \\      "properties": {
    \\        "unknown_bg": { "$ref": "#/$defs/riskTierColor" },
    \\        "dev_bg": { "$ref": "#/$defs/riskTierColor" },
    \\        "staging_bg": { "$ref": "#/$defs/riskTierColor" },
    \\        "prod_bg": { "$ref": "#/$defs/riskTierColor" }
    \\      }
    \\    },
    \\    "ssoExpiry": {
    \\      "type": "object",
    \\      "additionalProperties": true,
    \\      "properties": {
    \\        "warning_minutes": { "type": "integer", "minimum": 1 }
    \\      }
    \\    },
    \\    "commonRequest": {
    \\      "type": "object",
    \\      "required": ["v", "op", "request_id"],
    \\      "additionalProperties": true,
    \\      "properties": {
    \\        "v": { "const": 1 },
    \\        "op": { "$ref": "#/$defs/op" },
    \\        "request_id": { "type": "string" }
    \\      }
    \\    },
    \\    "renderRequest": {
    \\      "type": "object",
    \\      "required": ["v", "op", "request_id", "cwd", "exit", "jobs", "duration_ms", "shell", "cols", "rows", "tty", "color_caps", "glyph_caps", "user_id", "session"],
    \\      "additionalProperties": true,
    \\      "properties": {
    \\        "v": { "const": 1 },
    \\        "op": { "const": "render" },
    \\        "request_id": { "type": "string" },
    \\        "cwd": { "type": "string" },
    \\        "exit": { "type": "integer" },
    \\        "jobs": { "type": "integer", "minimum": 0 },
    \\        "duration_ms": { "type": "integer", "minimum": 0 },
    \\        "time": { "type": "boolean" },
    \\        "no_async": { "type": "boolean" },
    \\        "shell": { "$ref": "#/$defs/shell" },
    \\        "cols": { "type": "integer", "minimum": 1 },
    \\        "rows": { "type": "integer", "minimum": 1 },
    \\        "tty": { "type": "string" },
    \\        "color_caps": { "$ref": "#/$defs/colorCaps" },
    \\        "glyph_caps": { "$ref": "#/$defs/glyphCaps" },
    \\        "user_id": { "type": "integer", "minimum": 0 },
    \\        "session": { "type": "string" },
    \\        "rtl": { "type": "boolean" },
    \\        "rtl_reverse": { "type": "boolean" },
    \\        "cloud_ctx": { "$ref": "#/$defs/cloudCtx" },
    \\        "risk_tier": { "$ref": "#/$defs/riskTier" },
    \\        "sso_expiry": { "$ref": "#/$defs/ssoExpiry" }
    \\      }
    \\    },
    \\    "renderContinueRequest": {
    \\      "type": "object",
    \\      "required": ["v", "op", "request_id", "cwd", "exit", "jobs", "duration_ms", "shell", "cols", "rows", "tty", "color_caps", "glyph_caps", "user_id", "session"],
    \\      "additionalProperties": true,
    \\      "properties": {
    \\        "v": { "const": 1 },
    \\        "op": { "const": "render_continue" },
    \\        "request_id": { "type": "string" },
    \\        "cwd": { "type": "string" },
    \\        "exit": { "type": "integer" },
    \\        "jobs": { "type": "integer", "minimum": 0 },
    \\        "duration_ms": { "type": "integer", "minimum": 0 },
    \\        "time": { "type": "boolean" },
    \\        "no_async": { "type": "boolean" },
    \\        "shell": { "$ref": "#/$defs/shell" },
    \\        "cols": { "type": "integer", "minimum": 1 },
    \\        "rows": { "type": "integer", "minimum": 1 },
    \\        "tty": { "type": "string" },
    \\        "color_caps": { "$ref": "#/$defs/colorCaps" },
    \\        "glyph_caps": { "$ref": "#/$defs/glyphCaps" },
    \\        "user_id": { "type": "integer", "minimum": 0 },
    \\        "session": { "type": "string" },
    \\        "rtl": { "type": "boolean" },
    \\        "rtl_reverse": { "type": "boolean" },
    \\        "cloud_ctx": { "$ref": "#/$defs/cloudCtx" },
    \\        "risk_tier": { "$ref": "#/$defs/riskTier" },
    \\        "sso_expiry": { "$ref": "#/$defs/ssoExpiry" }
    \\      }
    \\    },
    \\    "healthRequest": {
    \\      "allOf": [
    \\        { "$ref": "#/$defs/commonRequest" },
    \\        { "properties": { "op": { "const": "health" } } }
    \\      ]
    \\    },
    \\    "metricsRequest": {
    \\      "allOf": [
    \\        { "$ref": "#/$defs/commonRequest" },
    \\        {
    \\          "properties": {
    \\            "op": { "const": "metrics" },
    \\            "format": { "enum": ["json", "prometheus"] }
    \\          }
    \\        }
    \\      ]
    \\    },
    \\    "reloadRequest": {
    \\      "allOf": [
    \\        { "$ref": "#/$defs/commonRequest" },
    \\        { "properties": { "op": { "const": "reload" } } }
    \\      ]
    \\    },
    \\    "versionRequest": {
    \\      "allOf": [
    \\        { "$ref": "#/$defs/commonRequest" },
    \\        { "properties": { "op": { "const": "version" } } }
    \\      ]
    \\    },
    \\    "subscribeRequest": {
    \\      "type": "object",
    \\      "required": ["v", "op", "request_id", "topics"],
    \\      "additionalProperties": true,
    \\      "properties": {
    \\        "v": { "const": 1 },
    \\        "op": { "const": "subscribe" },
    \\        "request_id": { "type": "string" },
    \\        "backpressure_limit": { "type": "integer", "minimum": 1, "maximum": 1024 },
    \\        "topics": {
    \\          "type": "array",
    \\          "items": { "type": "string" }
    \\        }
    \\      }
    \\    },
    \\    "diagnostic": {
    \\      "type": "object",
    \\      "required": ["code", "message"],
    \\      "additionalProperties": true,
    \\      "properties": {
    \\        "code": { "type": "string" },
    \\        "message": { "type": "string" }
    \\      }
    \\    },
    \\    "promptResponse": {
    \\      "type": "object",
    \\      "required": ["v", "request_id", "prompt", "diagnostics", "elapsed_us"],
    \\      "additionalProperties": true,
    \\      "properties": {
    \\        "v": { "const": 1 },
    \\        "request_id": { "type": "string" },
    \\        "prompt": { "type": "string" },
    \\        "redraw_token": { "type": ["string", "null"] },
    \\        "trailer": { "type": ["string", "null"] },
    \\        "diagnostics": {
    \\          "type": "array",
    \\          "items": { "$ref": "#/$defs/diagnostic" }
    \\        },
    \\        "elapsed_us": { "type": "integer", "minimum": 0 }
    \\      }
    \\    },
    \\    "healthResponse": {
    \\      "type": "object",
    \\      "required": ["v", "request_id", "ok"],
    \\      "additionalProperties": true,
    \\      "properties": {
    \\        "v": { "const": 1 },
    \\        "request_id": { "type": "string" },
    \\        "ok": { "type": "boolean" }
    \\      }
    \\    },
    \\    "metricsResponse": {
    \\      "type": "object",
    \\      "required": ["v", "request_id", "connections", "cache", "fsnotify"],
    \\      "additionalProperties": true,
    \\      "properties": {
    \\        "v": { "const": 1 },
    \\        "request_id": { "type": "string" },
    \\        "connections": { "type": "integer", "minimum": 0 },
    \\        "cache": { "type": "object", "additionalProperties": true },
    \\        "fsnotify": { "type": "object", "additionalProperties": true }
    \\      }
    \\    },
    \\    "reloadResponse": {
    \\      "type": "object",
    \\      "required": ["v", "request_id", "reloaded"],
    \\      "additionalProperties": true,
    \\      "properties": {
    \\        "v": { "const": 1 },
    \\        "request_id": { "type": "string" },
    \\        "reloaded": { "type": "boolean" },
    \\        "config_generation": { "type": "integer", "minimum": 0 },
    \\        "plugin_generation": { "type": "integer", "minimum": 0 },
    \\        "plugins": { "type": "integer", "minimum": 0 }
    \\      }
    \\    },
    \\    "versionResponse": {
    \\      "type": "object",
    \\      "required": ["v", "request_id", "daemon", "protocol"],
    \\      "additionalProperties": true,
    \\      "properties": {
    \\        "v": { "const": 1 },
    \\        "request_id": { "type": "string" },
    \\        "daemon": { "type": "string" },
    \\        "protocol": { "const": 1 }
    \\      }
    \\    },
    \\    "subscribeEvent": {
    \\      "type": "object",
    \\      "required": ["v", "request_id", "topic", "kind", "data"],
    \\      "additionalProperties": true,
    \\      "properties": {
    \\        "v": { "const": 1 },
    \\        "request_id": { "type": "string" },
    \\        "topic": { "type": "string" },
    \\        "kind": { "type": "string", "enum": ["snapshot", "delta", "heartbeat", "error"] },
    \\        "data": { "type": "object", "additionalProperties": true }
    \\      }
    \\    },
    \\    "errorCode": {
    \\      "type": "string",
    \\      "enum": ["E_VERSION", "E_OVERSIZE", "E_MALFORMED", "E_NOT_READY", "E_PLUGIN_TIMEOUT", "E_CAPABILITY_DENIED", "E_READONLY", "E_INTERNAL"]
    \\    },
    \\    "errorContext": {
    \\      "type": "object",
    \\      "additionalProperties": true,
    \\      "properties": {
    \\        "field": { "type": "string" },
    \\        "expected": { "type": "string" },
    \\        "highest_supported_version": { "type": "integer", "minimum": 1 },
    \\        "max_frame_bytes": { "type": "integer", "minimum": 1 },
    \\        "op": { "type": "string" },
    \\        "retry_after_ms": { "type": "integer", "minimum": 0 },
    \\        "plugin": { "type": "string" },
    \\        "timeout_ms": { "type": "integer", "minimum": 0 },
    \\        "capability": { "type": "string" },
    \\        "detail": { "type": "string" }
    \\      }
    \\    },
    \\    "errorEnvelope": {
    \\      "type": "object",
    \\      "required": ["v", "request_id", "error"],
    \\      "additionalProperties": true,
    \\      "properties": {
    \\        "v": { "const": 1 },
    \\        "request_id": { "type": "string" },
    \\        "error": {
    \\          "type": "object",
    \\          "required": ["code", "message", "context"],
    \\          "additionalProperties": true,
    \\          "properties": {
    \\            "code": { "$ref": "#/$defs/errorCode" },
    \\            "message": { "type": "string" },
    \\            "context": { "$ref": "#/$defs/errorContext" }
    \\          }
    \\        }
    \\      }
    \\    }
    \\  }
    \\}
    \\
;

test "schema mentions canonical protocol values" {
    const ops = [_]proto.Op{ .render, .render_continue, .health, .metrics, .reload, .version, .subscribe };
    for (ops) |op| {
        try std.testing.expect(std.mem.indexOf(u8, schema_json, @tagName(op)) != null);
    }

    const codes = [_]proto.ErrorCode{
        .E_VERSION,
        .E_OVERSIZE,
        .E_MALFORMED,
        .E_NOT_READY,
        .E_PLUGIN_TIMEOUT,
        .E_CAPABILITY_DENIED,
        .E_READONLY,
        .E_INTERNAL,
    };
    for (codes) |code| {
        try std.testing.expect(std.mem.indexOf(u8, schema_json, @tagName(code)) != null);
    }
}
