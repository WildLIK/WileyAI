import { fairyPoses, type FairyPose, type V3 } from "./avatarPoses.ts";

export type DanceStyle = 1 | 2 | 3;
const base = fairyPoses.joy;
const pose = (changes: Partial<FairyPose>): FairyPose => ({
  ...base,
  ...changes,
});
const prepare = pose({
  left: [0.045, 0.7, 0.17],
  right: [-0.045, 0.7, 0.17],
  leftHand: "soft",
  rightHand: "soft",
  body: [0, 0, 0],
  head: [0, 0, 0],
  leftLeg: [-0.25, 0.04, -0.02],
  rightLeg: [-0.25, -0.04, 0.02],
  knees: [0.55, 0.65],
});
const returnPose = pose({
  left: [0.24, 0.56, 0.1],
  right: [-0.24, 0.56, 0.1],
  body: [0, 0, 0],
  head: [0, 0, 0],
  knees: [0.7, 1],
});
// Hovering sway; the original open-palm dance.
const sway: FairyPose[] = [
  pose({
    left: [0.3, 0.72, 0.14],
    right: [-0.22, 0.8, 0.12],
    body: [0, -0.28, -0.08],
    head: [0, 0.12, -0.12],
    knees: [1.4, 1.7],
  }),
  pose({
    left: [0.24, 0.8, 0.12],
    right: [-0.3, 0.65, 0.18],
    body: [0.04, 0.32, 0.08],
    head: [-0.06, -0.12, 0.12],
    knees: [1.7, 1.25],
  }),
  pose({
    left: [0.16, 0.87, 0.08],
    right: [-0.34, 0.68, 0.14],
    body: [0, 0.55, -0.06],
    head: [0, -0.25, -0.06],
    knees: [1.6, 1.6],
  }),
  pose({
    left: [0.34, 0.65, 0.18],
    right: [-0.16, 0.84, 0.08],
    body: [0.04, -0.4, 0.1],
    head: [-0.08, 0.2, 0.1],
    knees: [1.3, 1.7],
  }),
];
// Reference 2: preparation, open arms, full turn, folded leg and raised-arm finish.
const spin: FairyPose[] = [
  prepare,
  pose({
    left: [0.39, 0.77, 0.08],
    right: [-0.39, 0.77, 0.08],
    body: [-0.04, 0, -0.06],
    head: [-0.05, 0, -0.04],
    knees: [0.7, 1.2],
  }),
  pose({
    left: [0.36, 0.78, 0.06],
    right: [-0.36, 0.78, 0.06],
    body: [-0.04, 0, 0.04],
    head: [0, 0, 0],
    leftLeg: [-0.35, 0.04, -0.06],
    rightLeg: [-0.65, -0.08, 0.12],
    knees: [0.8, 1.9],
  }),
  pose({
    left: [0.36, 0.8, 0.08],
    right: [-0.36, 0.78, 0.08],
    body: [-0.06, 0, -0.07],
    head: [-0.05, 0.1, 0.05],
    knees: [1.1, 2],
  }),
  pose({
    left: [0.23, 1.02, 0.08],
    right: [-0.36, 0.68, 0.14],
    body: [0, 0.05, -0.08],
    head: [-0.06, -0.1, 0.08],
    leftLeg: [-0.3, 0.08, -0.04],
    rightLeg: [-0.85, -0.08, 0.15],
    knees: [0.6, 2.1],
  }),
  returnPose,
];
// Reference 3: side step, turn, crossed legs, hand near the face, airborne finish.
const steps: FairyPose[] = [
  prepare,
  pose({
    left: [0.34, 0.77, 0.12],
    right: [-0.16, 0.77, 0.16],
    body: [0, -0.18, -0.1],
    head: [0, 0.08, -0.1],
    leftLeg: [-0.25, 0.12, -0.3],
    rightLeg: [-0.25, -0.12, 0.3],
    knees: [0.5, 0.65],
    shift: [0.05, 0, 0],
  }),
  pose({
    left: [0.34, 0.76, 0.06],
    right: [-0.32, 0.73, 0.08],
    body: [0, 0.2, 0.05],
    head: [-0.04, 0, 0],
    leftLeg: [-0.35, 0.1, -0.08],
    rightLeg: [-0.62, -0.15, 0.1],
    knees: [0.7, 1.4],
    shift: [0.02, 0.01, 0],
  }),
  pose({
    left: [0.26, 0.6, 0.12],
    right: [-0.26, 0.6, 0.12],
    body: [0, -0.12, -0.06],
    head: [0.02, 0.1, 0.08],
    leftLeg: [-0.25, -0.1, 0.24],
    rightLeg: [-0.3, 0.15, -0.24],
    knees: [0.55, 0.65],
    shift: [-0.05, 0, 0],
  }),
  pose({
    left: [0.12, 0.84, 0.17],
    right: [-0.31, 0.72, 0.22],
    leftHand: "point",
    body: [0, 0.1, 0.05],
    head: [-0.03, -0.12, 0.1],
    leftLeg: [-0.3, 0.1, -0.22],
    rightLeg: [-0.3, -0.1, 0.22],
    knees: [0.55, 0.65],
  }),
  pose({
    left: [0.29, 1, 0.1],
    right: [-0.29, 1, 0.1],
    body: [-0.04, 0, -0.04],
    head: [-0.07, 0, -0.05],
    leftLeg: [-0.3, 0.1, -0.04],
    rightLeg: [-0.9, -0.15, 0.14],
    knees: [0.6, 2.1],
    shift: [0, 0.025, 0],
  }),
];
const smooth = (value: number) => {
  const x = Math.max(0, Math.min(1, value));
  return x * x * (3 - 2 * x);
};

export function dancePose(phase: number, style: DanceStyle = 1): FairyPose {
  const cycle = ((phase % 16) + 16) % 16;
  const frames = style === 2 ? spin : style === 3 ? steps : sway;
  const position = (cycle / 16) * frames.length;
  const index = Math.floor(position),
    a = frames[index],
    b = frames[(index + 1) % frames.length];
  const t = (1 - Math.cos((position - index) * Math.PI)) / 2;
  const mix = (x: V3, y: V3): V3 =>
    x.map((value, i) => value + (y[i] - value) * t) as V3;
  return {
    ...a,
    left: mix(a.left, b.left),
    right: mix(a.right, b.right),
    leftWrist: mix(a.leftWrist, b.leftWrist),
    rightWrist: mix(a.rightWrist, b.rightWrist),
    head: mix(a.head, b.head),
    body: mix(a.body, b.body),
    leftLeg: mix(a.leftLeg, b.leftLeg),
    rightLeg: mix(a.rightLeg, b.rightLeg),
    knees: [
      a.knees[0] + (b.knees[0] - a.knees[0]) * t,
      a.knees[1] + (b.knees[1] - a.knees[1]) * t,
    ],
    leftHand: t < 0.5 ? a.leftHand : b.leftHand,
    rightHand: t < 0.5 ? a.rightHand : b.rightHand,
    shift: mix(a.shift || [0, 0, 0], b.shift || [0, 0, 0]),
    turn:
      style === 2
        ? Math.PI * 2 * smooth((cycle - 2) / 10)
        : style === 3
          ? Math.PI * 2 * smooth((cycle - 3) / 6)
          : 0,
  };
}
