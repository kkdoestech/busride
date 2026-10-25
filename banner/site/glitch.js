// A whole-screen glitch for short bursts, like the kkdoestech profile banners: horizontal strips
// slide sideways, red and blue split apart, and a few coloured blocks flash. Identity at 0.

export const GlitchShader = {
  uniforms: { tDiffuse: { value: null }, uAmount: { value: 0 }, uSeed: { value: 0 } },
  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse;
    uniform float uAmount, uSeed;
    varying vec2 vUv;

    float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

    void main() {
      vec2 uv = vUv;
      float band = floor(uv.y * 48.0);
      float hit = step(1.0 - 0.3 * uAmount, hash(vec2(band, uSeed)));
      uv.x += hit * (hash(vec2(band, uSeed + 5.0)) - 0.5) * 0.09 * uAmount;
      float split = 0.003 * uAmount + hit * 0.004;
      vec4 c = texture2D(tDiffuse, uv);
      c.r = texture2D(tDiffuse, uv + vec2(split, 0.0)).r;
      c.b = texture2D(tDiffuse, uv - vec2(split, 0.0)).b;

      vec2 cell = floor(vec2(uv.x * 24.0, uv.y * 70.0));
      float block = step(1.0 - 0.012 * uAmount, hash(cell + uSeed * 1.37));
      float pick = hash(cell + 9.1);
      vec3 colour = pick < 0.25 ? vec3(0.04, 1.0, 0.007)   // green
                  : pick < 0.5 ? vec3(1.0, 0.65, 0.0)      // yellow
                  : pick < 0.75 ? vec3(1.0, 0.014, 0.046)  // red
                  : vec3(0.0, 0.39, 1.0);                  // blue
      c.rgb = mix(c.rgb, colour, block);
      gl_FragColor = c;
    }`,
};
