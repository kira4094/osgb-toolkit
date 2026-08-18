#pragma once

#include <vector>

#include "Mesh.hpp"

template <typename Bool>
void find_boundary_edges(const Mesh& m, std::vector<Bool>& eflags) {
  for (auto e = 0; e < m.num_edges(); ++e)
    if (m.e2f[2 * e + 1] == -1) eflags[e] = true;
}