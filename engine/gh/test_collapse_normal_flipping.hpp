#pragma once

#include <Eigen/Dense>
#include <algorithm>
#include <cassert>
#include <iostream>
#include <tuple>
#include <vector>

#include "Mesh.hpp"

static bool test_collapse_normal_flipping(
    const Mesh& m, int e, const double* x, double tol,
    std::vector<std::tuple<int, Eigen::Vector3d, double>>& ns) {
  if (m.edel[e]) return false;

  auto v0 = m.e2v[e * 2];
  auto v1 = m.e2v[e * 2 + 1];
  auto f0 = m.e2f[e * 2];
  auto f1 = m.e2f[e * 2 + 1];

  assert(v0 != v1);
  assert(f0 != f1);

  // This is to do a single allocation.
  ns.reserve(std::count_if(m.v2f[v0].begin(), m.v2f[v0].end(),
                           [&](auto f) { return !m.fdel[f]; }) +
             std::count_if(m.v2f[v1].begin(), m.v2f[v1].end(),
                           [&](auto f) { return !m.fdel[f]; }) -
             -2 - (f1 == -1 ? 0 : 2));

  for (auto v : {v0, v1}) {
    for (auto f : m.v2f[v]) {
      if (f == f0 || f == f1 || m.fdel[f]) continue;

      Eigen::Vector3d x0{v == m.f2v[f * 3] ? x : &m.v[m.f2v[f * 3] * 3]};
      Eigen::Vector3d x1{v == m.f2v[f * 3 + 1] ? x
                                               : &m.v[m.f2v[f * 3 + 1] * 3]};
      Eigen::Vector3d x2{v == m.f2v[f * 3 + 2] ? x
                                               : &m.v[m.f2v[f * 3 + 2] * 3]};

      assert(x0 != x1);
      assert(x0 != x2);
      assert(x1 != x2);

      ns.push_back({f, (x1 - x0).cross(x2 - x0), 0.0});
      auto& n = std::get<1>(ns.back());
      auto& norm = std::get<2>(ns.back());
      norm = n.norm();

      // If mesh starts without null normals it should not ever have null
      // normals.
      if (norm == 0.0 || m.fa[f] == 0.0) {
        std::cerr << "WARNING: Null normals while testing for normal "
                     "flipping.\n";
        return false;
      }
      assert(norm != 0.0);
      assert(m.fa[f] != 0.0);

      n /= norm;

      // Reject collapse if the old to new normal cosine is less than a
      // tolerance.
      if (n.dot(Eigen::Map<const Eigen::Vector3d>{&m.fn[f * 3]}) < tol)
        return false;
    }
  }

  return true;
}