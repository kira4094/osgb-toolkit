#pragma once

#include <algorithm>
#include <numeric>
#include <vector>

#include "Mesh.hpp"
#include "parallel_task.hpp"

static void make_edges(Mesh& m) {
  // Make edge to vertex connectivity.
  {
    std::vector<int> counts(utl::NUM_HARDWARE_THREADS, 0);
    {
      const auto task = [&](auto i, auto v, auto end) {
        auto count = 0;
        for (; v < end; ++v)
          for (auto vv : m.v2v[v])
            if (v < vv) ++count;

        counts[i] = count;
      };
      utl::parallel_task(utl::NUM_HARDWARE_THREADS, 0, m.num_vertices(), task);
    }
    {
      std::vector<int> offsets(counts.size(), 0);
      std::partial_sum(counts.begin(), counts.end() - 1, offsets.begin() + 1);

      decltype(m.e2v)(std::reduce(counts.begin(), counts.end()) * 2)
          .swap(m.e2v);

      const auto task = [&](auto i, auto v, auto end) {
        auto e = offsets[i];
        for (; v < end; ++v)
          for (auto vv : m.v2v[v]) {
            if (v < vv) {
              m.e2v[e * 2] = v;
              m.e2v[e * 2 + 1] = vv;
              ++e;
            }
          }
      };
      utl::parallel_task(utl::NUM_HARDWARE_THREADS, 0, m.num_vertices(), task);
    }
  }

  // Make vertex to edge connectivity.
  {
    decltype(m.v2e)(m.num_vertices()).swap(m.v2e);
    for (auto e = 0; e < m.num_edges(); ++e) {
      m.v2e[m.e2v[e * 2]].push_back(e);
      m.v2e[m.e2v[e * 2 + 1]].push_back(e);
    }
  }

  // Make edge to face connectivity (only for manifold meshes).
  {
    decltype(m.e2f)(m.e2v.size(), -1).swap(m.e2f);
    const auto task = [&](auto, auto e, auto end) {
      for (; e < end; ++e) {
        auto v0 = m.e2v[e * 2];
        auto v1 = m.e2v[e * 2 + 1];

        // TODO: This is less efficient because it will scan the entire range
        // (if manifold at most 2 flaps can be found, if non-manifold can cause
        // problems with overwriting as there are more than 2 flaps).
        auto it = std::set_intersection(m.v2f[v0].cbegin(), m.v2f[v0].cend(),
                                        m.v2f[v1].cbegin(), m.v2f[v1].cend(),
                                        &m.e2f[e * 2]);
        // No more than 2 flaps for a manifold mesh.
        assert(it <= &m.e2f[e * 2] + 2);
      }
    };
    utl::parallel_task(utl::NUM_HARDWARE_THREADS, 0, m.num_edges(), task);
  }
}