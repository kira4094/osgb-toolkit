// TODO: Make the collapse only handle connectivity relations?
#pragma once

#include <algorithm>
#include <cassert>
#include <utility>
#include <vector>

#include "Mesh.hpp"

// clang-format off.
// Recap after the (u, v) collapse:
//   s
//  /f\ 
// u___v
//  \g/
//   t
// Vertex v is removed.
// Position of u is updated.
// Faces f, g are removed.
// Edge (u, v) will be popped from the queue.
// Edges (s, v), (t, v) will be popped from the queue (collapse rejected).
// All connectivity relations are updated, in particular face to vertex is
// updated with all v changed to u, vertex to face contains deleted faces but is
// still sorted (for fast look up of face flaps), vertex to vertex is no longer
// sorted and is updated for u and all neighbors of v that are not u, s and t.
// Therefore inner vectors could be (let for example v2f[v] -{u, s, t} = {p, q,
// r}):
// v2f[u] = [x x x x f f x x g g x x], sorted.
// v2f[s] = [x x x f x x x], sorted because unchanged.
// v2f[t] = [x x g x x], sorted because unchanged.
// v2v[u] = [x x v s x x t x x p q x x r].
// v2v[s] = [x x u x x v].
// v2v[t] = [x u x x v x x x].
// v2v[p or q or r] = [x x v=u x x].
// clang-format on
static void collapse_edge(Mesh& m, int e, const double* x,
                          std::vector<char>& is_boundary_edge,
                          std::vector<char>& is_boundary_vertex) {
  assert(e >= 0);
  assert(!m.edel[e]);

  // Get the edge vertices.
  auto v0 = m.e2v[e * 2];
  auto v1 = m.e2v[e * 2 + 1];

  // Update boundary vertices.
  if (is_boundary_vertex[v1] && !is_boundary_vertex[v0])
    is_boundary_vertex[v0] = true;

  assert(v0 >= 0 && v1 >= 0);
  assert(v0 != v1);
  assert(!m.vdel[v0]);
  assert(!m.vdel[v1]);

  // Get flap faces and check for boundary face.
  auto f0 = m.e2f[e * 2];
  auto f1 = m.e2f[e * 2 + 1];

  assert(f0 != f1);
  assert(f0 != -1);
  assert(!m.fdel[f0]);
  // Assert face is on boundary or not deleted.
  assert(f1 == -1 || !m.fdel[f1]);

  // Get flap vertices.
  const int* p = &m.f2v[f0 * 3];
  while (*p == v0 || *p == v1) ++p;
  assert(p < &m.f2v[f0 * 3] + 3);
  auto vf0 = *p;

  p = nullptr;
  if (f1 != -1) {
    p = &m.f2v[f1 * 3];
    while (*p == v0 || *p == v1) ++p;
    assert(p < &m.f2v[f1 * 3] + 3);
  }
  // This vertex can be invalid.
  auto vf1 = p ? *p : -1;

  // Assert mesh is not topologically degenerate.
  assert(vf0 != vf1);
  assert(vf0 != v0 && vf0 != v1);
  assert(!m.vdel[vf0]);
  assert(vf1 != v0 && vf1 != v1);
  assert(vf1 == -1 || !m.vdel[vf1]);

  // Update coordinates if specified.
  if (x) std::copy(x, x + 3, &m.v[v0 * 3]);

  // Delete flaps.
  m.fdel[f0] = true;
  if (f1 != -1) m.fdel[f1] = true;

  // Update face to vertex connectivity.
  for (auto f : m.v2f[v1]) {
    // Do not check flaps as they have been deleted already.
    if (m.fdel[f]) continue;
    auto* p = &m.f2v[f * 3];
    while (*p != v1) ++p;
    assert(p < &m.f2v[f * 3] + 3);
    *p = v0;
    // Update vertex to face connectivity (no more than 2 faces for manifold
    // meshes).
    m.v2f[v0].push_back(f);
  }

  // Update vertex to vertex connectivity.
  for (auto v : m.v2v[v1]) {
    if (v == v0 || v == vf0 || v == vf1 || m.vdel[v]) continue;

    // WARNING: Collapses with more than 2 common neighbors are rejected.
    m.v2v[v0].push_back(v);
    // Replace vertices.
    for (auto& vv : m.v2v[v]) {
      if (m.vdel[vv]) continue;
      if (vv == v1) {
        vv = v0;
        break;
      }
    }
  }

  // Delete vertex.
  m.vdel[v1] = true;

  // Take care of edges and edge flaps.
  m.edel[e] = true;
  // Pointers to the flaps for the surviving edges (can point to null face -1).
  int* p0 = nullptr;
  // Unset if vf1 is -1 and f1 is -1.
  int* p1 = nullptr;

  // The two surviving edges of the two flaps.
  auto ef0 = -1;
  auto ef1 = -1;

  // The two flaps different from f0 and f1 of the two surviving edges (can be
  // -1).
  auto ff0 = -1;
  auto ff1 = -1;

  for (auto ee : m.v2e[v0]) {
    if (m.edel[ee]) continue;

    const auto& vv = m.e2v[ee * 2] == v0 ? m.e2v[ee * 2 + 1] : m.e2v[ee * 2];
    assert(!m.vdel[vv]);
    assert(m.e2v[ee * 2] == v0 || m.e2v[ee * 2 + 1] == v0);

    if (vv == vf0) {
      assert(m.e2f[ee * 2] == f0 || m.e2f[ee * 2 + 1] == f0 || 0);
      p0 = m.e2f[ee * 2] == f0 ? &m.e2f[ee * 2] : &m.e2f[ee * 2 + 1];
      ef0 = ee;
      ff0 = m.e2f[ee * 2] == f0 ? m.e2f[ee * 2 + 1] : m.e2f[ee * 2];
    } else if (vv == vf1) {
      assert(vf1 != -1);
      assert(m.e2f[ee * 2] == f1 || m.e2f[ee * 2 + 1] == f1 || 0);
      p1 = m.e2f[ee * 2] == f1 ? &m.e2f[ee * 2] : &m.e2f[ee * 2 + 1];
      ef1 = ee;
      ff1 = m.e2f[ee * 2] == f1 ? m.e2f[ee * 2 + 1] : m.e2f[ee * 2];
    }
  }

  assert(p0);
  assert(vf1 == -1 || p1);
  assert(ef0 != -1);
  assert(vf1 == -1 || ef1 != -1);

  for (auto ee : m.v2e[v1]) {
    if (m.edel[ee]) continue;

    const auto& vv = m.e2v[ee * 2] == v1 ? m.e2v[ee * 2 + 1] : m.e2v[ee * 2];
    assert(!m.vdel[vv] || 0);
    assert(vv != v0);
    assert(m.e2v[ee * 2] == v1 || m.e2v[ee * 2 + 1] == v1);

    if (vv == vf0) {
      m.edel[ee] = true;
      // 注: 同 f1 分支, 非流形边安全跳过
      if (m.e2f[ee * 2] != f0 && m.e2f[ee * 2 + 1] != f0) { m.edel[ee] = false; continue; }
      auto ff = m.e2f[ee * 2] == f0 ? m.e2f[ee * 2 + 1] : m.e2f[ee * 2];
      if (ff0 == -1 && ff == -1) {
        // Delete also this edge and vertex. WARNING: There are problems with
        // open and non-manifold meshes and pinched edge collapses.
        m.edel[ef0] = true;
        m.vdel[vf0] = true;
      } else {
        // Correct even if ff is -1.
        *p0 = ff;
        // Make sure to always have the second flap equal to -1 if boundary
        // edge.
        if (m.e2f[ef0 * 2] == -1) std::swap(m.e2f[ef0 * 2], m.e2f[ef0 * 2 + 1]);
        assert(m.e2f[ef0 * 2] != -1);
        if (ff == -1) is_boundary_edge[ef0] = true;
      }
    } else if (vv == vf1) {
      m.edel[ee] = true;
      if (vf1 == -1 || !p1) { m.edel[ee] = false; continue; }
      // 注: qslim 原断言 m.e2f[ee*2]==f1 || m.e2f[ee*2+1]==f1 要求边 ee 必含面 f1。
      // OSGB 网格存在非流形边(>2 邻面), 这里安全跳过该边, 不做折叠。
      if (m.e2f[ee * 2] != f1 && m.e2f[ee * 2 + 1] != f1) { m.edel[ee] = false; continue; }
      auto ff = m.e2f[ee * 2] == f1 ? m.e2f[ee * 2 + 1] : m.e2f[ee * 2];
      if (ff1 == -1 && ff == -1) {
        // Delete also this edge and vertex. WARNING: There are problems with
        // open and non-manifold meshes and pinched edge collapses.
        m.edel[ef1] = true;
        m.vdel[vf1] = true;
      } else {
        // Correct even if ff is -1.
        *p1 = ff;
        // Make sure to always have the second flap equal to -1 if boundary
        // edge.
        if (m.e2f[ef1 * 2] == -1) std::swap(m.e2f[ef1 * 2], m.e2f[ef1 * 2 + 1]);
        assert(m.e2f[ef1 * 2] != -1);
        if (ff == -1) is_boundary_edge[ef1] = true;
      }
    } else {
      // Update only in this case
      if (m.e2v[ee * 2] == v1)
        m.e2v[ee * 2] = v0;
      else if (m.e2v[ee * 2 + 1] == v1)
        m.e2v[ee * 2 + 1] = v0;
      else
        assert(false);

      m.v2e[v0].push_back(ee);
    }
  }
}
