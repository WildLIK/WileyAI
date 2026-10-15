class WileyMicrophone extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frame = new Float32Array(Math.round(sampleRate / 50));
    this.offset = 0;
  }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    for (let index = 0; index < input.length; index++) {
      this.frame[this.offset++] = input[index];
      if (this.offset === this.frame.length) {
        const frame = this.frame;
        // Allocate before transferring: transfer detaches the old typed array.
        this.frame = new Float32Array(frame.length);
        this.offset = 0;
        this.port.postMessage(frame, [frame.buffer]);
      }
    }
    return true;
  }
}
registerProcessor("wiley-microphone", WileyMicrophone);
