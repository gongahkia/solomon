const std = @import("std");
const frame = @import("frame");
const context = @import("context");

export fn shisa_fuzz_frame_decode(data: [*]const u8, len: usize) void {
    const input = data[0..len];
    const payload = frame.decode(input) catch return;
    if (input.len < frame.header_bytes) @trap();
    const payload_len = std.mem.readInt(u32, input[0..frame.header_bytes], .big);
    if (frame.header_bytes + @as(usize, payload_len) != input.len) @trap();
    if (!std.mem.eql(u8, input[frame.header_bytes..], payload)) @trap();
}

export fn shisa_fuzz_context_input(data: [*]const u8, len: usize) void {
    const input = data[0..len];
    if (input.len > context.max_announce_bytes + 512) return;
    inline for (std.meta.fields(context.Function)) |field| {
        const function: context.Function = @enumFromInt(field.value);
        context.validateFunctionInput(function, input) catch |err| switch (err) {
            error.ContextInputTooLarge,
            error.InvalidContextUtf8,
            error.InvalidContextControl,
            => {},
        };
    }
}
