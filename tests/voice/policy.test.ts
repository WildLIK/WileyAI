import test from "node:test";
import assert from "node:assert/strict";
import { activationPolicy, sessionPolicy } from "../../src/voice/policy.ts";
import { inspectActivation } from "../../src/voice/activation.ts";

for (const environment of ["normal", "music"] as const) for (const required of [false, true]) for (const barge of [false, true]) {
  test(`activation matrix: ${environment}, wake=${required}, barge=${barge}`, () => {
    const config = { stt_environment: environment, conversation_wake_required: required, conversation_barge_in: barge, conversation_listen_while_thinking: true, conversation_wake_word: "Уайли", stt_model: "small" };
    const main = activationPolicy(config);
    assert.equal(main.required, environment === "music" || required);
    assert.equal(inspectActivation("Расскажи о Луне", "Уайли", main.required, environment === "music").accepted, !main.required);
    assert.equal(inspectActivation("Уайли, расскажи о Луне", "Уайли", main.required, environment === "music").accepted, true);
    assert.equal(activationPolicy(config, "barge").required, true);
    assert.equal(inspectActivation("Расскажи о Луне", "Уайли", activationPolicy(config, "barge").required).accepted, false);
    const snapshot = sessionPolicy(config); config.stt_environment = environment === "normal" ? "music" : "normal";
    assert.equal(snapshot.stt_environment, environment); assert.equal(snapshot.startedManually, true); assert.equal(snapshot.backgroundWake, false);
  });
}
