#version 330 core
// QuadRix terrain fragment shader.
// Текстура атласа + простой directional light по нормали.
// Источник — proto_moderngl.py (0.35 ambient + 0.65 * N·L).
uniform sampler2D texture0;
uniform vec3 light_dir;
uniform float ambient;

in vec3 v_normal;
in vec2 v_uv;

out vec4 f_color;

void main() {
    vec3 l = normalize(light_dir);
    float light = ambient + (1.0 - ambient) * max(dot(normalize(v_normal), l), 0.0);
    vec3 c = texture(texture0, v_uv).rgb;
    f_color = vec4(c * light, 1.0);
}
