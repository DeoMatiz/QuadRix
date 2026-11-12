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
    // Если uniform не задан (0), normalize(0) даёт NaN и всё чёрное —
    // поэтому подставляем направление и ambient по умолчанию.
    vec3 ld = length(light_dir) > 1e-4 ? normalize(light_dir) : vec3(0.0, 1.0, 0.0);
    float amb = clamp(ambient, 0.05, 1.0);
    float light = amb + (1.0 - amb) * max(dot(normalize(v_normal), ld), 0.0);
    vec3 c = texture(texture0, v_uv).rgb;
    f_color = vec4(c * light, 1.0);
}
