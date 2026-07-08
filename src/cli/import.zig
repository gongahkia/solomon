const starship = @import("import/starship.zig");
const p10k = @import("import/p10k.zig");
const omp = @import("import/omp.zig");
const tide = @import("import/tide.zig");
const pure = @import("import/pure.zig");

pub const importStarshipCmd = starship.importStarshipCmd;
pub const importP10kCmd = p10k.importP10kCmd;
pub const importOhMyPoshCmd = omp.importOhMyPoshCmd;
pub const importTideCmd = tide.importTideCmd;
pub const importPureCmd = pure.importPureCmd;

test {
    _ = @import("import/omp_tests.zig");
}
