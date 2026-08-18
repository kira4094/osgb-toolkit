#pragma once

#include <cassert>
#include <vector>

#include "Mesh.hpp"

static bool test_collapse_boundaries(
    const Mesh& m, int e, const std::vector<char>& is_boundary_edge,
    const std::vector<char>& is_boundary_vertex) {
  auto v0 = m.e2v[e * 2];
  auto v1 = m.e2v[e * 2 + 1];

  // WARNING: This a temporary fix that avoids pinching.
  if (is_boundary_vertex[v0] && is_boundary_vertex[v1] && !is_boundary_edge[e])
    return false;

  return true;
}