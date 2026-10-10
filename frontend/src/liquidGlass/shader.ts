function createShader(gl: WebGLRenderingContext, type: number, source: string) {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.warn("PowerBid liquid cursor shader failed:", gl.getShaderInfoLog(shader));
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}


export function createProgram(gl: WebGLRenderingContext) {
  const vertex = createShader(gl, gl.VERTEX_SHADER, `
    attribute vec2 a_position;
    attribute vec2 a_uv;
    varying vec2 v_uv;
    void main() {
      v_uv = a_uv;
      gl_Position = vec4(a_position, 0.0, 1.0);
    }
  `);
  const fragment = createShader(gl, gl.FRAGMENT_SHADER, `
    precision highp float;
    varying vec2 v_uv;
    uniform sampler2D u_texture;
    uniform vec2 u_resolution;
    uniform vec2 u_lensCenter;
    uniform vec2 u_lensSize;
    uniform float u_strength;
    uniform float u_pinch;
    uniform float u_aberration;
    uniform float u_zoom;
    uniform float u_wobble;
    uniform float u_time;

    float sdRoundBox(vec2 p, vec2 b, float r) {
      vec2 q = abs(p) - b + vec2(r);
      return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
    }

    vec2 warpPoint(vec2 p, float radius) {
      float angle = atan(p.y, p.x);
      float wave =
        sin(angle * 3.0 + u_time * 1.7) * 0.46 +
        cos(angle * 5.0 - u_time * 2.3) * 0.28 +
        sin(angle * 7.0 + u_time * 3.1) * 0.16;
      vec2 radial = normalize(p + vec2(0.0001));
      vec2 tangent = vec2(-radial.y, radial.x);
      return p - radial * wave * u_wobble * radius * 0.055
               + tangent * sin(angle * 2.0 + u_time * 1.25) * u_wobble * radius * 0.012;
    }

    void main() {
      vec2 screenUv = vec2(v_uv.x, 1.0 - v_uv.y);
      vec2 pixel = screenUv * u_resolution;
      vec2 halfSize = max(u_lensSize * 0.5, vec2(2.0));
      float radius = max(2.0, min(halfSize.x, halfSize.y));
      vec2 local = warpPoint(pixel - u_lensCenter, radius);
      float d = sdRoundBox(local, halfSize, radius);
      if (d > 1.5) {
        gl_FragColor = vec4(0.0);
        return;
      }

      float e = 1.0;
      float dx = sdRoundBox(local + vec2(e, 0.0), halfSize, radius) - sdRoundBox(local - vec2(e, 0.0), halfSize, radius);
      float dy = sdRoundBox(local + vec2(0.0, e), halfSize, radius) - sdRoundBox(local - vec2(0.0, e), halfSize, radius);
      vec2 normal = normalize(vec2(dx, dy) + vec2(0.00001));
      float distNorm = clamp(1.0 + d / radius, 0.0, 1.0);
      float effectivePinch = u_pinch * (radius / 100.0);
      float displacement = pow(distNorm, max(0.12, effectivePinch)) * u_strength * 40.0;

      // When the lens is physically close to a viewport/capture boundary there is
      // no real off-screen texture to refract. Fade the displacement there instead
      // of CLAMP_TO_EDGE stretching one texture column into a blank-looking slab.
      float textureEdgeDistance = min(
        min(screenUv.x, 1.0 - screenUv.x),
        min(screenUv.y, 1.0 - screenUv.y)
      );
      float edgeSafety = smoothstep(0.012, 0.075, textureEdgeDistance);
      displacement *= edgeSafety;

      vec2 sampleUv = screenUv - normal * (displacement / u_resolution);

      vec2 centerUv = u_lensCenter / u_resolution;
      sampleUv = (sampleUv - centerUv) / max(u_zoom, 1.0) + centerUv;
      sampleUv = clamp(sampleUv, vec2(0.001), vec2(0.999));

      vec2 chroma = normal * u_aberration * 0.02 * distNorm * edgeSafety;
      vec3 color;
      color.r = texture2D(u_texture, clamp(sampleUv + chroma, 0.0, 1.0)).r;
      color.g = texture2D(u_texture, sampleUv).g;
      color.b = texture2D(u_texture, clamp(sampleUv - chroma, 0.0, 1.0)).b;

      // Keep the surface almost optically clear.
      float edge = smoothstep(0.76, 1.0, distNorm);
      vec3 reflected = texture2D(u_texture, clamp(sampleUv + normal * 0.008 * edge, 0.0, 1.0)).rgb;
      color = mix(color, reflected, edge * 0.035);

      vec2 lightDir = normalize(vec2(-0.62, -0.78));
      float directional = pow(max(dot(normal, lightDir), 0.0), 7.0);
      float rim = edge * (0.008 + directional * 0.070);
      color += vec3(0.62, 0.78, 0.88) * rim;

      float mask = 1.0 - smoothstep(-1.15, 0.9, d);
      float edgeGlass = smoothstep(0.90, 1.0, distNorm) * 0.015;
      gl_FragColor = vec4((color + vec3(edgeGlass)) * mask, mask);
    }
  `);
  if (!vertex || !fragment) return null;
  const program = gl.createProgram();
  if (!program) return null;
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  gl.deleteShader(vertex);
  gl.deleteShader(fragment);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.warn("PowerBid liquid cursor program failed:", gl.getProgramInfoLog(program));
    gl.deleteProgram(program);
    return null;
  }
  return program;
}

