import type { AvatarGesture } from "./avatarBehavior";

export type V3 = [number, number, number];
export type HandShape = "open" | "soft" | "point" | "fist" | "thumbsup";
export type FairyPose = {
  left: V3;
  right: V3;
  leftWrist: V3;
  rightWrist: V3;
  leftHand: HandShape;
  rightHand: HandShape;
  head: V3;
  body: V3;
  leftLeg: V3;
  rightLeg: V3;
  knees: [number, number];
};
const resting: FairyPose = {
  left: [0.21, 0.45, 0.05],
  right: [-0.21, 0.45, 0.05],
  leftWrist: [0, 0, 0],
  rightWrist: [0, 0, 0],
  leftHand: "soft",
  rightHand: "soft",
  head: [0, 0, 0],
  body: [0, 0, 0],
  leftLeg: [-0.3, 0.1, -0.06],
  rightLeg: [-0.42, -0.1, 0.06],
  knees: [0.85, 1.25],
};
const pose = (changes: Partial<FairyPose>): FairyPose => ({
  ...resting,
  ...changes,
});
/** Hand goals use model-height fractions, with +Z toward the viewer. */
export const fairyPoses: Record<AvatarGesture, FairyPose> = {
  none: resting,
  nod: pose({ head: [0.05, 0, 0] }),
  wave: pose({
    right: [-0.22, 0.82, 0.12],
    rightWrist: [-0.9, 0, 0],
    rightHand: "open",
    head: [0, 0, -0.09],
    rightLeg: [-0.55, -0.12, 0.12],
    knees: [0.85, 1.55],
  }),
  joy: pose({
    left: [0.3, 0.75, 0.2],
    right: [-0.3, 0.75, 0.2],
    leftHand: "open",
    rightHand: "open",
    head: [-0.05, 0, -0.1],
    body: [0, 0.2, -0.05],
    leftLeg: [-0.65, 0.15, -0.13],
    rightLeg: [-0.6, -0.1, 0.1],
    knees: [1.65, 1.55],
  }),
  cute: pose({
    right: [-0.1, 0.75, 0.12],
    left: [0.25, 0.58, 0.18],
    rightHand: "point",
    leftHand: "open",
    leftWrist: [0.7, 0, 0],
    head: [0.03, -0.1, 0.14],
    body: [0, -0.2, 0.04],
    leftLeg: [-0.6, 0.1, -0.12],
    knees: [1.55, 0.95],
  }),
  explain: pose({
    right: [-0.28, 0.65, 0.22],
    left: [0.14, 0.64, 0.15],
    rightHand: "open",
    leftHand: "open",
    rightWrist: [-0.9, 0, 0],
    head: [0, 0.06, -0.06],
    body: [0, 0.07, 0],
    knees: [0.9, 1.25],
  }),
  think: pose({
    right: [-0.035, 0.75, 0.14],
    left: [0.055, 0.64, 0.15],
    rightHand: "point",
    head: [-0.09, 0.1, -0.1],
    body: [0.02, 0.06, 0],
    knees: [0.95, 1.3],
  }),
  praise: pose({
    right: [-0.28, 1.04, 0.1],
    left: [0.28, 1.04, 0.1],
    rightHand: "open",
    leftHand: "open",
    head: [-0.05, 0, -0.1],
    body: [-0.035, -0.18, -0.05],
    leftLeg: [-0.65, 0.12, -0.1],
    rightLeg: [-0.62, -0.1, 0.12],
    knees: [1.7, 1.65],
  }),
  point: pose({
    right: [-0.38, 0.77, 0.2],
    left: [0.15, 0.56, 0.07],
    rightHand: "point",
    leftHand: "soft",
    head: [0, 0.14, -0.04],
    body: [0, 0.12, 0],
    leftLeg: [-0.6, 0.15, -0.12],
    knees: [1.55, 0.8],
  }),
  listen: pose({
    right: [-0.105, 0.77, 0.13],
    left: [0.105, 0.77, 0.13],
    rightHand: "open",
    leftHand: "open",
    head: [0.04, 0, 0.13],
    body: [0.045, 0, 0.025],
    leftLeg: [-0.55, 0.05, -0.02],
    rightLeg: [-0.55, -0.05, 0.02],
    knees: [1.55, 1.55],
  }),
  thumbsup: pose({
    right: [-0.23, 0.78, 0.28],
    left: [0.15, 0.65, 0.13],
    rightHand: "thumbsup",
    leftHand: "fist",
    rightWrist: [-0.25, 0, -0.25],
    head: [0, 0, -0.12],
    body: [0, 0.06, -0.025],
    leftLeg: [-0.6, 0.1, -0.08],
    rightLeg: [-0.6, -0.1, 0.08],
    knees: [1.55, 1.5],
  }),
  shy: pose({
    right: [-0.025, 0.46, 0.16],
    left: [0.025, 0.46, 0.16],
    head: [0.1, -0.06, 0.1],
    body: [0.05, -0.05, 0],
    leftLeg: [-0.55, 0.02, 0.015],
    rightLeg: [-0.55, -0.02, -0.015],
    knees: [1.6, 1.6],
  }),
  tired: pose({
    right: [-0.085, 0.79, 0.13],
    left: [0.04, 0.45, 0.15],
    rightHand: "fist",
    rightWrist: [-0.4, 0, 0],
    head: [0.11, 0, 0.12],
    body: [0.1, -0.1, 0.02],
    leftLeg: [-0.55, 0.05, -0.02],
    rightLeg: [-0.55, -0.05, 0.02],
    knees: [1.6, 1.65],
  }),
  comfort: pose({
    right: [-0.14, 0.65, 0.2],
    left: [0.14, 0.65, 0.2],
    rightHand: "open",
    leftHand: "open",
    head: [0.04, 0, 0.08],
    body: [0.035, 0, 0],
    knees: [0.95, 1.25],
  }),
};
