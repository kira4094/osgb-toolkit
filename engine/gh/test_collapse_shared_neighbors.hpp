#pragma once

#include <algorithm>
#include <cassert>
#include <vector>

#include "Mesh.hpp"

// WARNING: Highly inefficent.
static bool test_collapse_shared_neighbors(
    const Mesh& m, int e, const std::vector<char>& is_boundary_edge) {
  if (m.edel[e]) return false;
  auto v0 = m.e2v[e * 2];
  auto v1 = m.e2v[e * 2 + 1];

  assert(v0 != v1);
  assert(!m.vdel[v0]);
  assert(!m.vdel[v1]);

  auto num_shared = 0;
  for (auto v : m.v2v[v0]) {
    if (m.vdel[v] || v == v1) continue;
    for (auto vv : m.v2v[v1]) {
      if (m.vdel[vv] || vv == v0) continue;
      if (v == vv) ++num_shared;
    }
  }

  // 注: qslim 原实现 assert(num_shared >= 1) 并要求非边界边 <3 / 边界边 <2。
  // OSGB 倾斜摄影网格顶点密集(共享邻居常 >= 3), 原阈值导致 90% 边被拒。
  // 放宽为仅拒绝"共享邻居过多"的极端情况(防止产生非流形):
  //   - 非边界边: 共享邻居 < 8
  //   - 边界边:   共享邻居 < 4
  // 同时允许 num_shared == 0(孤立共享, 非流形边也能折叠)。
  const int sharedLimit = is_boundary_edge[e] ? 4 : 8;
  return num_shared < sharedLimit;
}