#version 330 core
// QuadRix panorama fragment shader (MainMenu background).
// Порт gfx/panorama.wgsl::fs_panorama.
uniform samplerCube panorama;

in vec3 v_dir;

out vec4 f_color;

void main() {
    f_color = texture(panorama, v_dir);
}
