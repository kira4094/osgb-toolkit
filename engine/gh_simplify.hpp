// gh_simplify.hpp — qslim GH 核心的桥接封装
// OSG Geometry → Mesh → 按连通组件拆分 → 逐组件 GH 简化 → 合并 → 写回 Geometry
// 去掉了 boost 依赖: connected_components 用 BFS 实现
// 去掉了 qslim 对流形网格的硬断言: 每个组件独立简化, 避免非流形边界崩溃
#pragma once
#ifndef _USE_MATH_DEFINES
#define _USE_MATH_DEFINES
#endif
#include <osg/Geometry>
#include <osg/Array>
#include <vector>
#include <queue>
#include <cstdint>
#include <cmath>
#include <tuple>
#include <functional>
#include <algorithm>

#include "gh/Mesh.hpp"
#include "gh/Quadric.hpp"
#include "gh/collapse_edge.hpp"
#include "gh/compress_buffer.hpp"
#include "gh/find_boundary_edges.hpp"
#include "gh/find_buffer_duplicates.hpp"
#include "gh/find_duplicate_faces.hpp"
#include "gh/find_non_manifold_faces.hpp"
#include "gh/get_optimal_position.hpp"
#include "gh/make_compressed.hpp"
#include "gh/make_edge_heap.hpp"
#include "gh/make_edges.hpp"
#include "gh/make_face_normals_and_areas.hpp"
#include "gh/make_topology.hpp"
#include "gh/make_vertex_quadric.hpp"
#include "gh/make_vertex_quadrics.hpp"
#include "gh/split_into_connected_components.hpp"
#include "gh/test_collapse_shared_neighbors.hpp"
#include "gh/test_collapse_normal_flipping.hpp"
#include "gh/make_face_quadrics.hpp"

// 策略 → 法线翻转容差角(cos 值)
//   strategy: 0=triangular(60°) 1=prob_triangular(45°) 2=planar(30°) 3=prob_planar(20°)
static double strategyAngle(int strategy) {
    switch (strategy) {
        case 1: return std::cos(M_PI / 4.0);
        case 2: return std::cos(M_PI / 6.0);
        case 3: return std::cos(M_PI / 9.0);
        default: return std::cos(M_PI / 3.0);
    }
}

// BFS 连通组件(替换 boost::connected_components)
static void connected_components_bfs(const std::vector<std::vector<int>>& f2f,
                                     std::vector<int>& f2cc) {
    int n = (int)f2f.size();
    f2cc.assign(n, -1);
    int comp = 0;
    std::queue<int> q;
    for (int start = 0; start < n; ++start) {
        if (f2cc[start] >= 0) continue;
        f2cc[start] = comp;
        q.push(start);
        while (!q.empty()) {
            int f = q.front(); q.pop();
            for (int nb : f2f[f]) {
                if (f2cc[nb] < 0) { f2cc[nb] = comp; q.push(nb); }
            }
        }
        ++comp;
    }
}

// 从 OSG Geometry 提取 Mesh(顶点 + 三角索引)
// 支持 DrawElementsUInt/UShort/UByte 和 DrawArrays 的所有三角形模式
static bool mesh_from_geometry(osg::Geometry* geom, Mesh& m) {
    osg::Vec3Array* va = dynamic_cast<osg::Vec3Array*>(geom->getVertexArray());
    if (!va || va->empty()) return false;
    m.v.clear(); m.v.reserve(va->size() * 3);
    for (const auto& v : *va) { m.v.push_back(v.x()); m.v.push_back(v.y()); m.v.push_back(v.z()); }

    std::vector<int> tris;
    auto emit_tris = [&tris](GLenum mode, unsigned n, const std::function<unsigned(unsigned)>& idx) {
        if (mode == GL_TRIANGLES) {
            for (unsigned i = 0; i + 2 < n; i += 3)
                { tris.push_back((int)idx(i)); tris.push_back((int)idx(i+1)); tris.push_back((int)idx(i+2)); }
        } else if (mode == GL_TRIANGLE_STRIP) {
            for (unsigned i = 0; i + 2 < n; ++i)
                { tris.push_back((int)idx(i)); tris.push_back((int)idx(i+1)); tris.push_back((int)idx(i+2)); }
        } else if (mode == GL_TRIANGLE_FAN) {
            for (unsigned i = 1; i + 1 < n; ++i)
                { tris.push_back((int)idx(0)); tris.push_back((int)idx(i)); tris.push_back((int)idx(i+1)); }
        } else if (mode == GL_QUADS) {
            for (unsigned i = 0; i + 3 < n; i += 4)
                { tris.push_back((int)idx(i)); tris.push_back((int)idx(i+1)); tris.push_back((int)idx(i+2));
                  tris.push_back((int)idx(i)); tris.push_back((int)idx(i+2)); tris.push_back((int)idx(i+3)); }
        }
    };

    osg::Geometry::PrimitiveSetList& prims = geom->getPrimitiveSetList();
    for (auto& p : prims) {
        GLenum mode = p->getMode();
        if (osg::DrawElementsUInt* de = dynamic_cast<osg::DrawElementsUInt*>(p.get())) {
            emit_tris(mode, de->size(), [&](unsigned i){ return (unsigned)(*de)[i]; });
        } else if (osg::DrawElementsUShort* de = dynamic_cast<osg::DrawElementsUShort*>(p.get())) {
            emit_tris(mode, de->size(), [&](unsigned i){ return (unsigned)(*de)[i]; });
        } else if (osg::DrawElementsUByte* de = dynamic_cast<osg::DrawElementsUByte*>(p.get())) {
            emit_tris(mode, de->size(), [&](unsigned i){ return (unsigned)(*de)[i]; });
        } else if (osg::DrawArrays* da = dynamic_cast<osg::DrawArrays*>(p.get())) {
            unsigned first = da->getFirst(), count = da->getCount();
            emit_tris(mode, count, [&](unsigned i){ return first + i; });
        }
    }
    if (tris.empty()) return false;
    m.f2v = tris;

    osg::Vec2Array* ta = dynamic_cast<osg::Vec2Array*>(geom->getTexCoordArray(0));
    if (ta && !ta->empty()) {
        m.t.clear(); m.t.reserve(ta->size() * 2);
        for (const auto& uv : *ta) { m.t.push_back(uv.x()); m.t.push_back(uv.y()); }
    }
    return true;
}

// 简化后的 Mesh 写回 OSG Geometry
static bool geometry_from_mesh(osg::Geometry* geom, const Mesh& m) {
    unsigned nv = m.num_vertices();
    auto va = new osg::Vec3Array;
    va->reserve(nv);
    for (unsigned i = 0; i < nv; ++i) va->push_back(osg::Vec3(m.v[i*3], m.v[i*3+1], m.v[i*3+2]));
    geom->setVertexArray(va);

    unsigned nf = m.num_faces();
    auto de = new osg::DrawElementsUInt(GL_TRIANGLES, 0);
    de->reserve(nf * 3);
    for (unsigned i = 0; i < nf * 3; ++i) de->push_back((unsigned)m.f2v[i]);
    geom->removePrimitiveSet(0, geom->getNumPrimitiveSets());
    geom->addPrimitiveSet(de);

    if (!m.t.empty() && m.num_texture() > 0) {
        auto ta = new osg::Vec2Array;
        ta->reserve(m.num_texture());
        for (unsigned i = 0; i < m.num_texture(); ++i) ta->push_back(osg::Vec2(m.t[i*2], m.t[i*2+1]));
        geom->setTexCoordArray(0, ta);
    }
    return true;
}

// 对单个流形组件执行 GH 边折叠
// 返回折叠后的面数
static unsigned gh_collapse_component(Mesh& m, unsigned target, double normalFlipCos,
                                      bool verbose) {
    if (m.num_faces() <= target) return m.num_faces();

    // 边界检测
    std::vector<char> is_boundary_edge(m.num_edges(), false);
    find_boundary_edges(m, is_boundary_edge);
    std::vector<char> is_boundary_vertex(m.num_vertices(), false);
    for (auto e = 0; e < m.num_edges(); ++e) {
        if (is_boundary_edge[e]) {
            is_boundary_vertex[m.e2v[e*2]] = true;
            is_boundary_vertex[m.e2v[e*2+1]] = true;
        }
    }

    auto vq = make_vertex_quadrics(m, is_boundary_edge, is_boundary_vertex);
    std::vector<std::tuple<double,int,int>> eh;
    std::vector<Eigen::Vector3d> xs;
    make_edge_heap(m, vq, eh, xs);
    constexpr auto cmp = [](const auto& l, const auto& r) { return std::get<0>(l) > std::get<0>(r); };
    std::vector<int> times(m.num_edges(), 0);

    long long attempts = 0, collapsed = 0;
    auto num_faces = m.num_faces();
    auto tgt = std::max(4u, target);
    for (auto i = 0; num_faces > tgt && !eh.empty(); ++i) {
        const auto& [c, e, t] = eh.front();
        const auto* x = &(xs[e][0]);
        auto v0 = m.e2v[e*2];
        auto v1 = m.e2v[e*2+1];
        std::vector<std::tuple<int, Eigen::Vector3d, double>> ns;
        ++attempts;
        if (m.edel[e] || t < times[e] ||
            !test_collapse_shared_neighbors(m, e, is_boundary_edge) ||
            !test_collapse_normal_flipping(m, e, x, normalFlipCos, ns)) {
            std::pop_heap(eh.begin(), eh.end(), cmp);
            eh.pop_back();
        } else {
            collapse_edge(m, e, x, is_boundary_edge, is_boundary_vertex);
            num_faces -= is_boundary_edge[e] ? 1 : 2;
            ++collapsed;
            for (const auto& [f, n, a] : ns) {
                std::copy(&n[0], &n[0]+3, &m.fn[f*3]);
                m.fa[f] = a;
            }
            vq[v0].A += vq[v1].A; vq[v0].b += vq[v1].b; vq[v0].c += vq[v1].c;
            std::pop_heap(eh.begin(), eh.end(), cmp);
            eh.pop_back();
            for (auto e2 : m.v2e[v0]) {
                if (m.edel[e2]) continue;
                auto v2 = m.e2v[e2*2] == v0 ? m.e2v[e2*2+1] : m.e2v[e2*2];
                if (m.vdel[v2]) continue;
                Quadric q;
                q.A = vq[v0].A + vq[v2].A; q.b = vq[v0].b + vq[v2].b; q.c = vq[v0].c + vq[v2].c;
                Eigen::Vector3d x2;
                if (!get_optimal_position(q, x2)) {
                    Eigen::Vector3d x0{&m.v[v0*3]}; Eigen::Vector3d x1{&m.v[v2*3]};
                    x2 = (x0 + x1) * 0.5;
                }
                xs[e2] = x2;
                ++times[e2];
                eh.emplace_back(vq[v0](x2), e2, times[e2]);
                std::push_heap(eh.begin(), eh.end(), cmp);
            }
        }
    }
    if (verbose) {
        std::cerr << "  [gh] comp attempts=" << attempts << " collapsed=" << collapsed
                  << " faces=" << num_faces << std::endl;
    }
    return num_faces;
}

// GH 简化主函数: 对单个 Geometry 执行边折叠到目标面数
// target_faces <= 0 表示不简化
// strategy: 0=triangular 1=prob_triangular 2=planar 3=prob_planar
static void gh_simplify_geometry(osg::Geometry* geom, int target_faces, int strategy) {
    Mesh m;
    if (!mesh_from_geometry(geom, m) || m.num_faces() == 0) return;
    unsigned before = m.num_faces();
    if (target_faces <= 0 || (unsigned)target_faces >= before) return;

    // ---- 预处理 ----
    {
        std::vector<char> dup(m.num_faces(), false);
        find_duplicate_faces(m, dup);
        m.f2v.resize(3 * compress_buffer<3>(m.f2v.data(), m.num_faces(), dup.data()));
    }
    {
        std::vector<char> nmf(m.num_faces(), false);
        find_non_manifold_faces(m.f2v, nmf);
        m.f2v.resize(3 * compress_buffer<3>(m.f2v.data(), m.num_faces(), nmf.data()));
    }
    {
        constexpr auto hash = [](const double* x) {
            const auto h0 = std::hash<double>{}(x[0]);
            const auto h1 = std::hash<double>{}(x[1]);
            const auto h2 = std::hash<double>{}(x[2]);
            return (h0 ^ (h1 << 1)) ^ h2;
        };
        std::vector<char> vflags(m.num_vertices(), false);
        std::vector<int> ind0(m.num_vertices(), -1);
        std::vector<int> ind1(m.num_vertices(), -1);
        find_buffer_duplicates<3>(hash, m.v.data(), m.num_vertices(), vflags.data(), ind0.data());
        m.v.resize(compress_buffer<3>(m.v.data(), m.num_vertices(), vflags.data(), ind1.data()) * 3);
        for (auto& v : m.f2v) v = ind1[ind0[v]];
    }
    if (m.num_faces() == 0) return;
    make_face_normals_and_areas(m);
    make_topology(m);
    make_edges(m);
    m.fdel.assign(m.num_faces(), false);
    m.vdel.assign(m.num_vertices(), false);
    m.edel.assign(m.num_edges(), false);

    // ---- 按连通组件拆分 ----
    std::vector<int> f2cc(m.num_faces());
    connected_components_bfs(m.f2f, f2cc);
    int ncomp = 0;
    for (auto c : f2cc) ncomp = std::max(ncomp, c + 1);
    std::cerr << "  [gh] preprocess done: V=" << m.num_vertices()
              << " F=" << m.num_faces() << " comps=" << ncomp << std::endl;
    if (ncomp <= 1) {
        // 单组件直接简化
        gh_collapse_component(m, (unsigned)target_faces, strategyAngle(strategy), true);
        make_compressed(m);
        geometry_from_mesh(geom, m);
        return;
    }

    // 多组件: 拆开, 每组件按面数比例分配目标, 分别简化, 再合并
    std::vector<std::vector<int>> cc2f(ncomp);
    for (auto f = 0; f < m.num_faces(); ++f) cc2f[f2cc[f]].push_back(f);
    std::vector<Mesh> ms;
    split_into_connected_components(m, cc2f, ms);

    double flipCos = strategyAngle(strategy);
    Mesh result;
    int vofs = 0;
    for (auto& mc : ms) {
        if (mc.num_faces() < 4) continue;
        // 组件拆分后必须重建拓扑(make_topology/make_edges), qslim 原版 main.cpp 如此
        make_face_normals_and_areas(mc);
        make_topology(mc);
        make_edges(mc);
        mc.fdel.assign(mc.num_faces(), false);
        mc.vdel.assign(mc.num_vertices(), false);
        mc.edel.assign(mc.num_edges(), false);
        int mcTarget = (int)((double)target_faces * (double)mc.num_faces() / (double)before);
        if (mcTarget < 4) mcTarget = 4;
        if ((unsigned)mcTarget < mc.num_faces()) {
            gh_collapse_component(mc, (unsigned)mcTarget, flipCos, true);
        }
        make_compressed(mc);
        // 合并: 顶点追加, 面索引加偏移
        int vbase = vofs;
        for (auto i = 0; i < (int)mc.v.size(); ++i) result.v.push_back(mc.v[i]);
        if (!mc.t.empty()) {
            if (result.t.empty()) result.t.resize(vbase * 2, 0.0);
            result.t.insert(result.t.end(), mc.t.begin(), mc.t.end());
        }
        for (auto f = 0; f < mc.num_faces(); ++f) {
            result.f2v.push_back(mc.f2v[f*3] + vbase);
            result.f2v.push_back(mc.f2v[f*3+1] + vbase);
            result.f2v.push_back(mc.f2v[f*3+2] + vbase);
        }
        vofs += (int)mc.num_vertices();
    }
    if (result.f2v.empty()) return;
    geometry_from_mesh(geom, result);
}
