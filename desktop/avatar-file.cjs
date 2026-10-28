const path = require("node:path");

// A stable selection survives application updates and installation moves.
// Custom models must be absolute paths on a local drive: never relative, UNC
// (\\server\share) or device paths (\\?\, \\.\) that could reach the network.
function avatarFile(selection, resources) {
  if (selection === "builtin:fairy")
    return path.join(resources, "avatars", "Fairy_Assistant.vrm");
  return typeof selection === "string" &&
    /^[A-Za-z]:[\\/]/.test(selection) &&
    !selection.includes("\0") &&
    path.extname(selection).toLowerCase() === ".vrm"
    ? selection
    : null;
}

module.exports = { avatarFile };
