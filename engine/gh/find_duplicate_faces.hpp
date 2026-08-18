#pragma once

#include <robin_hood.h>

#include <algorithm>
#include <functional>
#include <vector>

#include "Mesh.hpp"

template <typename Bool>
void find_duplicate_faces(const Mesh& m, std::vector<Bool>& fflags) {
  constexpr auto equal = [](const int* p, const int* q) {
    auto pmax = std::max({p[0], p[1], p[2]});
    auto pmin = std::min({p[0], p[1], p[2]});
    auto pmid =
        std::max(std::min(p[0], p[1]), std::min(std::max(p[0], p[1]), p[2]));

    auto qmax = std::max({q[0], q[1], q[2]});
    auto qmin = std::min({q[0], q[1], q[2]});
    auto qmid =
        std::max(std::min(q[0], q[1]), std::min(std::max(q[0], q[1]), q[2]));

    return pmin == qmin && pmid == qmid && pmax == qmax;
  };

  // WARNING: Bad but commutative hash function.
  constexpr auto hash = [](const auto* p) {
    return std::hash<int>{}(p[0] ^ p[1] ^ p[2]);
  };

  robin_hood::unordered_set<const int*, decltype(hash), decltype(equal)> set(
      10, hash, equal);

  for (auto f = 0; f < m.num_faces(); ++f) {
    auto [it, inserted] = set.insert(&m.f2v[f * 3]);
    if (!inserted) fflags[f] = true;
  }
}