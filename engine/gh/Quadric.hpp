#pragma once

#include <Eigen/Core>

// clang-format off
// Given a plane with unit normal n and equation n*x=dist the quadric is:
// A = n * n^T
// b = dist * n
// c = dist^2
// The cost is computed as:
// cost = (A * x + 2 * b) * x + c
// The minimizer of the quadric is therefore:
// x = -A^-1 * b
// clang-format on
struct Quadric {
  Eigen::Matrix<double, 3, 3, Eigen::RowMajor> A;
  Eigen::Vector3d b;
  double c;

  template <typename DerivedX>
  double operator()(const Eigen::MatrixBase<DerivedX>& x) const {
    return (A * x + 2 * b).dot(x) + c;
  }
};

template <typename DerivedN, typename DerivedX>
auto make_quadric(const Eigen::MatrixBase<DerivedN>& n,
                  const Eigen::MatrixBase<DerivedX>& x) {
  Quadric q;
  q.A = n * n.transpose();
  auto dist = -n.dot(x);
  q.b = dist * n;
  q.c = dist * dist;
  return q;
}