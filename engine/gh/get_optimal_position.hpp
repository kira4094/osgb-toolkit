#pragma once

#include <Eigen/Dense>
#include <cassert>
#include <iostream>
#include <limits>

#include "Quadric.hpp"

static bool get_optimal_position(const Quadric& q, Eigen::Vector3d& x) {
  // if (q.A.determinant() == 0) return false;
  if (q.A.determinant() < std::numeric_limits<float>::epsilon()) return false;

  x = -q.A.ldlt().solve(q.b);
  assert(q.b != Eigen::Vector3d::Zero());

  if ((q.A * x + q.b).norm() / q.b.norm() >
      std::numeric_limits<float>::epsilon()) {
    std::cerr << "WARNING: High relative error.\n";
    return false;
  }

  return true;
}