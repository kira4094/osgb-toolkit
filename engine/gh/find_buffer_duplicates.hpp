#pragma once

#include <robin_hood.h>

#include <cassert>
#include <functional>
#include <unordered_map>

// Find duplicate memory of size SIZE * sizeof(Value) inside a buffer and mark
// duplicates to be removed, also optionally return the old to new index map.
template <size_t SIZE, typename Hash, typename Value, typename Bool,
          typename Index = int>
constexpr void find_buffer_duplicates(Hash&& hash, const Value* buf,
                                      size_t count, Bool* duplicated,
                                      Index* indices = nullptr) {
  static_assert(SIZE > 0);
  assert(buf);
  assert(count > 0);
  assert(duplicated);

  constexpr auto compare = [](const Value* lhs, const Value* rhs) {
    return std::equal(lhs, lhs + SIZE, rhs);
  };

  std::unordered_map<const Value*, Index, Hash, decltype(compare)> map(10, hash,
                                                                       compare);

  for (size_t i = 0; i < count; ++i) {
    auto [it, inserted] = map.insert({buf + i * SIZE, i});
    indices[i] = it->second;
    if (!inserted) duplicated[i] = true;
  }
}
