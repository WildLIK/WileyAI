import { useEffect, useRef } from "react";

const vertex = `
attribute vec2 a_position;
void main() { gl_Position = vec4(a_position, 0.0, 1.0); }
`;
const fragment = `
precision highp float;
uniform vec2 u_resolution;
uniform float u_time;

float hash(vec2 p) {
  vec3 a = fract(vec3(p.xyx) * .1031);
  a += dot(a, a.yzx + 33.33);
  return fract((a.x + a.y) * a.z);
}
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  f = f*f*(3.0-2.0*f);
  return mix(mix(hash(i), hash(i+vec2(1,0)), f.x),
             mix(hash(i+vec2(0,1)), hash(i+vec2(1,1)), f.x), f.y);
}
float fbm(vec2 p) {
  float sum = 0.0, amplitude = .5;
  mat2 turn = mat2(.8,-.6,.6,.8);
  for (int i=0; i<4; i++) {
    sum += amplitude * noise(p);
    p = turn*p*2.03 + 4.1;
    amplitude *= .5;
  }
  return sum;
}
void main() {
  vec2 p = (gl_FragCoord.xy*2.0-u_resolution)/u_resolution.y;
  p *= 1.25;
  float t = u_time*.055;
  vec2 q = p;
  q += .8*vec2(fbm(p*1.5+vec2(t*.4, -t*.25)),
                fbm(p*1.5+vec2(4.5-t*.3, 1.5+t*.15))) - .4;
  float cloud = fbm(q*2.4 + vec2(t*.1, -t*.2));
  float twist = fbm(q*3.3 + vec2(8.0, t*.3));
  float envelope = exp(-dot(p*vec2(.58,.95), p*vec2(.58,.95))*1.5);
  float wave = q.y*.85 + sin(q.x*1.8-t*.3)*.38 + cloud*1.6;
  float ribbon = exp(-abs(wave-.8)*8.0);
  float lace = pow(max(0.0, 1.0-abs(sin(wave*9.0+twist*2.0))), 24.0);
  float body = smoothstep(.22,.72,cloud) * envelope;
  float gold = exp(-dot((q-vec2(-.06,.1))*vec2(1.65,1.5),
                       (q-vec2(-.06,.1))*vec2(1.65,1.5))*2.5);
  vec3 violet = vec3(.39,.19,.83);
  vec3 blue = vec3(.21,.45,1.0);
  vec3 amber = vec3(1.0,.64,.16);
  vec3 hue = mix(violet, blue, smoothstep(.0,1.25,q.x));
  hue = mix(hue, amber, gold*.9);
  vec3 color = vec3(.017,.014,.033);
  color += violet * body*.36;
  color += hue * envelope * (ribbon*.52+lace*.24) * (.35+cloud);
  color += amber * gold * body*.72;
  vec2 sparkPos = p-vec2(.77+sin(t*.28)*.08,-.04+cos(t*.3)*.12);
  float spark = exp(-dot(sparkPos,sparkPos)*20.0);
  color += vec3(.25,.46,1.0)*spark*.5;
  color += vec3(.9,.87,1.0)*pow(spark,9.0)*.45;
  // A dark, softly changing cavity gives the ribbons a folded, volumetric edge.
  float hollow = length((q+vec2(.75,-.02))*vec2(1.0,.93));
  color *= mix(.09,1.0,smoothstep(.28,.47,hollow));
  float edge = exp(-abs(hollow-.43)*65.0);
  color += vec3(.3,.35,.69)*edge*envelope*.45;
  color *= .48 + .52*envelope;
  gl_FragColor = vec4(color,1.0);
}
`;

/** One small GPU surface, only while this theme is selected. No frame loop when paused. */
export function NebulaBackground({ motion }: { motion: "full" | "reduced" }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const node = canvas.current!;
    const gl = node.getContext("webgl", {
      alpha: false,
      antialias: false,
      depth: false,
      stencil: false,
      powerPreference: "low-power",
    });
    if (!gl) {
      node.dataset.state = "fallback";
      return;
    }
    const media = matchMedia("(prefers-reduced-motion: reduce)");
    let nativeActive = true,
      receivedActivity = false,
      disposed = false;
    let frame = 0,
      previous = 0,
      elapsed = 0,
      running = false;
    let program: WebGLProgram | null = null;
    let buffer: WebGLBuffer | null = null;
    let shaders: WebGLShader[] = [];
    let resolution: WebGLUniformLocation | null = null,
      clock: WebGLUniformLocation | null = null;
    const destroy = () => {
      if (program) gl.deleteProgram(program);
      if (buffer) gl.deleteBuffer(buffer);
      shaders.forEach((shader) => gl.deleteShader(shader));
      program = null;
      buffer = null;
      shaders = [];
    };
    const initialize = () => {
      destroy();
      program = gl.createProgram();
      if (!program) return false;
      for (const [type, source] of [
        [gl.VERTEX_SHADER, vertex],
        [gl.FRAGMENT_SHADER, fragment],
      ] as const) {
        const shader = gl.createShader(type);
        if (!shader) return false;
        shaders.push(shader);
        gl.shaderSource(shader, source);
        gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) return false;
        gl.attachShader(program, shader);
      }
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return false;
      gl.useProgram(program);
      buffer = gl.createBuffer();
      if (!buffer) return false;
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(
        gl.ARRAY_BUFFER,
        new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
        gl.STATIC_DRAW,
      );
      const position = gl.getAttribLocation(program, "a_position");
      gl.enableVertexAttribArray(position);
      gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
      resolution = gl.getUniformLocation(program, "u_resolution");
      clock = gl.getUniformLocation(program, "u_time");
      return true;
    };
    const draw = () => {
      if (!program || gl.isContextLost()) return;
      gl.viewport(0, 0, node.width, node.height);
      gl.uniform2f(resolution, node.width, node.height);
      gl.uniform1f(clock, elapsed);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    };
    const stop = () => {
      cancelAnimationFrame(frame);
      frame = 0;
      previous = 0;
      running = false;
    };
    const animate = (now: number) => {
      if (!running) return;
      if (!previous || now - previous >= 1000 / 24) {
        if (previous) elapsed += Math.min(0.1, (now - previous) / 1000);
        previous = now;
        draw();
      }
      frame = requestAnimationFrame(animate);
    };
    const refresh = () => {
      stop();
      if (gl.isContextLost() || !program) {
        node.dataset.state = "fallback";
        return;
      }
      draw();
      if (!nativeActive || document.hidden || !document.hasFocus()) {
        node.dataset.state = "paused";
        return;
      }
      if (motion === "reduced" || media.matches) {
        node.dataset.state = "still";
        return;
      }
      node.dataset.state = "running";
      running = true;
      frame = requestAnimationFrame(animate);
    };
    const resize = () => {
      const { width, height } = node.getBoundingClientRect();
      const scale = Math.min(
        0.66,
        960 / Math.max(1, width),
        540 / Math.max(1, height),
      );
      node.width = Math.max(1, Math.round(width * scale));
      node.height = Math.max(1, Math.round(height * scale));
      refresh();
    };
    const lost = (event: Event) => {
      event.preventDefault();
      stop();
      node.dataset.state = "fallback";
    };
    const restored = () => {
      if (initialize()) resize();
      else {
        destroy();
        node.dataset.state = "fallback";
      }
    };
    const ready = initialize();
    if (!ready) {
      node.dataset.state = "fallback";
      destroy();
      return;
    }
    const activity = (state: { visible: boolean; focused: boolean }) => {
      nativeActive = state.visible && state.focused;
      refresh();
    };
    const unsubscribe = window.wiley.onWindowActivity((state) => {
      receivedActivity = true;
      activity(state);
    });
    void window.wiley
      .windowActivity()
      .then((state) => {
        if (!disposed && !receivedActivity) activity(state);
      })
      .catch(() => {
        /* Browser visibility remains available. */
      });
    node.addEventListener("webglcontextlost", lost);
    node.addEventListener("webglcontextrestored", restored);
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("focus", refresh);
    window.addEventListener("blur", refresh);
    media.addEventListener("change", refresh);
    const observer = new ResizeObserver(resize);
    observer.observe(node);
    resize();
    return () => {
      disposed = true;
      unsubscribe();
      stop();
      observer.disconnect();
      destroy();
      node.removeEventListener("webglcontextlost", lost);
      node.removeEventListener("webglcontextrestored", restored);
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("focus", refresh);
      window.removeEventListener("blur", refresh);
      media.removeEventListener("change", refresh);
    };
  }, [motion]);
  return (
    <div className="nebula-backdrop" aria-hidden="true">
      <canvas ref={canvas} className="nebula-canvas" />
    </div>
  );
}
