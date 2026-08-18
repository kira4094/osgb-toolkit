#pragma once

#include <robin_hood.h>

#include <cmath>
#include <cstdint>
#include <vector>

template <typename Index, typename Bool>
void find_non_manifold_faces(const std::vector<Index>& f2v,
                             std::vector<Bool>& fflags) {
  // Set up hash table.
  static_assert(sizeof(Index) <= 4);

  constexpr auto hash = [](Index v0, Index v1) {
    return static_cast<uint64_t>(v0) << 32 | static_cast<uint64_t>(v1);
  };

  robin_hood::unordered_map<uint64_t, int> map;

  // Loop over faces and for each unordered edge count how many times it
  // appears.
  auto num_faces = f2v.size() / 3;
  for (auto f = 0; f < num_faces; ++f) {
    auto v0 = f2v[f * 3];
    auto v1 = f2v[f * 3 + 1];
    auto v2 = f2v[f * 3 + 2];

    auto count0 = ++map[hash(std::min(v0, v1), std::max(v0, v1))];
    auto count1 = ++map[hash(std::min(v1, v2), std::max(v1, v2))];
    auto count2 = ++map[hash(std::min(v2, v0), std::max(v2, v0))];

    if (count0 > 2 || count1 > 2 || count2 > 2) fflags[f] = true;
  }
}