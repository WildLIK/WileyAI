# Fairy Assistant — Crystal

Bundled character: model 0.16, authored by the FairyAssistant project using a
locally created VRoid Studio base and Blender refinements. The mesh, rig,
expressions and textures are embedded in `Fairy_Assistant.vrm`.

The embedded [VRM 1.0 license](https://vrm.dev/licenses/1.0/) and permissions
apply. Use as an avatar by everyone and redistribution are permitted. The
remaining use permissions are recorded in the VRM metadata.

This version retains the repaired shoulder weights and skin palette, adds
layered pearl hair with painted fibres and nine fine silhouette cards, and
lightens the blue/rose/violet wing membrane. WileyAI supplies the pose solver,
facial animation, head petting and music reactions.

The portable settings value `builtin:fairy` resolves this file relative to the
current application resources directory. A custom user VRM keeps its own path.

Model 0.16 follows the character reference sheet more closely and is rebuilt
from 0.15 by `scripts/fairy-model-edit.py` (Blender 5.2 with the VRM Add-on):

- live hair and skirt: the bob is weighted to its nine hair spring chains
  (roots stay on the head), and the skirt hem to six hip chains that collide
  with the thighs;
- reference colours: black sash, back bow, ribbons and choker; white skirt
  petals with an ice-blue cast; pale white-blue wing membrane;
- new details: a black thigh garter with a bow on the right leg, black boot
  soles and low block heels.
