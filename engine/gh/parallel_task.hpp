#pragma once

#include <cassert>
#include <cmath>       // max, min
#include <functional>  // reference_wrapper
#include <iterator>
#include <thread>
#include <type_traits>
#include <utility>  // move
#include <vector>

namespace utl {
namespace {

// Helper to forward args to threads as wrapped references in case of lvalue ref
// and const lvalue ref and move if rvalue ref. WARNING: reference_wrapper<T>
// are implicitely convertible to T& but auto will not deduce T&, therefore auto
// must not be used in this context (compiler will produce an error).
template <typename T>
constexpr auto custom_forward(std::remove_reference_t<T>& t) {
  return std::ref(t);
}

template <typename T>
constexpr T&& custom_forward(typename std::remove_reference_t<T>&& t) {
  return std::move(t);
}

// Helpers to adapt some iterator operations to indices.
template <typename Begin, typename End>
constexpr auto custom_distance(Begin begin, End end) {
  if constexpr (std::is_integral_v<Begin> && std::is_integral_v<End>)
    return end - begin;
  else
    return std::distance(begin, end);
}

template <typename Position, typename Count>
constexpr void custom_advance(Position& position, Count count) {
  if constexpr (std::is_integral_v<Position>)
    position += count;
  else
    std::advance(position, count);
}

template <typename Position, typename Count>
constexpr auto custom_next(Position position, Count count) {
  if constexpr (std::is_integral_v<Position>)
    return position + count;
  else
    return std::next(position, count);
}

}  // namespace

// Use this switch for debugging.
#if 0
inline const auto NUM_HARDWARE_THREADS = std::thread::hardware_concurrency();
#else
inline const auto NUM_HARDWARE_THREADS = 1;
#endif

// Perform a parallel task on a range that can be given both as a pair of
// iterators and as a pair of indices (in the latter case the range must be
// contiguous), specify the number of threads or use the constant
// NUM_HARDWARE_THREADS, the input task has to take as first 3 arguments these:
// thread index, local begin index or iterator, local end index or iterator.
// References (lvalue ref, const lvalue ref, rvalue ref) can be used in the task
// args freely and will be forwarded to the std::thread constructor as
// reference_wrappers. If the range is not divisible by the number of threads
// the first few threads will get an extra bit to work on. The main thread also
// does its part of the work (so only num_threads-1 are instantiated). Begin and
// End types can be iterators or integers and must be comparable. Returns the
// number of threads that were actually used to execute the task in parallel or
// 0 if the range is empty and no threads were used.
template <typename Begin, typename End, typename Task, typename... Args>
auto parallel_task(unsigned num_threads, Begin begin, End end, Task&& task,
                   Args&&... args) {
  // Note that std::max and std::min require the same type in their arguments.
  num_threads =
      std::max(std::min(num_threads, std::thread::hardware_concurrency()), 1u);
  assert(num_threads >= 1);

  auto n = custom_distance(begin, end);
  if (n == 0) return unsigned(0);

  auto nloc = n / num_threads + 1;
  auto remainder = n % num_threads;

  std::vector<std::thread> threads(num_threads - 1);

  auto begin_loc = begin;
  auto index = 0;
  for (auto& t : threads) {
    // Only the first few threads do extra work.
    if (index == remainder) nloc -= 1;
    // Each thread receives copies of the arguments, so reference wrappers are
    // needed to have the same semantic of references.
    t = std::thread(task, index, begin_loc, custom_next(begin_loc, nloc),
                    custom_forward<Args>(args)...);
    custom_advance(begin_loc, nloc);
    ++index;
  }
  task(index, begin_loc, end, custom_forward<Args>(args)...);

  for (auto& t : threads) t.join();

  // Return the number of threads that were actually used at runtime.
  return num_threads;
}

}  // namespace utl
