#version 330 core
// QuadRix terrain vertex shader.
// Вершина: pos(3) + normal(3) + uv(2) + color(4).
// in_color — биомный tint грани (v_color), как TerrainVertex::color в Rust.
uniform mat4 mvp;

in vec3 in_pos;
in vec3 in_normal;
in vec2 in_uv;
in vec4 in_color;

out vec3 v_normal;
out vec2 v_uv;
out vec4 v_color;

void main() {
    gl_Position = mvp * vec4(in_pos, 1.0);
    v_normal = in_normal;
    v_uv = in_uv;
    v_color = in_color;
}