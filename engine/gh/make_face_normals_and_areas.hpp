#pragma once

#include <Eigen/Dense>

#include "Mesh.hpp"
#include "parallel_task.hpp"

static void make_face_normals_and_areas(Mesh& m) {
  decltype(m.fn)(m.num_faces() * 3).swap(m.fn);
  decltype(m.fa)(m.num_faces()).swap(m.fa);

  const auto task = [&](auto, auto f, auto end) {
    for (; f < end; ++f) {
      auto v0 = m.f2v[f * 3];
      auto v1 = m.f2v[f * 3 + 1];
      auto v2 = m.f2v[f * 3 + 2];

      Eigen::Vector3d x0{&m.v[v0 * 3]};
      Eigen::Vector3d x1{&m.v[v1 * 3]};
      Eigen::Vector3d x2{&m.v[v2 * 3]};

      Eigen::Map<Eigen::Vector3d> n{&m.fn[f * 3]};
      n = (x1 - x0).cross(x2 - x0);
      auto norm = n.norm();
      if (norm != 0.0) n /= norm;
      m.fa[f] = norm;
    }
  };
  utl::parallel_task(utl::NUM_HARDWARE_THREADS, 0, m.num_faces(), task);
}