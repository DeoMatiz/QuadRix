#version 330 core
// QuadRix UI vertex shader (GUI PART 1).
// Вершина UI-квада: pos(2) + uv(2) + color(4). Порт quad.wgsl → GLSL.
// Координаты — в GUI-пикселях, projection переводит их в clip space.
uniform mat4 projection;

in vec2 in_pos;
in vec2 in_uv;
in vec4 in_color;

out vec2 v_uv;
out vec4 v_color;

void main() {
    gl_Position = projection * vec4(in_pos, 0.0, 1.0);
    v_uv = in_uv;
    v_color = in_color;
}
