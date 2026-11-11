#version 330 core
// QuadRix UI fragment shader (GUI PART 1).
// Текстура (атлас шрифта) × цвет вершины. Порт quad.wgsl → GLSL.
uniform sampler2D texture0;

in vec2 v_uv;
in vec4 v_color;

out vec4 f_color;

void main() {
    f_color = texture(texture0, v_uv) * v_color;
}
