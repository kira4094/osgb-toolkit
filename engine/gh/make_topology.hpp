#pragma once

#include <algorithm>
#include <vector>

#include "Mesh.hpp"
#include "parallel_task.hpp"

static void make_topology(Mesh& m) {
  // Make vertex to face connectivity.
  {
    decltype(m.v2f)(m.num_vertices()).swap(m.v2f);

    for (auto f = 0; f < m.num_faces(); ++f) {
      m.v2f[m.f2v[f * 3]].push_back(f);
      m.v2f[m.f2v[f * 3 + 1]].push_back(f);
      m.v2f[m.f2v[f * 3 + 2]].push_back(f);
    }
  }

  // Make vertex to vertex connectivity.
  {
    decltype(m.v2v)(m.num_vertices()).swap(m.v2v);

    const auto task = [&](auto, auto v, auto end) {
      for (; v < end; ++v) {
        for (auto f : m.v2f[v])
          for (const auto* vv = &m.f2v[f * 3]; vv < &m.f2v[f * 3] + 3; ++vv)
            if (*vv != v) m.v2v[v].push_back(*vv);

        std::sort(m.v2v[v].begin(), m.v2v[v].end());
        m.v2v[v].erase(std::unique(m.v2v[v].begin(), m.v2v[v].end()),
                       m.v2v[v].end());
      }
    };

    utl::parallel_task(utl::NUM_HARDWARE_THREADS, 0, m.num_vertices(), task);
  }

  // Make face to face connectivity.
  {
    decltype(m.f2f)(m.num_faces()).swap(m.f2f);

    const auto task = [&](auto, auto f, auto end) {
      for (; f < end; ++f) {
        for (const auto* v = &m.f2v[f * 3]; v < &m.f2v[f * 3] + 3; ++v)
          for (auto ff : m.v2f[*v])
            if (ff != f) m.f2f[f].push_back(ff);

        std::sort(m.f2f[f].begin(), m.f2f[f].end());
        m.f2f[f].erase(std::unique(m.f2f[f].begin(), m.f2f[f].end()),
                       m.f2f[f].end());
      }
    };

    utl::parallel_task(utl::NUM_HARDWARE_THREADS, 0, m.num_faces(), task);
  }
}