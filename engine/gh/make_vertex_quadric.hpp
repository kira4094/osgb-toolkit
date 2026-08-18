#pragma once

#include <Eigen/Dense>
#include <vector>

#include "Mesh.hpp"
#include "Quadric.hpp"

auto make_vertex_quadric(const Mesh& m, int v, const std::vector<Quadric>& fq) {
  Quadric q{Eigen::Matrix3d::Zero(), Eigen::Vector3d::Zero(), 0.0};

  for (auto f : m.v2f[v]) {
    if (m.fdel[f]) continue;

    q.A += fq[f].A;
    q.b += fq[f].b;
    q.c += fq[f].c;
  }

  return q;
}
