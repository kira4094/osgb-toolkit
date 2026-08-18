#pragma once

#include <Eigen/Dense>
#include <cassert>
#include <limits>
#include <vector>

#include "Mesh.hpp"
#include "Quadric.hpp"

static auto make_vertex_quadrics(const Mesh& m,
                                 const std::vector<char>& is_boundary_edge,
                                 const std::vector<char>& is_boundary_vertex) {
  // Weight needed to not have degenerate quadrics in case of planar meshes.
  constexpr auto WEIGHT = 1.0e-10;
  // Weight needed to preserved boundaris by adding an orthogonal plane to
  // boundary edges.
  constexpr auto BOUNDARY_WEIGHT = 1.0e2;

  // Return.
  std::vector<Quadric> vq;
  vq.reserve(m.num_vertices());

  // Initialize vertex quadrics to handle degenerate cases.
  for (auto v = 0; v < m.num_vertices(); ++v) {
    auto x = Eigen::Vector3d{&m.v[v * 3]};

    // Using c++20 emplace_back aggregate.
    vq.emplace_back(
        WEIGHT * Eigen::Matrix<double, 3, 3, Eigen::RowMajor>::Identity(),
        -WEIGHT * x, WEIGHT * x.squaredNorm());
  }

  // Accumulate quadrics.
  for (auto f = 0; f < m.num_faces(); ++f) {
    Eigen::Vector3d n{&m.fn[f * 3]};
    Eigen::Vector3d x{&m.v[m.f2v[f * 3] * 3]};

    if (m.fa[f] > std::numeric_limits<double>::epsilon()) {
      auto q = make_quadric(n, x);

      for (auto i = 0; i < 3; ++i) {
        auto v = m.f2v[f * 3 + i];
        vq[v].A += q.A;
        vq[v].b += q.b;
        vq[v].c += q.c;
      }
    }
  }

  // Boundary preservation quadrics.
  for (auto e = 0; e < m.num_edges(); ++e) {
    if (!is_boundary_edge[e]) continue;

    auto v0 = m.e2v[e * 2];
    auto v1 = m.e2v[e * 2 + 1];

    assert(v0 != v1);
    assert(is_boundary_vertex[v0]);
    assert(is_boundary_vertex[v1]);

    Eigen::Vector3d x0{&m.v[v0 * 3]};
    Eigen::Vector3d x1{&m.v[v1 * 3]};
    auto s = x1 - x0;

    assert(m.e2f[e * 2] != -1);
    // 注: qslim 原断言 e2f[e*2+1]==1 要求严格流形; OSGB 瓦片间存在非流形边,
    // 放宽为"至少有一个邻面"并安全跳过异常边
    if (m.e2f[e * 2 + 1] < 0) continue;

    Eigen::Vector3d fn{&m.fn[m.e2f[e * 2] * 3]};
    auto n = s.cross(fn);
    auto norm = n.norm();

    if (norm > std::numeric_limits<float>::epsilon()) {
      n /= norm;
      auto q = make_quadric(n, x0);
      q.A *= BOUNDARY_WEIGHT;
      q.b *= BOUNDARY_WEIGHT;
      q.c *= BOUNDARY_WEIGHT;

      vq[v0].A += q.A;
      vq[v0].b += q.b;
      vq[v0].c += q.c;

      vq[v1].A += q.A;
      vq[v1].b += q.b;
      vq[v1].c += q.c;
    }
  }

  return vq;
}