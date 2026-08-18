#pragma once

#include <cassert>
#include <vector>

#include "Mesh.hpp"

static void split_into_connected_components(
    const Mesh& m, const std::vector<std::vector<int>>& cc2f,
    std::vector<Mesh>& ms) {
  assert(!m.v.empty());
  assert(!m.f2v.empty());
  assert(!cc2f.empty());

  for (auto fs : cc2f) {
    ms.emplace_back();
    auto& mc = ms.back();

    // Copy indices.
    for (auto f : fs) {
      mc.f2v.insert(mc.f2v.end(), &m.f2v[f * 3], &m.f2v[f * 3] + 3);
      if (!m.f2t.empty())
        mc.f2t.insert(mc.f2t.end(), &m.f2t[f * 3], &m.f2t[f * 3] + 3);
      if (!m.f2n.empty())
        mc.f2n.insert(mc.f2n.end(), &m.f2n[f * 3], &m.f2n[f * 3] + 3);
    }

    // Copy data and update indices.
    constexpr auto task = [](const auto& obuf, auto& buf, auto& ibuf,
                             auto count, auto size, auto& indmap) {
      indmap.assign(count, -1);
      auto new_index = 0;
      for (auto& i : ibuf) {
        if (indmap[i] == -1) {
          buf.insert(buf.end(), &obuf[i * size], &obuf[i * size] + size);
          indmap[i] = new_index++;
        }
        i = indmap[i];
      }
    };

    std::vector<int> indmap;
    task(m.v, mc.v, mc.f2v, m.num_vertices(), 3, indmap);
    if (!m.t.empty()) task(m.t, mc.t, mc.f2t, m.num_texture(), 2, indmap);
    if (!m.n.empty()) task(m.n, mc.n, mc.f2n, m.num_normals(), 3, indmap);
  }
}