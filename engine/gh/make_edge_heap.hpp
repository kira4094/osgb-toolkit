#pragma once

#include <Eigen/Dense>
#include <algorithm>
#include <vector>

#include "Mesh.hpp"
#include "Quadric.hpp"
#include "WriterVTK.hpp"
#include "get_optimal_position.hpp"
#include "parallel_task.hpp"

static void make_edge_heap(const Mesh& m, const std::vector<Quadric>& vq,
                           std::vector<std::tuple<double, int, int>>& eh,
                           std::vector<Eigen::Vector3d>& xs) {
  eh.resize(m.num_edges());
  xs.resize(m.num_edges());

  // Trying parallel even if it repeats calculations. TODO: redo vertex-wise.
  const auto task = [&](auto, auto e, auto end) {
    for (; e < end; ++e) {
      auto v0 = m.e2v[e * 2];
      auto v1 = m.e2v[e * 2 + 1];

      // Sum quadrics.
      Quadric q;
      q.A = vq[v0].A + vq[v1].A;
      q.b = vq[v0].b + vq[v1].b;
      q.c = vq[v0].c + vq[v1].c;

      // Compute position.
      Eigen::Vector3d x;
      if (!get_optimal_position(q, x)) {
        std::cout << "WARNING: Initial optimal position failed.\n";
        Eigen::Vector3d x0{&m.v[v0 * 3]};
        Eigen::Vector3d x1{&m.v[v1 * 3]};
        x = (x0 + x1) * 0.5;
      }

      // Cost is always positive up to floating point arithmetic.
      auto cost = std::abs(q(x));

      eh[e] = std::make_tuple(cost, e, 0);
      xs[e] = x;
    }
  };
  utl::parallel_task(utl::NUM_HARDWARE_THREADS, 0, m.num_edges(), task);

  std::make_heap(eh.begin(), eh.end(), [](const auto& l, const auto& r) {
    return std::get<0>(l) > std::get<0>(r);
  });
}