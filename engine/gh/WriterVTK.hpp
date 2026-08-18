#pragma once

#include <algorithm>
#include <cassert>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <utility>
#include <vector>

// TODO rethink design to make it easy to use but templatizable
// only fixed number of points size cells are supported
class WriterVTK {
 public:
  enum { LINE = 3, TRIANGLE = 5, QUAD = 9, POLYGON = 7, POINT = -1, CELL = -2 };

 public:
  bool write(std::string_view filepath,
             std::string_view header = std::string_view{}) {
    std::ofstream ofs(std::string{filepath});

    if (!ofs.is_open()) {
      std::cerr << "WARNING: cannot open file " << filepath << "\n";
      return false;
    } else {
      ofs << "# vtk DataFile Version 3.0\n"
          << (header.empty() ? "default header" : header)
          << "\nASCII\nDATASET UNSTRUCTURED_GRID\n";

      // TODO this does not make sense if some buffer is not filled
      if (!print_points(ofs)) return false;
      if (!print_cells(ofs)) return false;
      if (!print_scalars(ofs)) return false;

      return true;
    }
  }

  void add_point_buffer(const double* ptr, uint64_t size, int dim) {
    assert(ptr);
    assert(size);
    points.emplace_back(ptr, size);
    point_dimensions.push_back(dim);
  }

  void add_cell_buffer(const int* ptr, uint64_t size, int cell_type) {
    assert(ptr);
    assert(size);
    cells.emplace_back(ptr, size);
    cell_types.push_back(cell_type);
  }
  
  void add_scalar_buffer(const double* ptr, uint64_t size, int scalar_type) {
    assert(ptr);
    assert(size);
    scalars.emplace_back(ptr, size);
    scalar_types.push_back(scalar_type);
  }

  void clear() {
    points.clear();
    points.shrink_to_fit();
    point_dimensions.clear();
    point_dimensions.shrink_to_fit();
    cells.clear();
    cells.shrink_to_fit();
    cell_types.clear();
    cell_types.shrink_to_fit();
    scalars.clear();
    scalars.shrink_to_fit();
    scalar_types.clear();
    scalar_types.shrink_to_fit();
  }

 private:
  bool print_points(std::ofstream& ofs) {
    if (!ofs) return false;

    uint64_t total_size = 0;
    for (const auto [_, size] : points) total_size += size;

    ofs << "POINTS " << total_size << ' ' << "double\n";

    size_t i = 0;
    for (const auto [ptr, size] : points) {
      const int dim = point_dimensions[i++];
      for (size_t p = 0; p < size; ++p) {
        ofs << ptr[dim * p] << ' ' << ptr[dim * p + 1] << ' ';
        if (dim == 3) {
          ofs << ptr[dim * p + 2] << '\n';
        } else
          ofs << 0.0 << '\n';
      }
    }

    return true;
  }

  bool print_cells(std::ofstream& ofs) {
    if (!ofs) return false;

    uint64_t total_size{0};
    uint64_t list_size{0};

    size_t i = 0;
    for (const auto [_, size] : cells) {
      static_cast<void>(_);
      const auto num_points = get_cell_num_points(cell_types[i++]);
      list_size += size * (1 + num_points);
      total_size += size;
    }

    ofs << "CELLS " << total_size << ' ' << list_size << '\n';

    for (size_t i = 0; i < cells.size(); ++i) {
      const auto [ptr, size] = cells[i];
      const auto num_points = get_cell_num_points(cell_types[i]);

      for (size_t c = 0; c < size; ++c) {
        ofs << num_points;
        for (size_t p = 0; p < num_points; ++p) {
          ofs << ' ' << ptr[c * num_points + p];
        }
        ofs << '\n';
      }
    }

    ofs << "CELL_TYPES " << total_size << '\n';

    for (size_t i = 0; i < cells.size(); ++i)
      std::fill_n(std::ostream_iterator<int>{ofs, "\n"}, cells[i].second,
                  cell_types[i]);

    return true;
  }

  bool print_scalars(std::ofstream& ofs) {
    if (!ofs) return false;

    size_t i = 0;
    for (const auto [ptr, size] : scalars) {
      auto type = scalar_types[i];

      ofs << get_c_str_type(type) << "_DATA " << size << '\n';
      ofs << "SCALARS "
          << "scalar_data" << std::to_string(i) << " double\n";
      ofs << "LOOKUP_TABLE default\n";
      for (size_t s = 0; s < size; ++s) ofs << ptr[s] << '\n';

      ++i;
    }

    return true;
  }

  const char* get_c_str_type(int type) {
    if (type == POINT) return "POINT";
    if (type == CELL) return "CELL";
    std::cerr << "ERROR: type not supported\n";
    exit(1);
    return "";
  }

  uint64_t get_cell_num_points(int cell_type) {
    if (cell_type == LINE) return 2;
    if (cell_type == TRIANGLE) return 3;
    if (cell_type == QUAD) return 4;
    std::cerr << "ERROR: cell type not supported\n";
    exit(1);
    return -1;
  }

 private:
  std::vector<std::pair<const double*, uint64_t>> points;
  std::vector<int> point_dimensions;
  std::vector<std::pair<const int*, uint64_t>> cells;
  std::vector<int> cell_types;
  std::vector<std::pair<const double*, uint64_t>> scalars;
  std::vector<int> scalar_types;
};
