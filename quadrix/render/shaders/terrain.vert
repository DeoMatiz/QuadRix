#version 330 core
// QuadRix terrain vertex shader.
// Вершина: pos(3) + normal(3) + uv(2). Источник — proto_moderngl.py.
uniform mat4 mvp;

in vec3 in_pos;
in vec3 in_normal;
in vec2 in_uv;

out vec3 v_normal;
out vec2 v_uv;

void main() {
    gl_Position = mvp * vec4(in_pos, 1.0);
    v_normal = in_normal;
    v_uv = in_uv;
}
