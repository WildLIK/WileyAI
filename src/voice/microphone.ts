import { microphoneConstraints, microphoneError } from "./devices.ts";

export interface Capture {
  sampleRate: number;
  start(
    onFrame: (frame: Float32Array) => void,
    onError: (error: Error) => void,
  ): Promise<void>;
  stop(): Promise<void>;
}

export class Microphone implements Capture {
  sampleRate = 16000;
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private node: AudioWorkletNode | null = null;
  private generation = 0;
  private deviceId: string;
  constructor(deviceId = "") {
    this.deviceId = deviceId;
  }

  async start(
    onFrame: (frame: Float32Array) => void,
    onError: (error: Error) => void,
  ) {
    const generation = ++this.generation;
    try {
      const stream = await navigator.mediaDevices.getUserMedia(
        microphoneConstraints(this.deviceId),
      );
      if (generation !== this.generation) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      this.stream = stream;
      stream.getAudioTracks().forEach((track) =>
        track.addEventListener(
          "ended",
          () => {
            if (generation === this.generation)
              onError(
                new Error(
                  "Микрофон отключён. Подключите его и начните разговор заново.",
                ),
              );
          },
          { once: true },
        ),
      );
      const context = new AudioContext({ sampleRate: 16000 });
      this.context = context;
      await context.audioWorklet.addModule(
        new URL("./microphone-worklet.js", import.meta.url).href,
      );
      if (generation !== this.generation) return;
      this.sampleRate = context.sampleRate;
      const node = new AudioWorkletNode(context, "wiley-microphone");
      this.node = node;
      const source = context.createMediaStreamSource(stream);
      this.source = source;
      node.port.onmessage = (event) => {
        if (generation === this.generation) onFrame(event.data as Float32Array);
      };
      node.onprocessorerror = () =>
        onError(
          new Error("Аудиопроцессор остановился. Начните разговор заново."),
        );
      source.connect(node);
      // The worklet outputs silence. The microphone is never monitored to speakers.
      node.connect(context.destination);
      await context.resume();
    } catch (error) {
      if (generation === this.generation) await this.stop();
      throw microphoneError(error);
    }
  }

  async stop() {
    this.generation++;
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.source?.disconnect();
    this.source = null;
    if (this.node) {
      this.node.port.onmessage = null;
      this.node.onprocessorerror = null;
      this.node.disconnect();
      this.node.port.close();
      this.node = null;
    }
    const context = this.context;
    this.context = null;
    if (context && context.state !== "closed") await context.close();
  }
}
