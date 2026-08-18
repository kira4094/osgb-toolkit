#pragma once

#include <vector>

#include "Mesh.hpp"
#include "Quadric.hpp"

auto make_face_quadrics(const Mesh& m) -> std::vector<Quadric>;