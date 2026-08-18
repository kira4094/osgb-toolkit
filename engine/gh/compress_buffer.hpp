#pragma once

#include <algorithm>
#include <cassert>
#include <numeric>

// Compress a raw buffer of count elements of SIZE * sizeof(Value) bytes
// eliminating elements marked as removed. Return the new size of the buffer.
// Optional argument is for the map from old indices to new. Only surviving
// indices will be updated, removed indices will maintain their original value.
template <size_t SIZE, typename Value, typename Bool, typename Index = int>
constexpr auto compress_buffer(Value* buf, size_t count, const Bool* removed,
                               Index* indices = nullptr) -> size_t {
  static_assert(SIZE > 0);
  assert(buf);
  assert(count > 0);
  assert(removed);

  // Find the index of the first element that needs to be removed in order to
  // start copying.
  size_t i = 0;
  while (i < count && !removed[i]) ++i;

  if (indices) std::iota(indices, indices + i, Index{0});

  // Start from the first element in the buffer that needs to be removed.
  for (size_t j = i + 1; j < count; ++j) {
    if (!removed[j]) {
      std::copy(buf + j * SIZE, buf + (j + 1) * SIZE, buf + i * SIZE);
      if (indices) indices[j] = i;
      i++;
    }
  }

  // Max index cannot exceed original count.
  assert(i > 0);
  assert(i <= count);

  return i;
}
