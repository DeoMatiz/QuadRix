#version 330 core
// QuadRix panorama vertex shader (MainMenu background).
// Порт gfx/panorama.wgsl::vs_panorama: position-only cube, direction
// передаёт исходную позицию вершины (samplerCube её и сэмплит).
uniform mat4 projection;

out vec3 v_dir;

void main() {
    vec3 corners[8] = vec3[8](
        vec3(-1.0, -1.0, -1.0), vec3(1.0, -1.0, -1.0),
        vec3(1.0, 1.0, -1.0), vec3(-1.0, 1.0, -1.0),
        vec3(-1.0, -1.0, 1.0), vec3(1.0, -1.0, 1.0),
        vec3(1.0, 1.0, 1.0), vec3(-1.0, 1.0, 1.0)
    );
    int indices[36] = int[36](
        4, 7, 6, 4, 6, 5, 5, 6, 2, 5, 2, 1,
        1, 2, 3, 1, 3, 0, 0, 3, 7, 0, 7, 4,
        7, 3, 2, 7, 2, 6, 0, 4, 5, 0, 5, 1
    );
    vec3 position = corners[indices[gl_VertexID]];
    v_dir = position;
    gl_Position = projection * vec4(position, 1.0);
}
