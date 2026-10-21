/** GPU timer queries measure this canvas, not whole-computer utilization. */
export class AvatarMeter {
  private extension: {
    TIME_ELAPSED_EXT: number;
    GPU_DISJOINT_EXT: number;
  } | null;
  private pending: WebGLQuery[] = [];
  private active: WebGLQuery | null = null;
  private sampled = -1000;
  gpuMs: number | null = null;
  readonly device: string;
  private gl: WebGL2RenderingContext;
  constructor(gl: WebGLRenderingContext | WebGL2RenderingContext) {
    this.gl = gl as WebGL2RenderingContext;
    this.extension =
      "beginQuery" in gl
        ? gl.getExtension("EXT_disjoint_timer_query_webgl2")
        : null;
    const debug = gl.getExtension("WEBGL_debug_renderer_info");
    this.device = debug
      ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)
      : "WebGL 2";
  }
  begin(now: number) {
    const ext = this.extension,
      gl = this.gl;
    if (!ext || gl.isContextLost()) return;
    const disjoint = gl.getParameter(ext.GPU_DISJOINT_EXT);
    this.pending = this.pending.filter((query) => {
      if (!gl.getQueryParameter(query, gl.QUERY_RESULT_AVAILABLE)) {
        if (disjoint) gl.deleteQuery(query);
        return !disjoint;
      }
      if (!disjoint)
        this.gpuMs = gl.getQueryParameter(query, gl.QUERY_RESULT) / 1e6;
      gl.deleteQuery(query);
      return false;
    });
    if (disjoint || this.pending.length >= 3 || now - this.sampled < 1000)
      return;
    this.active = gl.createQuery();
    if (this.active) {
      gl.beginQuery(ext.TIME_ELAPSED_EXT, this.active);
      this.sampled = now;
    }
  }
  end() {
    if (!this.active || !this.extension) return;
    this.gl.endQuery(this.extension.TIME_ELAPSED_EXT);
    this.pending.push(this.active);
    this.active = null;
  }
  dispose() {
    for (const query of this.pending) this.gl.deleteQuery(query);
    if (this.active) this.gl.deleteQuery(this.active);
    this.pending = [];
    this.active = null;
  }
}
