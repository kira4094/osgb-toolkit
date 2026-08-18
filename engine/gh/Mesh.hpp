#pragma once

#include <vector>

struct Mesh {
  std::vector<double> v;
  std::vector<double> t;
  std::vector<double> n;
  std::vector<int> f2v;
  std::vector<int> f2t;
  std::vector<int> f2n;

  auto num_faces() const { return f2v.size() / 3; }
  auto num_vertices() const { return v.size() / 3; }
  auto num_normals() const { return n.size() / 3; }
  auto num_texture() const { return t.size() / 2; }

  std::vector<std::vector<int>> v2f;
  std::vector<std::vector<int>> v2v;
  std::vector<std::vector<int>> f2f;

  std::vector<int> e2v;
  std::vector<std::vector<int>> v2e;
  std::vector<int> e2f;

  auto num_edges() const { return e2v.size() / 2; }

  std::vector<double> fn;
  std::vector<double> fa;

  // Mark if a face is deleted.
  std::vector<char> vdel;
  std::vector<char> fdel;
  std::vector<char> edel;
};