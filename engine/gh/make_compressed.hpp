#pragma once

#include <algorithm>
#include <vector>

#include "Mesh.hpp"
#include "compress_buffer.hpp"

static void make_compressed(Mesh& m) {
  // Compress generic data before removing faces.
  compress_buffer<3>(&m.fn[0], m.num_faces(), &m.fdel[0]);
  compress_buffer<1>(&m.fa[0], m.num_faces(), &m.fdel[0]);

  // Remove all the faces.
  auto num_faces = compress_buffer<3>(&m.f2v[0], m.num_faces(), &m.fdel[0]);
  m.f2v.resize(num_faces * 3);

  // Find and remove redunant vertices.
  std::vector<char> vdel(m.num_vertices(), true);
  for (auto v : m.f2v)
    if (vdel[v]) vdel[v] = false;

  std::vector<int> indmap(m.num_vertices(), -1);
  m.v.resize(
      compress_buffer<3>(&m.v[0], m.num_vertices(), &vdel[0], &indmap[0]) * 3);

  // Reindex faces if some vertices are removed.
  for (auto& v : m.f2v) v = indmap[v];
}