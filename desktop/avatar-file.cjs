const path = require("node:path");

// A stable selection survives application updates and installation moves.
function avatarFile(selection, resources) {
  if (selection === "builtin:fairy")
    return path.join(resources, "avatars", "Fairy_Assistant.vrm");
  return typeof selection === "string" &&
    path.extname(selection).toLowerCase() === ".vrm"
    ? selection
    : null;
}

module.exports = { avatarFile };
